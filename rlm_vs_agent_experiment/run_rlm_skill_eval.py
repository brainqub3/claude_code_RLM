#!/usr/bin/env python3
"""Run the OOLONG (trec_coarse) eval with the GENERAL `/rlm` skill (LLM-as-root).

This is the RLM arm of the rlm-vs-agent experiment (issue #6). Unlike the agent
baselines (`agent_*/run_plain_eval.py`), here each item is solved by an *RLM root*:
a headless Claude Code session (`claude -p`, model = --root) that is given ONLY the
context file path and the question, told to **use the `rlm` skill**, and left to
author the decomposition itself. The root never reads the 131K context into its
window; it drives `.claude/skills/rlm/scripts/rlm_repl.py`, sub-queries a cheap
`haiku` leaf over chunks, and aggregates in Python.

Crucially this measures the *general skill*, self-authored at runtime:
  * The root is handed NO classify-then-count recipe, NO label taxonomy beyond what
    the benchmark question itself contains, and NO OOLONG-specific parsing.
  * The strategy (chunking, prompts, aggregation) is discovered by the root.

ALL usage is accounted for, root AND leaf, kept separate:
  * Root: the `claude -p --output-format stream-json` session's own usage/cost
    (its model turns: reading metadata, writing REPL code, reading truncated stdout).
  * Leaf: every `llm_query`/`llm_query_map` call spawns a SEPARATE `claude -p`
    subprocess whose usage is NOT in the root's JSON. We set RLM_LEAF_USAGE_LOG so
    the instrumented `llm_query` (see rlm_repl.py) appends each leaf call's usage to
    a per-task log; we sum it. Total = root + leaf.

Outputs (under rlm_skill_<root>/):
  preds_rlm_skill.jsonl    -- {id, output, total_tokens, total_cost_usd}  (TOTAL = root+leaf)
  diagnostics.json         -- per-task root/leaf/total split, wall time, turns, answers, notes
  _runs/task_<id>.stream.jsonl   -- raw root stream-json transcript (orchestration evidence)
  _runs/leaf_usage_<id>.jsonl    -- raw per-leaf-call usage records

Usage:
  python run_rlm_skill_eval.py --root opus                 # full 10-task arm
  python run_rlm_skill_eval.py --root opus --ids 17000206  # single-task smoke test
  python score.py --manifest oolong_trec_coarse.jsonl --predictions rlm_skill_opus/preds_rlm_skill.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Robust logging on Windows cp1252 stdout (model output may contain non-ASCII).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent                       # rlm_vs_agent_experiment/
REPO = HERE.parent                                            # repo root
MANIFEST = HERE / "oolong_trec_coarse.jsonl"
# The manifest's context_file paths (e.g. "contexts/trec_coarse_cw6.txt") are
# relative to the rlm skill's eval data directory.
CTX_ROOT = REPO / ".claude" / "skills" / "rlm" / "eval" / "data"
REPL = REPO / ".claude" / "skills" / "rlm" / "scripts" / "rlm_repl.py"
STATE_DIR = REPO / ".claude" / "rlm_state"
STATE_PKL = STATE_DIR / "state.pkl"

# Minimal, non-leaking root prompt. Mirrors the skill's own recursive-spawn prompt
# (rlm_repl.rlm_query): it names the file + REPL and tells the root to FOLLOW THE
# SKILL -- it does not hand over labels, a classify-then-count recipe, or parsing.
ROOT_PROMPT_TEMPLATE = """\
Use the rlm skill to answer a question about a large context file.

The context file is on disk at:
  {ctx}
The rlm REPL script is at:
  {repl}

Follow the rlm skill procedure exactly: initialise the REPL on that file (do NOT
read the context file into this conversation directly), probe its format, decompose
it, and sub-query the cheap leaf model over chunks with llm_query / llm_query_map.
Let Python do the counting/aggregation, then set the final answer in the REPL with
FINAL(...) or FINAL_VAR(...).

query = {question!r}

