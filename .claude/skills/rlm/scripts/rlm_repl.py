#!/usr/bin/env python3
"""Persistent REPL for Recursive Language Model (RLM) workflows in Claude Code.

This is a faithful instantiation of *Recursive Language Models* (Zhang, Kraska,
Khattab; arXiv:2512.24601), Algorithm 1, adapted to Claude Code's primitives.

Mental model (the paper's three design choices):
  1. SYMBOLIC HANDLE TO THE PROMPT. The long context P is loaded as a `context`
     variable inside this REPL. The root model (the main Claude Code conversation)
     only ever sees *metadata* about it (type, length, a short prefix) plus the
     *truncated* stdout of code it runs -- never the whole thing. This is what
     keeps an arbitrarily large prompt out of the root's context window.
  2. OUTPUT VIA A VARIABLE. The final answer is returned by setting it inside the
     REPL with FINAL(answer) or FINAL_VAR(varname), not by the root verbalizing it.
     So the answer can be larger than the root's output window.
  3. SYMBOLIC RECURSION. Code running *inside* this REPL can invoke the LLM
     programmatically, in loops, over slices of the context:
       - llm_query(prompt)      -> a single sub-LM call (a "leaf"; tools OFF).
       - llm_query_map(prompts) -> many leaf calls, run in parallel (batching).
       - rlm_query(context,q)   -> a full *recursive* RLM over a sub-context,
                                   used for sub-tasks too big for one leaf call;
                                   falls back to llm_query at the max depth.

The sub-LM is a nested *headless Claude Code* process (`claude -p`), reusing your
existing login. `llm_query` runs it with tools OFF (a plain LLM call); `rlm_query`
runs it WITH the rlm skill + bash ON (its own REPL), which is what makes recursion
"recursive". No Anthropic API key or SDK is involved.

Typical flow (driven by the root model via the `rlm` skill):
  python rlm_repl.py init path/to/context.txt        # load P, print metadata
  python rlm_repl.py status                           # inspect state
  python rlm_repl.py exec -c "print(peek(0, 2000))"   # probe
  python rlm_repl.py exec <<'PY'                       # decompose + sub-query
  lines = [ln for ln in content.splitlines() if ln.strip()]
  prompts = [build_prompt(batch) for batch in chunked(lines, 50)]
  outs = llm_query_map(prompts)        # parallel sub-LM calls
  ...aggregate into a variable...
  FINAL_VAR("answer")
  PY
  python rlm_repl.py final                             # print the final answer

State persists between invocations via a pickle file. Helpers and the context are
re-injected each `exec`; only your own (pickleable) variables are carried over.

Security note: `exec` runs arbitrary Python you wrote, and `llm_query`/`rlm_query`
spawn `claude -p` subprocesses. Treat it like running code you wrote.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_STATE_PATH = Path(".claude/rlm_state/state.pkl")
DEFAULT_AUDIT_ROOT = Path(".claude/rlm_runs")
DEFAULT_MAX_OUTPUT_CHARS = 8000

# Sub-LM defaults. Override per-call or via environment.
#   RLM_SUB_MODEL   : model alias for llm_query leaf calls (default: haiku -- cheap,
#                     200K-token window, strong at extraction/classification).
#   RLM_MAX_WORKERS : parallel sub-LM calls for llm_query_map (default: 8).
#   RLM_DEPTH       : current recursion depth (managed automatically; 0 at the root).
#   RLM_MAX_DEPTH   : max recursion depth for rlm_query (default: 1). At the limit,
#                     rlm_query degrades to a single llm_query call (paper behavior).
DEFAULT_SUB_MODEL = os.environ.get("RLM_SUB_MODEL", "haiku")
DEFAULT_MAX_WORKERS = int(os.environ.get("RLM_MAX_WORKERS", "8"))
DEFAULT_RLM_MODEL = os.environ.get("RLM_ROOT_MODEL", "sonnet")
RLM_CLAUDE_DISALLOWED_TOOLS = (
    "WebSearch WebFetch Monitor "
    "ScheduleWakeup Task AskUserQuestion "
    "CronCreate CronDelete CronList "
    "RemoteTrigger PushNotification Workflow "
    "TaskCreate TaskGet TaskList TaskOutput TaskStop TaskUpdate "
    "EnterPlanMode ExitPlanMode EnterWorktree ExitWorktree"
)

# A minimal system nudge so leaf outputs are clean and machine-parseable. The
# paper's llm_query is a plain call; this only trims preambles so that code which
# aggregates the outputs (e.g. parsing "N: label" lines) is not derailed by chatter.
DEFAULT_LEAF_SYSTEM = (
    "You are a sub-LLM invoked programmatically inside a larger system. "
    "Answer the query precisely using only the provided text. "
    "Output only the answer in the exact format requested, with no preamble, "
    "explanation, or markdown fences unless explicitly asked."
)


class RlmReplError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Sub-LM calls (the "recursion" in Recursive Language Models)                  #
# --------------------------------------------------------------------------- #
def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise RlmReplError(
            "`claude` CLI not found on PATH. llm_query/rlm_query need the Claude "
            "Code CLI to spawn the sub-LM."
        )
    return exe


# --- Leaf-usage accounting (opt-in; off by default) ------------------------- #
# Each llm_query shells out to its own `claude -p` subprocess, so its token/cost
# usage is NOT visible in the root session's usage JSON. For evaluation we need to
# account for it. When the environment variable RLM_LEAF_USAGE_LOG points at a
# file, llm_query adds `--output-format json` to the leaf call, returns the same
# `result` text the plain call would have produced (so callers are unaffected),
# and appends one JSON record of that leaf's usage to the log. When the variable
# is unset, llm_query runs EXACTLY as before (plain text, no JSON) -- so the skill
# the user actually gets is unchanged; this is purely measurement instrumentation.
_LEAF_USAGE_LOCK = threading.Lock()
_LEAF_TOKEN_KEYS = (
    "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
)


def _leaf_usage_log_path() -> Optional[str]:
    p = os.environ.get("RLM_LEAF_USAGE_LOG", "").strip()
    return p or None


def _record_leaf_usage(log_path: str, model: str, obj: Optional[Dict[str, Any]],
                       ok: bool, note: str = "") -> None:
    """Append one leaf-call usage record (thread-safe) to log_path as JSONL."""
    usage = (obj or {}).get("usage") if isinstance(obj, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    rec: Dict[str, Any] = {"ts": time.time(), "model": model, "ok": bool(ok)}
    total = 0
    for k in _LEAF_TOKEN_KEYS:
        v = usage.get(k, 0)
        v = int(v) if isinstance(v, (int, float)) else 0
        rec[k] = v
        total += v
    rec["total_tokens"] = total
    cost = (obj or {}).get("total_cost_usd") if isinstance(obj, dict) else None
    rec["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else 0.0
    if note:
        rec["note"] = note
    line = json.dumps(rec)
    try:
        with _LEAF_USAGE_LOCK:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # never let accounting break a run
        pass


def llm_query(
    prompt: str,
    model: Optional[str] = None,
    timeout: int = 300,
    system: Optional[str] = DEFAULT_LEAF_SYSTEM,
) -> str:
    """A single sub-LM call -- the leaf of the recursion.

    Runs a headless Claude Code (`claude -p`) with TOOLS OFF, so it behaves as a
    plain LLM forward pass: it reads the (bounded) `prompt` in its own context
    window and returns a string. The root is responsible for chunking the context
    down to something a leaf can hold; the leaf does the *semantic* work
    (classify / extract / summarize / answer) while the root's Python does the
    *arithmetic* (count / aggregate / format).

    Returns the sub-LM's text. On failure returns a "[llm_query: ...]" marker
    string rather than raising, so a large loop is not aborted by one bad call.

    Usage accounting: if RLM_LEAF_USAGE_LOG is set, the call is made with
    `--output-format json` and its usage/cost is appended to that log; the text
    returned is identical to the un-instrumented path.
    """
    model = model or DEFAULT_SUB_MODEL
    usage_log = _leaf_usage_log_path()
    cmd = [_claude_exe(), "-p", "--model", model, "--allowedTools", ""]
    if usage_log:
        cmd += ["--output-format", "json"]
    if system:
        cmd += ["--append-system-prompt", system]
    try:
        res = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        if usage_log:
            _record_leaf_usage(usage_log, model, None, ok=False, note=f"TIMEOUT/{timeout}s")
        return f"[llm_query: TIMEOUT after {timeout}s]"
    except Exception as e:  # pragma: no cover - environment dependent
        if usage_log:
            _record_leaf_usage(usage_log, model, None, ok=False, note=f"{type(e).__name__}")
        return f"[llm_query: ERROR {type(e).__name__}: {e}]"

    raw = (res.stdout or "").strip()
    if not usage_log:
        # Default path: byte-identical to the original (plain text, no JSON).
        if res.returncode != 0 and not raw:
            err = (res.stderr or "").strip()[:300]
            return f"[llm_query: ERROR rc={res.returncode}] {err}"
        return raw

    # Instrumented path: parse the JSON envelope, record usage, return result text.
    try:
        d = json.loads(raw)
    except Exception:
        _record_leaf_usage(usage_log, model, None, ok=False, note="jsonparse")
        if res.returncode != 0 and not raw:
            err = (res.stderr or "").strip()[:300]
            return f"[llm_query: ERROR rc={res.returncode}] {err}"
        return raw
    ok = not bool(d.get("is_error"))
    _record_leaf_usage(usage_log, model, d, ok=ok)
    out = (d.get("result") or "").strip()
    if not ok and not out:
        return f"[llm_query: ERROR is_error] {(d.get('result') or '')[:200]}"
    return out


def llm_query_map(
    prompts: List[str],
    model: Optional[str] = None,
    max_workers: Optional[int] = None,
    timeout: int = 300,
    system: Optional[str] = DEFAULT_LEAF_SYSTEM,
) -> List[str]:
    """Run many llm_query leaf calls in parallel; return outputs in input order.

    This is the workhorse for information-dense tasks: batch the context into N
    chunks, build one prompt per chunk, and fan them out. Prefer fewer, fatter
    batches (a leaf can hold a large chunk) over thousands of per-item calls.
    Results preserve the order of `prompts`.
    """
    model = model or DEFAULT_SUB_MODEL
    workers = max_workers or DEFAULT_MAX_WORKERS
    workers = max(1, min(workers, len(prompts) or 1))
    results: List[Optional[str]] = [None] * len(prompts)

    def _one(i_p: Tuple[int, str]) -> Tuple[int, str]:
        i, p = i_p
        return i, llm_query(p, model=model, timeout=timeout, system=system)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, out in ex.map(_one, list(enumerate(prompts))):
            results[i] = out
    return [r if r is not None else "" for r in results]


def rlm_query(
    context_text: str,
    query: str,
    model: Optional[str] = None,
    timeout: int = 1200,
    state_path: Optional[str] = None,
) -> str:
    """A full RECURSIVE RLM over a sub-context -- the depth>1 primitive.

    Use this when a sub-task is itself too large/complex for a single llm_query
    (e.g. "analyze these 500 documents that each need their own chunking"). It
    spawns a nested headless Claude Code WITH bash + the rlm skill, so the sub-task
    gets its own REPL, its own llm_query leaves, and its own iterative loop.

    Depth guard: a child RLM would run at depth+1. If that child depth is at or
    beyond RLM_MAX_DEPTH, degrade to a single llm_query call. max_depth=1 (the
    default) therefore means "llm_query leaves only"; max_depth=2 allows the
    root to spawn one nested RLM level, whose own recursive calls fall back to
    leaf llm_query calls.
    """
    depth = int(os.environ.get("RLM_DEPTH", "0"))
    max_depth = int(os.environ.get("RLM_MAX_DEPTH", "1"))
    child_depth = depth + 1
    if child_depth >= max_depth:
        return llm_query(
            f"{query}\n\n--- CONTEXT ---\n{context_text}",
            timeout=min(timeout, 300),
        )

    model = model or DEFAULT_RLM_MODEL
    run_id = f"d{child_depth}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
    sub_state = Path(state_path) if state_path else Path(f".claude/rlm_state/sub_{run_id}.pkl")
    sub_ctx = sub_state.with_suffix(".context.txt")
    sub_ctx.parent.mkdir(parents=True, exist_ok=True)
    sub_ctx.write_text(context_text, encoding="utf-8")

    repl = str(Path(__file__).resolve())
    prompt = textwrap.dedent(
        f"""\
        Use the rlm skill to answer a query over a large context file.

        The context is already on disk at: {sub_ctx}
        The rlm REPL script is at: {repl}
        Use this isolated REPL state file for every REPL command: {sub_state}

        Start with exactly:
        python "{repl}" --state "{sub_state}" init "{sub_ctx}"

        Initialise the REPL on that file and follow the rlm skill procedure
        (probe -> decompose -> programmatic llm_query over chunks -> aggregate),
        passing --state "{sub_state}" to every exec/final command. Then set the
        final answer with FINAL(...) or FINAL_VAR(...). Reply with ONLY the final
        answer text.

        query = {query!r}
        """
    )
    env = dict(os.environ)
    env["RLM_DEPTH"] = str(child_depth)
    cmd = [
        _claude_exe(), "-p", "--model", model,
        "--allowedTools", "Bash Read Write Edit Grep Glob Skill",
        "--disallowedTools", RLM_CLAUDE_DISALLOWED_TOOLS,
    ]
    try:
        res = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace", env=env,
        )
    except subprocess.TimeoutExpired:
        return f"[rlm_query: TIMEOUT after {timeout}s]"
    out = (res.stdout or "").strip()
    if res.returncode != 0 and not out:
        return f"[rlm_query: ERROR rc={res.returncode}] {(res.stderr or '')[:300]}"
    return out


# --------------------------------------------------------------------------- #
# State persistence                                                           #
# --------------------------------------------------------------------------- #
def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _timestamp_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"


def _json_write(path: Path, obj: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except Exception:
        pass


def _audit_runtime_source() -> Optional[Path]:
    p = Path(__file__).resolve().parent / "rlm_audit_runtime.py"
    return p if p.exists() else None


def _write_audit_readme(run_dir: Path) -> None:
    readme = textwrap.dedent(
        """\
        # RLM Audit Run

        This directory contains standalone Python scripts for the REPL code that
        was executed during one RLM session.

        - Run all saved steps from a clean replay checkpoint:
          `python replay_all.py`
        - Run one step directly:
          `python steps/step_0001.py`
        - Live replay calls `llm_query` / `llm_query_map` again, so LLM text may
          differ from the original run.
        - Replay state is written to `replay_state.pkl`; the original live REPL
          state is not modified.
        """
    )
    (run_dir / "README.md").write_text(readme, encoding="utf-8")


def _write_replay_all(run_dir: Path) -> None:
    body = textwrap.dedent(
        """\
        #!/usr/bin/env python3
        from __future__ import annotations

        import subprocess
        import sys
        from pathlib import Path


        def main(argv):
            run_dir = Path(__file__).resolve().parent
            resume = "--resume" in argv
            state = run_dir / "replay_state.pkl"
            if state.exists() and not resume:
                state.unlink()
            steps = sorted((run_dir / "steps").glob("step_*.py"))
            if not steps:
                print("No replay steps found.", file=sys.stderr)
                return 1
            for step in steps:
                print(f"=== {step.name} ===", flush=True)
                res = subprocess.run([sys.executable, str(step)])
                if res.returncode != 0:
                    return res.returncode
            return 0


        if __name__ == "__main__":
            raise SystemExit(main(sys.argv[1:]))
        """
    )
    p = run_dir / "replay_all.py"
    p.write_text(body, encoding="utf-8")
    _make_executable(p)


def _create_audit_run(ctx_path: Path, content: str, audit_dir: str,
                      run_id: Optional[str]) -> Dict[str, Any]:
    root = Path(audit_dir)
    rid = run_id or _timestamp_run_id()
    run_dir = root / rid
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = root / f"{rid}_{suffix}"
    steps_dir = run_dir / "steps"
    runtime_dir = run_dir / "runtime"
    steps_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(Path(__file__).resolve(), runtime_dir / "rlm_repl.py")
    runtime_src = _audit_runtime_source()
    if runtime_src:
        shutil.copyfile(runtime_src, runtime_dir / "rlm_audit_runtime.py")

    ctx_abs = ctx_path.resolve() if ctx_path.exists() else (Path.cwd() / ctx_path).resolve()
    manifest: Dict[str, Any] = {
        "run_id": run_dir.name,
        "created_by": "rlm_repl.py",
        "initialized_at": time.time(),
        "cwd": str(Path.cwd()),
        "context_path": str(ctx_path),
        "context_abs_path": str(ctx_abs),
        "context_sha256": _sha256_text(content),
        "context_size_chars": len(content),
        "state_path": str(DEFAULT_STATE_PATH),
        "steps": [],
        "live_replay_note": (
            "Generated step scripts call llm_query live; LLM outputs are not "
            "expected to be byte-for-byte reproducible."
        ),
    }
    if ctx_abs.exists():
        try:
            manifest["context_file_sha256"] = _sha256_file(ctx_abs)
        except Exception:
            pass
    _json_write(run_dir / "manifest.json", manifest)
    _write_replay_all(run_dir)
    _write_audit_readme(run_dir)
    return {
        "enabled": True,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "next_step": 1,
    }


def _render_step_script(code: str, step_index: int) -> str:
    body = textwrap.indent(code.rstrip() or "pass", "    ")
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        # Auto-generated RLM audit replay step {step_index:04d}.

        import sys
        from pathlib import Path

        _rlm_run_dir = Path(__file__).resolve().parents[1]
        _rlm_runtime_dir = _rlm_run_dir / "runtime"
        sys.path.insert(0, str(_rlm_runtime_dir))

        from rlm_audit_runtime import load_env, save_env

        globals().update(load_env(_rlm_run_dir, step_index={step_index}))
        try:
        {body}
        finally:
            save_env(_rlm_run_dir, step_index={step_index}, namespace=globals())
        """
    )


