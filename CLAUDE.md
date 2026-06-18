# Project instructions

## Headless Codex sub-agent

This repo exposes a root-level headless Codex command for agents that need a
non-interactive Codex pass:

```bash
./codex-headless "review the current repo and list the highest-risk files"
```

On Windows shells, use either:

```powershell
.\codex-headless.ps1 "review the current repo and list the highest-risk files"
.\codex-headless.cmd "review the current repo and list the highest-risk files"
```

The wrapper runs `codex exec` from the repo root with `gpt-5.5`,
`model_reasoning_effort="xhigh"`, `--sandbox workspace-write`,
`approval_policy="never"`, and `--ephemeral`. It preserves normal
`codex exec` behavior, so callers can pass a prompt argument, pipe stdin, add
flags such as `--json`, or use `-o <file>` for the final message. It requires
the Codex CLI on `PATH` and an existing `codex login` or `CODEX_API_KEY` scoped
to the invocation.

## RLM mode for long-context tasks

This repository includes a faithful "Recursive Language Model" (RLM) setup for
Claude Code (after *Recursive Language Models*, arXiv:2512.24601, Algorithm 1):
- Skill: `rlm` in `.claude/skills/rlm/`
- Persistent Python REPL: `.claude/skills/rlm/scripts/rlm_repl.py` — holds the
  large context as a variable and exposes `llm_query` / `llm_query_map` /
  `rlm_query` and `FINAL` / `FINAL_VAR`.
- Sub-LM (`llm_query`): a nested headless Claude Code (`claude -p`, tools off,
  default model `haiku`), called *programmatically from REPL code* — not a Task
  subagent. The recursive `rlm_query` runs `claude -p` with bash + this skill on.

When the user needs you to work over a context that is too large to paste into chat:
1) Ask for (or locate) a context file path.
2) Run the `/rlm` Skill and follow its procedure.

Keep the main conversation light: the root model never reads the full context —
it writes REPL code that sub-queries the context in chunks, then synthesises.
Use `python` (not `python3`) to invoke the REPL on this machine.

## OOLONG eval — where run artifacts go

The RLM-vs-agent OOLONG eval (issue #6) is driven by
`rlm_vs_agent_experiment/run_rlm_skill_eval.py`. **Every run writes only under a
timestamped folder — `rlm_vs_agent_experiment/runs/<YYYYMMDD_HHMMSS>/<arm>/` — never
loose in the experiment folder.** Pass the same `--run-id` to every arm so one
experiment groups together:

```bash
TS=$(date +%Y%m%d_%H%M%S)
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode agent --root opus
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode agent --root haiku
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode rlm   --root opus
python rlm_vs_agent_experiment/score.py --predictions rlm_vs_agent_experiment/runs/$TS/rlm_skill_opus/preds_rlm_skill.jsonl
```

`runs/` is gitignored — run folders are local scratch; the committed deliverable is
`rlm_vs_agent_experiment/REPORT.md`. This keeps the repo clean so we never accumulate
stray eval files that must later be archived. (To keep a specific run as committed
provenance, `git add -f` that one run folder.)

This is a **driver convention only — the `/rlm` skill is unchanged**. The skill's own
on-disk state is the transient `.claude/rlm_state/` REPL pickle (gitignored, and wiped
per task by the driver); it never writes into the experiment folder.

## Running the OOLONG RLM-vs-agent experiment

**GitHub issue #6 (pinned) is the source of truth** for this experiment — its design,
the three arms, the exact commands, and the "done when" criteria. Treat the issue as
the external instruction surface: fetch it at run time with `gh issue view 6` and
follow it, rather than relying on memory.

When someone asks to run the experiment:
1. **First ask whether they want the full run.** The full experiment is all three arms
   × 10 samples and is costly (~$90 and a few hours, dominated by the Opus agent arm).
   Offer the cheap alternative — a single-task smoke test (`--ids <one id>` per arm) —
   and only launch the full run once they confirm.
2. **Then run it exactly as issue #6 instructs** — all arms into one timestamped
   `runs/<ts>/` folder (shared `--run-id`), then score with `score.py` and fold the
   numbers into `REPORT.md`.