OPERATIONAL CONSTRAINTS (this is a single, non-interactive run):
- Do ALL work synchronously, in the foreground, within THIS session. Do NOT run
  commands in the background, do NOT use the Monitor tool, and do NOT wait for
  external events. A long llm_query_map call simply blocks until it returns -- that
  is expected; let it run to completion (the Bash timeout has been raised for this).
- Before you reply, run `python {repl} final` to confirm a final answer is stored.
  If it is not set, or your code has not processed ALL items in the context, finish
  that work first and then set FINAL.
- When everything is complete, reply with ONLY the final answer text, in the exact
  format the query requests, and nothing else.
"""


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        sys.exit("ERROR: `claude` CLI not found on PATH.")
    return exe


CLAUDE: Optional[str] = None
TOKEN_KEYS = ("input_tokens", "output_tokens",
              "cache_creation_input_tokens", "cache_read_input_tokens")
DISALLOWED_TOOLS = (
    "WebSearch", "WebFetch", "Monitor",
    # The RLM eval is a single synchronous root session. These tools can defer,
    # delegate, or resume work outside the captured root transcript.
    "ScheduleWakeup", "Task", "AskUserQuestion",
    "CronCreate", "CronDelete", "CronList",
    "RemoteTrigger", "PushNotification", "Workflow",
    "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate",
    "EnterPlanMode", "ExitPlanMode", "EnterWorktree", "ExitWorktree",
)
FORBIDDEN_RLM_TOOLS = {
    "ScheduleWakeup", "Task", "AskUserQuestion",
    "CronCreate", "CronDelete", "CronList",
    "RemoteTrigger", "PushNotification", "Workflow",
    "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate",
    "EnterPlanMode", "ExitPlanMode", "EnterWorktree", "ExitWorktree",
}


def _sum_usage(usage: Dict[str, Any]) -> int:
    return sum(int(usage.get(k, 0) or 0) for k in TOKEN_KEYS)


def _reset_state() -> None:
    """Wipe RLM state so each task's root starts cold (no leftover context/vars)."""
    shutil.rmtree(STATE_DIR, ignore_errors=True)


def _parse_root_stream(text: str, ctx_abs: str) -> Dict[str, Any]:
    """Parse a stream-json transcript: final result + usage + orchestration tally."""
    result_text = ""
    root_tokens = 0
    root_cost = 0.0
    num_turns: Optional[int] = None
    is_error = False
    err = ""
    tool_uses: Dict[str, int] = {}
    read_context_directly = False
    saw_result = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if t == "assistant":
            # tally tool_use blocks for orchestration evidence
            msg = d.get("message") or {}
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    tool_uses[name] = tool_uses.get(name, 0) + 1
                    if name in ("Read", "Grep", "Glob"):
                        # detect the skill-violating move: reading the context file directly
                        inp = block.get("input") or {}
                        blob = json.dumps(inp)
                        if ctx_abs and (ctx_abs in blob or Path(ctx_abs).name in blob):
                            read_context_directly = True
        elif t == "result":
            saw_result = True
            result_text = (d.get("result") or "").strip()
            usage = d.get("usage") or {}
            root_tokens = _sum_usage(usage)
            root_cost = float(d.get("total_cost_usd") or 0.0)
            num_turns = d.get("num_turns")
            is_error = bool(d.get("is_error"))
            if is_error:
                err = str(d.get("subtype") or d.get("result") or "is_error")[:200]
    return {
        "result": result_text, "root_tokens": root_tokens, "root_cost": root_cost,
        "num_turns": num_turns, "is_error": is_error, "err": err,
        "tool_uses": tool_uses, "read_context_directly": read_context_directly,
        "saw_result": saw_result,
    }


def _read_leaf_usage(log_path: Path) -> Dict[str, Any]:
    tokens, cost, calls, failed = 0, 0.0, 0, 0
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            calls += 1
            tokens += int(r.get("total_tokens", 0) or 0)
            cost += float(r.get("cost_usd", 0.0) or 0.0)
            if not r.get("ok", True):
                failed += 1
    return {"leaf_tokens": tokens, "leaf_cost": cost,
            "leaf_calls": calls, "leaf_failed": failed}