def _audit_record_exec(state: Dict[str, Any], state_path: Path, code: str,
                       stdout_text: str, stderr_text: str,
                       dropped: List[str]) -> Optional[Path]:
    audit = state.get("audit")
    if not isinstance(audit, dict) or not audit.get("enabled"):
        return None
    run_dir = Path(str(audit.get("run_dir", "")))
    if not run_dir:
        return None
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    step_index = int(audit.get("next_step", 1))
    stem = f"step_{step_index:04d}"
    step_path = steps_dir / f"{stem}.py"
    stdout_path = steps_dir / f"{stem}.stdout.txt"
    stderr_path = steps_dir / f"{stem}.stderr.txt"
    meta_path = steps_dir / f"{stem}.json"

    step_path.write_text(_render_step_script(code, step_index), encoding="utf-8")
    _make_executable(step_path)
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    final = state.get("final", {})
    final_value = final.get("value") if isinstance(final, dict) else None
    meta: Dict[str, Any] = {
        "step": step_index,
        "created_at": time.time(),
        "code_sha256": _sha256_text(code),
        "script": str(step_path.relative_to(run_dir)),
        "stdout": str(stdout_path.relative_to(run_dir)),
        "stderr": str(stderr_path.relative_to(run_dir)),
        "stdout_chars": len(stdout_text),
        "stderr_chars": len(stderr_text),
        "dropped_unpickleable": dropped,
        "state_path": str(state_path),
        "final_set": isinstance(final, dict) and "value" in final,
    }
    if final_value is not None:
        meta["final_sha256"] = _sha256_text(str(final_value))
        meta["final_chars"] = len(str(final_value))
    _json_write(meta_path, meta)

    manifest_path = run_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest, dict):
            manifest.setdefault("steps", []).append(meta)
            manifest["updated_at"] = time.time()
            _json_write(manifest_path, manifest)
    except Exception:
        pass

    audit["next_step"] = step_index + 1
    state["audit"] = audit
    return step_path


