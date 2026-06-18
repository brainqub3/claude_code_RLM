#!/usr/bin/env python3
"""Run the OOLONG (trec_coarse) eval with PLAIN Claude Code (no RLM), capturing
score-ready predictions plus token/cost usage and wall-clock time.

Two non-RLM baselines, selectable via --modes:

  * base  -- a single `claude -p` call per item with the FULL context in the
             prompt and TOOLS OFF. A pure long-context base-model forward pass,
             directly comparable to the paper's "base model" row.
  * agent -- a `claude -p` agentic session per item: Claude Code is pointed at the
             context FILE PATH with its default tools on (permission checks
             bypassed so it runs headless) and solves however it likes. Measures
             "Claude Code as an agent", not pure long-context reasoning.

Both are genuinely non-RLM: the RLM skill is not invoked, and (run from this
folder, outside the RLM repo) is not even on the skill path.

For each (item, mode) it records {id, output, total_tokens, total_cost_usd} to a
per-mode predictions file you then score with score.py. Usage is summed from
`claude -p --output-format json` (input+output+cache tokens, and total_cost_usd).

Outputs (under this folder):
  preds_base_<model>.jsonl    -- predictions for the base-model baseline
  preds_agent_<model>.jsonl   -- predictions for the agent baseline
  _runs/plain_run.json        -- full diagnostics (per item/mode: timing, usage, output)

Usage:
  python run_plain_eval.py --model opus --modes base,agent
  python run_plain_eval.py --model opus --modes base --ids 17000208   # smoke test
  python score.py --predictions preds_base_opus.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make logging robust to non-ASCII model output on Windows (cp1252 stdout would
# otherwise raise UnicodeEncodeError when a prediction contains e.g. a checkmark).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "data" / "oolong_trec_coarse.jsonl"
RUNLOG_OUT = HERE / "_runs" / "plain_run.json"

BASE_SYSTEM = (
    "You are answering a question about a dataset provided to you in full in the "
    "prompt. Base your answer on the ENTIRE dataset. Output ONLY your final answer "
    "as the last line, in the EXACT format the question requests (e.g. 'Label: <x>' "
    "or 'Answer: <n>'), with no preamble or explanation."
)

AGENT_PROMPT_TEMPLATE = """\
You are benchmarking a long-context aggregation task. A dataset file is on disk:

  PATH: {path}

It contains 3182 general-knowledge questions, one per line, in the format
"Date: ... || User: ... || Instance: <question>". Each question's answer falls into
exactly one of 6 categories: numeric value, entity, human being, location,
abbreviation, description and abstract concept. The category labels are NOT in the
file -- you must determine each question's category yourself.

IMPORTANT: the file is ~3190 lines / ~131K tokens, which is larger than a single
file read returns by default. Make sure your answer accounts for ALL 3182
questions (read the file in parts, or use shell tools), not just the first portion.

Task: {question}