def _repl_final() -> str:
    """Read whatever the root stored via FINAL/FINAL_VAR (default state path)."""
    global CLAUDE
    try:
        res = subprocess.run(
            [sys.executable, str(REPL), "final"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(REPO), timeout=60,
        )
        if res.returncode == 0:
            return (res.stdout or "").strip()
    except Exception:
        pass
    return ""


def run_one(item: Dict[str, Any], root_model: str, arm_dir: Path,
            runs_dir: Path, timeout: int) -> Dict[str, Any]:
    global CLAUDE
    CLAUDE = CLAUDE or _claude_exe()
    iid = int(item["id"])
    ctx_abs = (CTX_ROOT / item["context_file"]).resolve()
    if not ctx_abs.exists():
        return {"id": iid, "ok": False, "err": f"context missing: {ctx_abs}",
                "output": "[runner ERROR: context file missing]"}

    leaf_log = (runs_dir / f"leaf_usage_{iid}.jsonl")
    stream_log = (runs_dir / f"task_{iid}.stream.jsonl")
    for p in (leaf_log, stream_log):
        p.unlink(missing_ok=True)

    _reset_state()

    env = dict(os.environ)
    env["RLM_SUB_MODEL"] = "haiku"          # leaf is haiku in all arms (issue #6)
    env["RLM_MAX_WORKERS"] = env.get("RLM_MAX_WORKERS", "8")
    env["RLM_MAX_DEPTH"] = "1"
    env["RLM_LEAF_USAGE_LOG"] = str(leaf_log.resolve())
    # Raise the root's Bash-tool timeout so a synchronous llm_query_map over all
    # chunks can block to completion in the foreground (in headless single-shot
    # mode a short bash timeout otherwise pushes the agentic root toward
    # background execution + Monitor, which never resumes).
    env["BASH_DEFAULT_TIMEOUT_MS"] = "1200000"   # 20 min
    env["BASH_MAX_TIMEOUT_MS"] = "1200000"

    prompt = ROOT_PROMPT_TEMPLATE.format(
        ctx=str(ctx_abs), repl=str(REPL), question=item["question"])
    cmd = [
        CLAUDE, "-p", "--model", root_model,
        "--permission-mode", "bypassPermissions",
        "--allowedTools", "Bash Read Write Edit Grep Glob Skill",
        "--disallowedTools", " ".join(DISALLOWED_TOOLS),
        "--output-format", "stream-json", "--verbose",
    ]

    t0 = time.time()
    ok, timed_out = True, False
    try:
        res = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            cwd=str(REPO), env=env,
        )
        raw = res.stdout or ""
    except subprocess.TimeoutExpired as e:
        timed_out = True
        ok = False
        raw = (e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes)
               else (e.stdout or "")) if e.stdout else ""
    dt = time.time() - t0

    stream_log.write_text(raw, encoding="utf-8")
    parsed = _parse_root_stream(raw, str(ctx_abs))
    leaf = _read_leaf_usage(leaf_log)
    repl_final = _repl_final()

    # Scored output: the REPL FINAL value is authoritative for an RLM. A verbal
    # root reply without FINAL/FINAL_VAR is not a completed RLM trajectory.
    output = repl_final or "[no answer produced]"
    forbidden_used = sorted(FORBIDDEN_RLM_TOOLS.intersection(parsed["tool_uses"]))
    if timed_out:
        ok = False
    elif not repl_final:
        ok = False
    elif forbidden_used:
        ok = False
    elif parsed["is_error"]:
        ok = False
    err = "TIMEOUT" if timed_out else parsed["err"]
    if not repl_final and not err:
        err = "NO_REPL_FINAL"
    if forbidden_used:
        err = (err + "; " if err else "") + "FORBIDDEN_TOOLS_USED=" + ",".join(forbidden_used)

    total_tokens = parsed["root_tokens"] + leaf["leaf_tokens"]
    total_cost = parsed["root_cost"] + leaf["leaf_cost"]

    return {
        "id": iid, "ok": ok and not timed_out,
        "timed_out": timed_out, "err": err,
        "task": item["task"], "answer_type": item["answer_type"],
        "gold": item["answer"], "context_file": item["context_file"],
        "output": output,
        "root_result": parsed["result"], "repl_final": repl_final,
        "root_tokens": parsed["root_tokens"], "root_cost": round(parsed["root_cost"], 6),
        "leaf_tokens": leaf["leaf_tokens"], "leaf_cost": round(leaf["leaf_cost"], 6),
        "leaf_calls": leaf["leaf_calls"], "leaf_failed": leaf["leaf_failed"],
        "total_tokens": total_tokens, "total_cost_usd": round(total_cost, 6),
        "wall_seconds": round(dt, 2), "num_turns": parsed["num_turns"],
        "tool_uses": parsed["tool_uses"],
        "read_context_directly": parsed["read_context_directly"],
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="root model alias, e.g. opus | sonnet | haiku")
    ap.add_argument("--ids", default=None, help="comma-separated subset of item ids")
    ap.add_argument("--timeout", type=int, default=3000, help="per-task root timeout (s)")
    args = ap.parse_args(argv)

    arm_dir = HERE / f"rlm_skill_{args.root}"
    runs_dir = arm_dir / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    preds_path = arm_dir / "preds_rlm_skill.jsonl"
    diag_path = arm_dir / "diagnostics.json"

    items = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        items = [it for it in items if int(it["id"]) in want]

    preds_lines: List[str] = []
    diagnostics: List[Dict[str, Any]] = []
    t_run = time.time()
    print(f"RLM-SKILL OOLONG eval | root={args.root} leaf=haiku | {len(items)} items", flush=True)
    print("=" * 80, flush=True)

    for n, item in enumerate(items, 1):
        iid = int(item["id"])
        print(f"[{n}/{len(items)}] id={iid} {item['task']} cw{item['context_window_id']} "
              f"| root={args.root}", flush=True)
        r = run_one(item, args.root, arm_dir, runs_dir, args.timeout)
        last = (r["output"] or "").replace("\n", " ")[-90:]
        print(f"      -> {last!r}", flush=True)
        print(f"      [{r['wall_seconds']:.1f}s, turns={r.get('num_turns')}, "
              f"root {r['root_tokens']:,}tok/${r['root_cost']:.4f} + "
              f"leaf {r['leaf_tokens']:,}tok/${r['leaf_cost']:.4f} "
              f"({r['leaf_calls']} calls) = ${r['total_cost_usd']:.4f}"
              + ("" if r["ok"] else f", ERR={r['err']}") + "]", flush=True)
        if r.get("read_context_directly"):
            print("      [WARN: root used Read/Grep/Glob on the context file directly]", flush=True)

        preds_lines.append(json.dumps({
            "id": iid, "output": r["output"],
            "total_tokens": r["total_tokens"], "total_cost_usd": r["total_cost_usd"]}))
        preds_path.write_text("\n".join(preds_lines) + "\n", encoding="utf-8")
        diagnostics.append(r)
        diag_path.write_text(json.dumps({
            "root_model": args.root, "leaf_model": "haiku",
            "started_unix": t_run, "elapsed_seconds_so_far": round(time.time() - t_run, 2),
            "items": diagnostics}, indent=2), encoding="utf-8")
        print("-" * 80, flush=True)

    total_dt = time.time() - t_run
    rt = sum(d["root_tokens"] for d in diagnostics)
    rc = sum(d["root_cost"] for d in diagnostics)
    lt = sum(d["leaf_tokens"] for d in diagnostics)
    lc = sum(d["leaf_cost"] for d in diagnostics)
    nbad = sum(1 for d in diagnostics if not d["ok"])
    print("=" * 80, flush=True)
    print(f"[rlm_skill_{args.root}] {len(diagnostics)} items"
          + (f" | {nbad} failed" if nbad else ""), flush=True)
    print(f"  ROOT : {rt:,} tok | ${rc:.4f}", flush=True)
    print(f"  LEAF : {lt:,} tok | ${lc:.4f}", flush=True)
    print(f"  TOTAL: {rt + lt:,} tok | ${rc + lc:.4f}", flush=True)
    print(f"  wall : {total_dt:.1f}s ({total_dt/60:.1f} min)", flush=True)
    print(f"  preds -> {preds_path}", flush=True)
    print(f"  diag  -> {diag_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