def _load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        raise RlmReplError(
            f"No state found at {state_path}. Run: python rlm_repl.py init <context_path>"
        )
    with state_path.open("rb") as f:
        state = pickle.load(f)
    if not isinstance(state, dict):
        raise RlmReplError(f"Corrupt state file: {state_path}")
    return state


def _save_state(state: Dict[str, Any], state_path: Path) -> None:
    _ensure_parent_dir(state_path)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with tmp_path.open("wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(state_path)


def _read_text_file(path: Path, max_bytes: Optional[int] = None) -> str:
    if not path.exists():
        raise RlmReplError(f"Context file does not exist: {path}")
    with path.open("rb") as f:
        data = f.read() if max_bytes is None else f.read(max_bytes)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _truncate(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    head = s[:max_chars]
    return head + f"\n... [stdout truncated: {len(s):,} chars total, showing {max_chars:,}] ...\n"


def _is_pickleable(value: Any) -> bool:
    try:
        pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return True
    except Exception:
        return False


def _filter_pickleable(d: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    kept: Dict[str, Any] = {}
    dropped: List[str] = []
    for k, v in d.items():
        if _is_pickleable(v):
            kept[k] = v
        else:
            dropped.append(k)
    return kept, dropped


# --------------------------------------------------------------------------- #
# Context-manipulation helpers (closures over the live content string)        #
# --------------------------------------------------------------------------- #
def _make_helpers(state: Dict[str, Any], buffers_ref: List[str], final_ref: Dict[str, Any]):
    def _content() -> str:
        return state.get("content", "")

    def peek(start: int = 0, end: int = 1000) -> str:
        """Return content[start:end] -- a window into the raw context."""
        return _content()[start:end]

    def grep(pattern: str, max_matches: int = 20, window: int = 120, flags: int = 0):
        """Regex-search the context; return [{match, span, snippet}] with context windows."""
        content = _content()
        out: List[Dict[str, Any]] = []
        for m in re.finditer(pattern, content, flags):
            s, e = m.span()
            out.append({
                "match": m.group(0),
                "span": (s, e),
                "snippet": content[max(0, s - window): min(len(content), e + window)],
            })
            if len(out) >= max_matches:
                break
        return out

    def chunked(seq, size: int):
        """Yield successive `size`-length slices of any sequence (list of lines, etc.)."""
        if size <= 0:
            raise ValueError("size must be > 0")
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    def chunk_indices(size: int = 200_000, overlap: int = 0) -> List[Tuple[int, int]]:
        """Character (start, end) spans tiling the context, with optional overlap."""
        if size <= 0:
            raise ValueError("size must be > 0")
        if not (0 <= overlap < size):
            raise ValueError("overlap must satisfy 0 <= overlap < size")
        content = _content()
        n = len(content)
        spans: List[Tuple[int, int]] = []
        step = size - overlap
        for start in range(0, n, step):
            end = min(n, start + size)
            spans.append((start, end))
            if end >= n:
                break
        return spans

    def write_chunks(out_dir, size: int = 200_000, overlap: int = 0,
                     prefix: str = "chunk", encoding: str = "utf-8") -> List[str]:
        """Materialise character chunks as files (useful for rlm_query/inspection)."""
        content = _content()
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        paths: List[str] = []
        for i, (s, e) in enumerate(chunk_indices(size=size, overlap=overlap)):
            p = out_path / f"{prefix}_{i:04d}.txt"
            p.write_text(content[s:e], encoding=encoding)
            paths.append(str(p))
        return paths

    def add_buffer(text: str) -> None:
        """Append a string to the persistent `buffers` list (intermediate results)."""
        buffers_ref.append(str(text))

    def FINAL(answer: Any) -> None:
        """Set the final answer directly. Stops the loop; this value is returned."""
        final_ref["value"] = "" if answer is None else str(answer)

    def FINAL_VAR(name: str) -> None:
        """Set the final answer from a REPL variable you created (by name)."""
        frame = sys._getframe(1)
        if name in frame.f_locals:
            val = frame.f_locals[name]
        elif name in frame.f_globals:
            val = frame.f_globals[name]
        else:
            raise NameError(f"FINAL_VAR: variable {name!r} is not defined in the REPL")
        final_ref["value"] = "" if val is None else str(val)

    return {
        "peek": peek,
        "grep": grep,
        "chunked": chunked,
        "chunk_indices": chunk_indices,
        "write_chunks": write_chunks,
        "add_buffer": add_buffer,
        "llm_query": llm_query,
        "llm_query_map": llm_query_map,
        "rlm_query": rlm_query,
        "FINAL": FINAL,
        "FINAL_VAR": FINAL_VAR,
    }


# --------------------------------------------------------------------------- #
# Metadata (the constant-size view the root model gets of the context)        #
# --------------------------------------------------------------------------- #
def _metadata_str(state: Dict[str, Any]) -> str:
    content = state.get("content", "")
    n = len(content)
    lines = content.count("\n") + 1 if content else 0
    prefix = content[:600].replace("\r", "")
    final_set = "value" in state.get("final", {}) if isinstance(state.get("final"), dict) else bool(state.get("final"))
    return textwrap.dedent(
        f"""\
        RLM REPL initialised.
          context : str  ({n:,} chars, ~{lines:,} lines, ~{n // 4:,} tokens est.)
          source  : {state.get('context_path')}
          buffers : {len(state.get('buffers', []))}
          final   : {'SET' if final_set else 'not set'}

        The full context is the `context` variable in the REPL (also aliased `content`).
        You can see only metadata + truncated stdout -- never the whole context. Use
        llm_query / llm_query_map to do semantic work over chunks of it.

        --- first {len(prefix)} chars of context ---
        {prefix}
        --- end preview ---"""
    )


# --------------------------------------------------------------------------- #
# Commands                                                                    #
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    ctx_path = Path(args.context)
    content = _read_text_file(ctx_path, max_bytes=args.max_bytes)
    audit = (
        {"enabled": False}
        if args.no_audit
        else _create_audit_run(ctx_path, content, args.audit_dir, args.audit_run_id)
    )
    if audit.get("enabled"):
        manifest_path = Path(str(audit["run_dir"])) / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state_path"] = str(state_path)
            _json_write(manifest_path, manifest)
        except Exception:
            pass
    state: Dict[str, Any] = {
        "version": 3,
        "context_path": str(ctx_path),
        "loaded_at": time.time(),
        "content": content,
        "buffers": [],
        "final": {},
        "globals": {},
        "audit": audit,
    }
    _save_state(state, state_path)
    print(_metadata_str(state))
    if audit.get("enabled"):
        print(f"\nAudit replay package: {audit['run_dir']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.state))
    print(_metadata_str(state))
    g = state.get("globals", {})
    if g:
        print(f"\n  persisted vars ({len(g)}): " + ", ".join(sorted(g.keys())))
    return 0


def cmd_final(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.state))
    final = state.get("final", {})
    if isinstance(final, dict) and "value" in final:
        print(final["value"])
        return 0
    sys.stderr.write("No final answer set yet (use FINAL(...) or FINAL_VAR(...) in exec).\n")
    return 1


def cmd_reset(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    if state_path.exists():
        state_path.unlink()
        print(f"Deleted state: {state_path}")
    else:
        print(f"No state to delete at: {state_path}")
    return 0


def cmd_export_buffers(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.state))
    buffers = state.get("buffers", [])
    out_path = Path(args.out)
    _ensure_parent_dir(out_path)
    out_path.write_text("\n\n".join(str(b) for b in buffers), encoding="utf-8")
    print(f"Wrote {len(buffers)} buffers to: {out_path}")
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = _load_state(state_path)
    if "content" not in state:
        raise RlmReplError("State is missing 'content'. Re-run init.")

    buffers = state.setdefault("buffers", [])
    if not isinstance(buffers, list):
        buffers = []
        state["buffers"] = buffers
    final_ref: Dict[str, Any] = state.setdefault("final", {})
    if not isinstance(final_ref, dict):
        final_ref = {}
        state["final"] = final_ref
    persisted = state.setdefault("globals", {})
    if not isinstance(persisted, dict):
        persisted = {}
        state["globals"] = persisted

    code = args.code if args.code is not None else sys.stdin.read()

    # Build the execution environment: persisted user vars, then the live context
    # and helpers. `context` and `content` both point at the loaded string.
    env: Dict[str, Any] = dict(persisted)
    env["context"] = state["content"]
    env["content"] = state["content"]
    env["buffers"] = buffers
    helpers = _make_helpers(state, buffers, final_ref)
    env.update(helpers)

    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, env, env)
    except Exception:
        traceback.print_exc(file=stderr_buf)

    # Pull back mutated buffers.
    if isinstance(env.get("buffers"), list):
        state["buffers"] = env["buffers"]

    # Persist user variables (exclude injected names and the big context aliases).
    injected = {"__builtins__", "context", "content", "buffers", *helpers.keys()}
    to_persist = {k: v for k, v in env.items() if k not in injected}
    filtered, dropped = _filter_pickleable(to_persist)
    state["globals"] = filtered

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    step_path = None
    if not getattr(args, "no_audit", False):
        try:
            step_path = _audit_record_exec(state, state_path, code, out, err, dropped)
        except Exception:
            traceback.print_exc(file=stderr_buf)
            err = stderr_buf.getvalue()
    _save_state(state, state_path)

    if "value" in final_ref:
        out += (f"\n=== FINAL ANSWER SET ({len(final_ref['value']):,} chars) ===\n"
                + _truncate(final_ref["value"], args.max_output_chars))
    if step_path is not None:
        out += f"\n=== AUDIT STEP SAVED: {step_path} ===\n"
    if dropped and args.warn_unpickleable:
        err += ("\n" if err else "") + "Dropped unpickleable variables: " + ", ".join(dropped) + "\n"
    if out:
        sys.stdout.write(_truncate(out, args.max_output_chars))
    if err:
        sys.stderr.write(_truncate(err, args.max_output_chars))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rlm_repl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            Persistent REPL for Recursive Language Model (RLM) workflows.

            Examples:
              python rlm_repl.py init context.txt
              python rlm_repl.py status
              python rlm_repl.py exec -c "print(peek(0, 2000))"
              python rlm_repl.py exec <<'PY'
              labels = llm_query_map([build(b) for b in chunked(lines, 50)])
              FINAL_VAR("answer")
              PY
              python rlm_repl.py final
            """
        ),
    )
    p.add_argument("--state", default=str(DEFAULT_STATE_PATH),
                   help=f"Path to state pickle (default: {DEFAULT_STATE_PATH})")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Load a context file and print metadata")
    p_init.add_argument("context", help="Path to the context file")
    p_init.add_argument("--max-bytes", type=int, default=None,
                        help="Optional cap on bytes read from the context file")
    p_init.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_ROOT),
                        help=f"Directory for standalone replay packages (default: {DEFAULT_AUDIT_ROOT})")
    p_init.add_argument("--audit-run-id", default=None,
                        help="Optional audit run directory name")
    p_init.add_argument("--no-audit", action="store_true",
                        help="Do not create standalone replay scripts for this REPL state")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Show metadata + persisted var names")
    p_status.set_defaults(func=cmd_status)

    p_final = sub.add_parser("final", help="Print the stored final answer (if set)")
    p_final.set_defaults(func=cmd_final)

    p_reset = sub.add_parser("reset", help="Delete the current state file")
    p_reset.set_defaults(func=cmd_reset)

    p_export = sub.add_parser("export-buffers", help="Export buffers list to a text file")
    p_export.add_argument("out", help="Output file path")
    p_export.set_defaults(func=cmd_export_buffers)

    p_exec = sub.add_parser("exec", help="Execute Python with persisted state + helpers")
    p_exec.add_argument("-c", "--code", default=None,
                        help="Inline code. If omitted, reads code from stdin.")
    p_exec.add_argument("--max-output-chars", type=int, default=DEFAULT_MAX_OUTPUT_CHARS,
                        help=f"Truncate stdout/stderr to N chars (default: {DEFAULT_MAX_OUTPUT_CHARS})")
    p_exec.add_argument("--warn-unpickleable", action="store_true",
                        help="Warn on stderr when variables could not be persisted")
    p_exec.add_argument("--no-audit", action="store_true",
                        help="Execute without writing a standalone audit step")
    p_exec.set_defaults(func=cmd_exec)
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RlmReplError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
