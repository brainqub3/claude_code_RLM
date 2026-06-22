# Claude Code RLM

A minimal implementation of Recursive Language Models (RLM) using Claude Code as the scaffold. Implemented by [Brainqub3](https://brainqub3.com/).

## About

This repository provides a basic RLM setup that enables Claude to process documents and contexts that exceed typical context window limits. It implements the core RLM pattern where a root language model orchestrates sub-LLM calls over chunks of a large document.

**This is a basic implementation** of the RLM paper. For the full research, see:

> **Recursive Language Models**
> Alex L. Zhang, Tim Kraska, Omar Khattab
> MIT CSAIL
> [arXiv:2512.24601](https://arxiv.org/abs/2512.24601)

*Abstract: RLMs treat long prompts as part of an external environment and allow the LLM to programmatically examine, decompose, and recursively call itself over snippets of the prompt. RLMs can handle inputs up to two orders of magnitude beyond model context windows.*

## Architecture

This implementation follows the paper's Algorithm 1 and maps it onto Claude Code's
primitives as follows:

| RLM Concept | Implementation | Model |
|-------------|----------------|-------|
| Root LLM | Main Claude Code conversation (never reads the full context) | your session model (e.g. **Opus**) |
| External environment | Persistent Python REPL (`rlm_repl.py`) holding the context as a variable | Python |
| Sub-LM `llm_query` (leaf) | Nested headless Claude Code (`claude -p`, **tools off**), called programmatically from REPL code | **Haiku** (default) |
| Recursive `rlm_query` (depth>1) | Nested headless Claude Code with **bash + this skill on** (its own REPL) | configurable |

The key fidelity point from the paper: the root model **does not read the context
into its window**. It only sees metadata and truncated `stdout`, and answers by
writing REPL code that **programmatically** sub-queries the context in chunks
(`llm_query` / `llm_query_map`), aggregates with plain Python, and returns the
answer via `FINAL(...)` / `FINAL_VAR(...)`. The sub-LM is a nested `claude -p`
process that reuses your existing login — no Anthropic API key or SDK. The split
that makes it work: the **LLM does the semantics** (classify/extract/summarise) and
**Python does the arithmetic** (count/aggregate/format).

## Prerequisites

- **Claude Code recommended** - This skill currently works best when run from
  Claude Code. The RLM REPL is not yet implemented for direct Codex use because
  the current harness launches a headless Claude Code instance for sub-LM calls.
- **Claude Code account** - You need access to [Claude Code](https://claude.ai/claude-code), Anthropic's official CLI tool
- **Python 3** - For the persistent REPL environment

## Usage

### Headless Codex helper

This repo includes a root-level helper that lets Claude Code, another Codex
session, or any other CLI agent call non-interactive Codex from the repository
root:

```bash
./codex-headless "summarize this repo and identify the next implementation step"
```

On Windows:

```powershell
.\codex-headless.ps1 "summarize this repo and identify the next implementation step"
.\codex-headless.cmd "summarize this repo and identify the next implementation step"
```

The helper runs `codex exec` with `gpt-5.5`, extra-high reasoning
(`model_reasoning_effort="xhigh"`), `workspace-write` sandboxing,
`approval_policy=never`, and ephemeral session storage. It also accepts normal
`codex exec` flags, for example:

```bash
./codex-headless --json "inspect the git diff and return a risk summary"
```

1. **Clone this repository**
   ```bash
   git clone https://github.com/Brainqub3/claude_code_RLM.git
   cd claude_code_RLM
   ```

2. **Start Claude Code in the repository directory**
   ```bash
   claude
   ```

3. **Run the RLM skill**
   ```
   /rlm
   ```

4. **Follow the prompts** - The skill will ask for:
   - A path to your large context file
   - Your query/question about the content

The RLM workflow will then:
- Initialize the REPL with your context (loaded as a variable, not into chat)
- Probe the format and choose a chunking strategy
- Write REPL code that programmatically sub-queries the context in chunks via `llm_query`
- Aggregate with plain Python and return the answer via `FINAL` / `FINAL_VAR`
- Save each REPL `exec` block as a standalone Python replay step under
  `.claude/rlm_runs/<run_id>/`

### Standalone audit replay

By default, `rlm_repl.py init` creates an audit replay package:

```text
.claude/rlm_runs/<run_id>/
|-- manifest.json
|-- replay_all.py
|-- runtime/
`-- steps/
    |-- step_0001.py
    |-- step_0001.json
    |-- step_0001.stdout.txt
    `-- step_0001.stderr.txt
```

Run all saved steps from a clean replay checkpoint:

```bash
python .claude/rlm_runs/<run_id>/replay_all.py
```

The generated scripts recreate the REPL globals (`content`, `grep`,
`llm_query_map`, `FINAL_VAR`, persisted variables, etc.) and write replay state to
`replay_state.pkl`, separate from the live `.claude/rlm_state/state.pkl`. They call
`llm_query` live, so LLM outputs are not guaranteed to match the original run.

Useful knobs:

```bash
python .claude/skills/rlm/scripts/rlm_repl.py init context.txt --audit-run-id my_run
python .claude/skills/rlm/scripts/rlm_repl.py init context.txt --audit-dir audit_runs
python .claude/skills/rlm/scripts/rlm_repl.py init context.txt --no-audit
```

## Working with Long Files

When using RLM to process large context files, it is recommended to save them in a dedicated `context/` folder within this project directory. This keeps your working files organized and separate from the RLM implementation code.

```bash
mkdir context
# Place your large documents here, e.g.:
# context/my_large_document.txt
# context/codebase_dump.py
```

## Security Warning

**This project is not intended for production use.**

If you plan to run Claude Code in `--dangerously-skip-permissions` mode:

1. **Ensure your setup is correct** - Verify all file paths and configurations before enabling this mode
2. **Run in an isolated folder** - Never run with skipped permissions in directories containing sensitive data, credentials, or system files
3. **Understand the risks** - This mode allows Claude to execute commands without confirmation prompts, which can lead to unintended file modifications or deletions

**Recommended**: Create a dedicated, isolated working directory specifically for RLM tasks when using dangerous mode:

```bash
# Example: Create an isolated workspace
mkdir ~/rlm-workspace
cd ~/rlm-workspace
git clone https://github.com/Brainqub3/claude_code_RLM.git
cd claude_code_RLM
```

## Repository Structure

```
.
├── CLAUDE.md                          # Project instructions for Claude Code
├── .claude/
│   └── skills/
│       └── rlm/
│           ├── SKILL.md              # RLM skill definition (the root's procedure)
│           ├── scripts/
│           │   └── rlm_repl.py       # Persistent Python REPL + llm_query/rlm_query
│           └── eval/                 # OOLONG long-context eval (score vs. the paper)
├── context/                           # Recommended location for large context files
└── README.md
```

> Note: earlier versions used a `.claude/agents/rlm-subcall.md` Task subagent as the
> sub-LM. The faithful implementation calls the sub-LM *programmatically from REPL
> code* (`claude -p`), so that subagent is no longer used.

## License

See [LICENSE](LICENSE) for details.
