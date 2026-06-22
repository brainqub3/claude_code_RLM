#!/usr/bin/env python3
"""Runtime used by generated RLM audit step scripts.

The scripts in an audit run are normal Python files, but they need the same
globals that `rlm_repl.py exec` injected at execution time: `content`, `grep`,
`llm_query`, `FINAL`, persisted variables from earlier steps, and so on. This
module recreates that environment and persists replay state between step files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import rlm_repl


_ACTIVE: Dict[str, Any] = {}


def _load_manifest(run_dir: Path) -> Dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Invalid manifest: {manifest_path}")
    return manifest


def _resolve_context_path(manifest: Dict[str, Any]) -> Path:
    candidates = []
    abs_path = manifest.get("context_abs_path")
    if abs_path:
        candidates.append(Path(abs_path))

    ctx = manifest.get("context_path")
    cwd = manifest.get("cwd")
    if ctx:
        p = Path(ctx)
        candidates.append(p)
        if cwd and not p.is_absolute():
            candidates.append(Path(cwd) / p)

    for p in candidates:
        if p.exists():
            return p
    tried = ", ".join(str(p) for p in candidates) or "<none>"
    raise RuntimeError(f"Could not locate replay context file; tried: {tried}")


def _initial_state(manifest: Dict[str, Any]) -> Dict[str, Any]:
    context_path = _resolve_context_path(manifest)
    content = rlm_repl._read_text_file(context_path)
    return {
        "version": 2,
        "context_path": str(context_path),
        "loaded_at": manifest.get("initialized_at"),
        "content": content,
        "buffers": [],
        "final": {},
        "globals": {},
    }


def load_env(run_dir: str | Path, step_index: int) -> Dict[str, Any]:
    """Return the globals expected by one generated audit step."""
    run_dir = Path(run_dir).resolve()
    manifest = _load_manifest(run_dir)

    cwd = manifest.get("cwd")
    if cwd and Path(cwd).exists():
        os.chdir(cwd)

    state_path = run_dir / "replay_state.pkl"
    if state_path.exists():
        state = rlm_repl._load_state(state_path)
    else:
        if step_index != 1:
            raise RuntimeError(
                "Replay state is missing. Run prior steps first, or use replay_all.py."
            )
        state = _initial_state(manifest)

    buffers = state.setdefault("buffers", [])
    if not isinstance(buffers, list):
        buffers = []
        state["buffers"] = buffers
    final_ref = state.setdefault("final", {})
    if not isinstance(final_ref, dict):
        final_ref = {}
        state["final"] = final_ref
    persisted = state.setdefault("globals", {})
    if not isinstance(persisted, dict):
        persisted = {}
        state["globals"] = persisted

    env: Dict[str, Any] = dict(persisted)
    env["context"] = state["content"]
    env["content"] = state["content"]
    env["buffers"] = buffers
    helpers = rlm_repl._make_helpers(state, buffers, final_ref)
    env.update(helpers)

    _ACTIVE.clear()
    _ACTIVE.update({
        "run_dir": run_dir,
        "state_path": state_path,
        "state": state,
        "helpers": helpers,
        "step_index": step_index,
    })
    return env


def save_env(run_dir: str | Path, step_index: int, namespace: Dict[str, Any]) -> None:
    """Persist variables mutated by a generated audit step."""
    run_dir = Path(run_dir).resolve()
    if not _ACTIVE or _ACTIVE.get("run_dir") != run_dir:
        raise RuntimeError("No active replay environment. Call load_env() first.")
    if _ACTIVE.get("step_index") != step_index:
        raise RuntimeError("Replay step mismatch while saving state.")

    state = _ACTIVE["state"]
    helpers = _ACTIVE["helpers"]

    if isinstance(namespace.get("buffers"), list):
        state["buffers"] = namespace["buffers"]

    injected = {
        "__builtins__",
        "context",
        "content",
        "buffers",
        "Path",
        "sys",
        "load_env",
        "save_env",
        *helpers.keys(),
    }
    to_persist = {
        k: v
        for k, v in namespace.items()
        if k not in injected and not k.startswith("_rlm_")
    }
    filtered, _dropped = rlm_repl._filter_pickleable(to_persist)
    state["globals"] = filtered
    rlm_repl._save_state(state, _ACTIVE["state_path"])
