#!/usr/bin/env python3
"""Reconstruct the actual orchestration trajectory an RLM root took, from the
stream-json transcript captured by run_rlm_skill_eval.py.

Usage:
  python _runs_extract_path.py rlm_skill_opus/_runs/task_17000206.stream.jsonl
  python _runs_extract_path.py <file> --full     # don't truncate commands/results
"""
import argparse
import json
import sys


def short(s, n):
    s = s or ""
    s = s.replace("\r", "")
    return s if len(s) <= n else s[:n] + f"\n      ...[+{len(s)-n} chars]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--cmd-chars", type=int, default=100000)
    ap.add_argument("--text-chars", type=int, default=600)
    ap.add_argument("--result-chars", type=int, default=400)
    args = ap.parse_args()

    # tool_use id -> (name, command) so we can attach the matching tool_result
    pending = {}
    step = 0
    for line in open(args.file, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if t == "assistant":
            for b in (d.get("message") or {}).get("content", []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    print(f"\n>> ROOT: {short(b['text'].strip(), args.text_chars)}")
                elif b.get("type") == "tool_use":
                    step += 1
                    name = b.get("name")
                    inp = b.get("input") or {}
                    pending[b.get("id")] = name
                    if name == "Bash":
                        cmd = inp.get("command", "")
                        print(f"\n[{step}] TOOL Bash:\n{short(cmd, args.cmd_chars)}")
                    elif name == "Skill":
                        print(f"\n[{step}] SKILL Skill: {inp.get('command') or inp.get('name') or inp}")
                    else:
                        print(f"\n[{step}] TOOL {name}: {short(json.dumps(inp), 300)}")
        elif t == "user":
            # tool_result(s)
            for b in (d.get("message") or {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    print(f"    -> stdout: {short(str(c), args.result_chars)}")
        elif t == "result":
            print(f"\n=== FINAL REPLY ({d.get('num_turns')} turns) ===")
            print(short(d.get("result") or "", 500))


if __name__ == "__main__":
    main()