Use whatever approach you like (read the file, write and run a script, etc.). When
done, end your reply with a single final line in EXACTLY the format the task
requests (e.g. 'Label: <x>' or 'Answer: <n>') and nothing after it.
"""


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        sys.exit("ERROR: `claude` CLI not found on PATH.")
    return exe


CLAUDE: Optional[str] = None


def _usage_tokens(d: Dict[str, Any]) -> int:
    u = d.get("usage") or {}
    return sum(int(u.get(k, 0) or 0) for k in (
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens"))


def run_call(cmd: List[str], stdin: str, timeout: int) -> Dict[str, Any]:
    """Run one `claude -p ... --output-format json` call. Returns
    {ok, text, tokens, cost, err}. Never raises."""
    try:
        res = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                             timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "tokens": 0, "cost": 0.0, "err": f"TIMEOUT/{timeout}s"}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "text": "", "tokens": 0, "cost": 0.0, "err": f"{type(e).__name__}:{e}"}
    if res.returncode != 0 and not (res.stdout or "").strip():
        return {"ok": False, "text": "", "tokens": 0, "cost": 0.0,
                "err": f"rc={res.returncode} {(res.stderr or '')[:200]}"}
    try:
        d = json.loads(res.stdout)
    except Exception as e:
        return {"ok": False, "text": "", "tokens": 0, "cost": 0.0,
                "err": f"jsonparse:{e} head={res.stdout[:200]!r}"}
    return {"ok": not bool(d.get("is_error")), "text": (d.get("result") or "").strip(),
            "tokens": _usage_tokens(d), "cost": float(d.get("total_cost_usd") or 0.0),
            "err": "" if not d.get("is_error") else "is_error"}


def call_base(item: Dict[str, Any], model: str, timeout: int) -> Dict[str, Any]:
    global CLAUDE
    CLAUDE = CLAUDE or _claude_exe()
    ctx = (HERE / "data" / Path(item["context_file"])).read_text(encoding="utf-8")
    stdin = ctx + "\n\n" + item["question"]
    cmd = [CLAUDE, "-p", "--model", model, "--allowedTools", "",
           "--append-system-prompt", BASE_SYSTEM, "--output-format", "json"]
    return run_call(cmd, stdin, timeout)


def call_agent(item: Dict[str, Any], model: str, timeout: int) -> Dict[str, Any]:
    global CLAUDE
    CLAUDE = CLAUDE or _claude_exe()
    ctx_path = (HERE / "data" / Path(item["context_file"])).resolve()
    stdin = AGENT_PROMPT_TEMPLATE.format(path=str(ctx_path), question=item["question"])
    cmd = [CLAUDE, "-p", "--model", model,
           "--permission-mode", "bypassPermissions",
           "--disallowedTools", "WebSearch", "WebFetch",
           "--output-format", "json"]
    return run_call(cmd, stdin, timeout)


MODES = {"base": call_base, "agent": call_agent}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--modes", default="base,agent", help="comma list of: base, agent")
    ap.add_argument("--ids", default=None, help="comma-separated subset of item ids")
    ap.add_argument("--base-timeout", type=int, default=600)
    ap.add_argument("--agent-timeout", type=int, default=1500)
    args = ap.parse_args(argv)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in MODES:
            sys.exit(f"unknown mode {m!r}; choose from {sorted(MODES)}")

    items = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        items = [it for it in items if int(it["id"]) in want]

    RUNLOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    preds_paths = {m: HERE / f"preds_{m}_{args.model}.jsonl" for m in modes}
    preds_lines: Dict[str, List[str]] = {m: [] for m in modes}
    diagnostics: List[Dict[str, Any]] = []

    t_run = time.time()
    print(f"PLAIN (non-RLM) OOLONG eval | model={args.model} modes={modes} | {len(items)} items",
          flush=True)
    print("=" * 80, flush=True)

    for n, item in enumerate(items, 1):
        iid = int(item["id"])
        for mode in modes:
            timeout = args.base_timeout if mode == "base" else args.agent_timeout
            print(f"[{n}/{len(items)}] id={iid} {item['task']} cw{item['context_window_id']} "
                  f"| mode={mode}", flush=True)
            t0 = time.time()
            r = MODES[mode](item, args.model, timeout)
            dt = time.time() - t0
            out = r["text"] if r["ok"] else f"[{mode} ERROR: {r['err']}]"
            last = out.replace("\n", " ")[-90:]
            print(f"      -> {last!r}", flush=True)
            print(f"      [{dt:.1f}s, {r['tokens']:,} tok, ${r['cost']:.4f}"
                  + ("" if r["ok"] else f", ERR={r['err']}") + "]", flush=True)

            preds_lines[mode].append(json.dumps({
                "id": iid, "output": out,
                "total_tokens": r["tokens"], "total_cost_usd": round(r["cost"], 6)}))
            preds_paths[mode].write_text("\n".join(preds_lines[mode]) + "\n", encoding="utf-8")
            diagnostics.append({
                "id": iid, "mode": mode, "task": item["task"],
                "answer_type": item["answer_type"], "gold": item["answer"],
                "ok": r["ok"], "err": r["err"], "output": out,
                "wall_seconds": round(dt, 2),
                "total_tokens": r["tokens"], "total_cost_usd": round(r["cost"], 6)})
            RUNLOG_OUT.write_text(json.dumps({
                "model": args.model, "modes": modes, "started_unix": t_run,
                "elapsed_seconds_so_far": round(time.time() - t_run, 2),
                "items": diagnostics}, indent=2), encoding="utf-8")
        print("-" * 80, flush=True)

    total_dt = time.time() - t_run
    print("=" * 80, flush=True)
    for mode in modes:
        rows = [d for d in diagnostics if d["mode"] == mode]
        tok = sum(d["total_tokens"] for d in rows)
        cost = sum(d["total_cost_usd"] for d in rows)
        nbad = sum(1 for d in rows if not d["ok"])
        print(f"[{mode}] {len(rows)} items | {tok:,} tokens | ${cost:.4f}"
              + (f" | {nbad} failed" if nbad else "")
              + f" | preds -> {preds_paths[mode].name}", flush=True)
    print(f"TOTAL wall time: {total_dt:.1f}s ({total_dt/60:.1f} min)", flush=True)
    print(f"diagnostics -> {RUNLOG_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
