---
name: rlm
description: >-
  Recursive Language Model (RLM) loop for processing a context that is too large
  to read into the conversation directly. Loads the context as a variable in a
  persistent Python REPL and answers the query by writing code that probes,
  chunks, and programmatically sub-queries a cheap LLM (`llm_query`) over slices
  of it, then aggregates. Use this WHENEVER the user points you at a big context
  file/log/transcript/codebase/scraped corpus (anything from ~50K chars up to
  millions) and asks a question that needs most of the content -- counting,
  aggregating, classifying every item, multi-hop lookup, or summarising the whole
  thing -- ESPECIALLY when the answer "depends on almost every line" and a single
  retrieval/grep won't do. Trigger it even if the user doesn't say "RLM": phrases
  like "this file is huge", "go through the whole log", "how many X across all of
  these", "label every row", or "it won't fit in context" are all signals to use
  this skill. Prefer it over dumping the file into chat.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
---

# rlm — Recursive Language Model loop

A faithful instantiation of *Recursive Language Models* (Zhang, Kraska, Khattab;
arXiv:2512.24601), Algorithm 1, on Claude Code's primitives. The paper's insight:
**an arbitrarily long prompt should not be fed into a model's context window at
all. It should live in an environment the model interacts with *programmatically*,
recursively calling a model over slices of it.** That's what this skill does.

## Mental model

You (the main Claude Code conversation) are the **root model**. You do **not** read
the big context into this conversation. Instead:

- The context lives as a `context` variable inside a **persistent Python REPL**
  (`scripts/rlm_repl.py`). You only ever see *metadata* about it (length, a short
  prefix) and the *truncated stdout* of code you run — never the whole thing. This
  is the one rule that lets the context be far larger than any window.
- You answer by **writing REPL code** that probes the context, decomposes it, and
  calls a cheap **sub-LM** over the pieces:
  - `llm_query(prompt)` / `llm_query_map(prompts)` — a single / a parallel batch of
    plain sub-LM calls (a nested headless `claude -p`, tools off). This is the
    **leaf**: it reads a *bounded chunk* in its own window and returns text.
  - `rlm_query(context, query)` — a full **recursive** RLM over a sub-context, for
    sub-tasks that are themselves too big for one leaf call (depth > 1). Falls back
    to `llm_query` at the depth limit.
- You build intermediate results into REPL variables/buffers, then return the
  answer by setting it in the REPL: `FINAL(answer)` or `FINAL_VAR(varname)`.

**The division of labour that makes this work:** the **LLM does the semantics**
(classify this question, extract this fact, summarise this section); your **Python
does the bookkeeping** (loop over every chunk, count, aggregate, format). Do not
ask the LLM to count or do arithmetic over the whole corpus, and do not try to do
the semantics yourself in Python with keyword heuristics — that is exactly the
failure mode the paper's ablations show. Split the work along that seam.

## When to use this

Use it when the context won't fit comfortably in the conversation **and** the task
needs broad access to it: aggregation/counting over every item, labelling every
row, multi-hop questions across a corpus, whole-document summarisation, or
"the answer depends on almost every line". For a one-off needle lookup in a file
you can just `grep`, you don't need this.

## Inputs (`$ARGUMENTS`)

- `context=<path>` (required): path to the large context file.
- `query=<question>` (required): what to answer about it.
- Optional: `sub_model=<alias>` (default `haiku`), `max_workers=<int>` (default 8),
  `max_depth=<int>` (default 1; >1 enables recursive `rlm_query`).

If the user didn't supply them, ask for the context file path and the query.

Set optional knobs via environment before running, e.g.:
`export RLM_SUB_MODEL=haiku RLM_MAX_WORKERS=8 RLM_MAX_DEPTH=1`.

## The loop (Algorithm 1)

Run these via the **Bash** tool. State persists between calls in
`.claude/rlm_state/state.pkl`. By default, `init` also creates a standalone
audit replay package under `.claude/rlm_runs/<run_id>/`; every `exec` saves the
submitted Python as `steps/step_XXXX.py`.

### 1. Initialise — load the context, read only its metadata

```bash
python .claude/skills/rlm/scripts/rlm_repl.py init <context_path>
```

This prints the context's type, char/line/token estimate, and a short prefix.
**Do not** read the context file with the Read tool — that defeats the purpose.
It also prints the audit replay package path. Use `--no-audit` only when you do
not want standalone step scripts.

### 2. Probe — understand the format with small, cheap code

Look at the shape of the data before deciding a strategy. Print *small* slices and
structure, not the bulk:

```bash
python .claude/skills/rlm/scripts/rlm_repl.py exec <<'PY'
print(peek(0, 1500))                 # head
lines = [l for l in content.splitlines() if l.strip()]
print("lines:", len(lines))
print("sample:", lines[1] if len(lines) > 1 else "")
PY
```

Ask: Is it line-oriented? JSON objects? Markdown sections? Logs with timestamps?
The format dictates the chunking.

### 3. Decompose + sub-query — write code that calls the LLM over chunks

This is the core. Chunk the context, build one prompt per chunk, and fan the
**semantic** work out to the sub-LM with `llm_query_map` (parallel). Keep the
chunks fat (a leaf can hold a large slice — batch to minimise call count) but small
enough that the sub-LM stays accurate. Accumulate results in a variable; let Python
do the aggregation.

```bash
python .claude/skills/rlm/scripts/rlm_repl.py exec <<'PY'
# Example shape for an aggregation task: derive records from the actual format,
# ask leaf LMs for semantic labels, then count/aggregate in Python.
records = [line.strip() for line in content.splitlines() if line.strip()]

# Fill these from the user's query and what you observed while probing. Do not
# assume the file's delimiter, item marker, or labels before inspecting it.
question = "What should be classified or extracted for each record?"
categories = ["category_a", "category_b", "category_c"]

def build(batch, start):
    body = "\n".join(f"{start+i}: {record}" for i, record in enumerate(batch))
    return (
        f"{question}\n"
        f"Use exactly one of these categories: {', '.join(categories)}.\n"
        "Output exactly one line per record as 'N: <category>'. No extra text.\n\n"
        + body
    )

BATCH = 50
prompts = [build(records[s:s+BATCH], s) for s in range(0, len(records), BATCH)]
outs = llm_query_map(prompts)          # parallel sub-LM calls; order preserved

import re
from collections import Counter
labels = {}
for out in outs:
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s*[:.\)]\s*(.+)", ln)
        if m:
            labels[int(m.group(1))] = m.group(2).strip().strip("*[]").lower()
missing = [i for i in range(len(records)) if i not in labels]
counts = Counter(labels.values())
print("classified:", len(labels), "/", len(records), "missing:", len(missing))
print("counts:", dict(counts))
PY
```

Because the REPL is persistent, `items`, `labels`, and `counts` survive into your
next `exec`. Inspect, sanity-check, and re-run pieces as needed. Save durable
intermediate text with `add_buffer(...)` (it lives in the `buffers` list).

### 4. Aggregate + answer — compute the final answer, set it in the REPL

Do the final arithmetic/formatting in Python, then set the answer. **The answer
must be a REPL variable or literal — not just something you say in chat** (so it
can be arbitrarily long and is captured verbatim):

```bash
python .claude/skills/rlm/scripts/rlm_repl.py exec <<'PY'
top = counts.most_common(1)[0][0]
answer = f"Label: {top}"
FINAL_VAR("answer")          # or: FINAL(f"Label: {top}")
PY
python .claude/skills/rlm/scripts/rlm_repl.py final   # prints the stored answer
```

Then report that final answer to the user, in the exact output format the query
asked for.

## REPL interface (what's available inside `exec`)

Injected automatically every `exec` (you never import or define these):

| name | what it does |
|---|---|
| `context` / `content` | the full context, as a `str` (two names for the same value) |
| `llm_query(prompt, model=None, timeout=300, system=...)` | one sub-LM leaf call → text |
| `llm_query_map(prompts, max_workers=8, ...)` | many leaf calls in parallel → list of texts, in order |
| `rlm_query(context_text, query, ...)` | recursive RLM over a sub-context (depth>1); falls back to `llm_query` at max depth |
| `FINAL(answer)` / `FINAL_VAR(name)` | set the final answer (literal / by variable name) |
| `peek(start, end)` | a slice of the raw context |
| `grep(pattern, max_matches, window)` | regex search → matches with surrounding snippets |
| `chunked(seq, size)` | yield size-length slices of a list (lines, etc.) |
| `chunk_indices(size, overlap)` / `write_chunks(dir, ...)` | character chunk spans / write chunks to files |
| `add_buffer(text)` / `buffers` | append to / read the persistent list of intermediate results |

Your own variables persist between `exec` calls (anything pickleable). `stdout` is
truncated (~8000 chars) before you see it — `print` summaries and samples, not bulk.

## Standalone audit replay

Each audited `exec` writes:

- `steps/step_XXXX.py` - a normal Python script containing the original REPL code
  plus a small prelude that recreates the RLM globals.
- `steps/step_XXXX.json` - metadata such as hashes, output paths, and final status.
- `steps/step_XXXX.stdout.txt` / `.stderr.txt` - the original captured output.
- `runtime/` - a copy of the runtime needed by the generated scripts.
- `replay_all.py` - runs all saved steps from a clean `replay_state.pkl`.

Replay with:

```bash
python .claude/rlm_runs/<run_id>/replay_all.py
```

Replay calls `llm_query` live, so sub-LM text can differ from the original run.
The replay checkpoint is separate from the live REPL state and does not mutate
`.claude/rlm_state/state.pkl`.

## Guardrails — these are where RLMs win or lose

- **Never read the whole context into the conversation.** No Read tool on the
  context file, no `print(content)`. Work through the REPL and sub-LM calls. If you
  catch yourself wanting the full text in chat, chunk it and `llm_query` it instead.
- **Split semantics from arithmetic.** LLM = meaning (classify/extract/summarise);
  Python = counting/aggregation/formatting. Counting with the LLM, or classifying
  with `if "keyword" in line`, both score badly.
- **Batch sub-calls; don't make one call per line.** Put many items in each
  `llm_query` (e.g. 50–100 short lines per call) and parallelise with
  `llm_query_map`. Thousands of one-item calls are slow and costly for no accuracy
  gain. But keep batches small enough that the sub-LM doesn't drop or miscount items
  — verify `classified == total` and re-run any short/garbled batch.
- **Process the *entire* context before answering** for aggregation tasks — the
  point is that you can't shortcut it. Check your coverage counts.
- **Return the answer from the REPL** via `FINAL`/`FINAL_VAR`, then echo it to the
  user in the requested format. Don't stop at intermediate buffers.
- **Recursion (`rlm_query`) is for sub-tasks too big for one leaf**, e.g. "analyse
  these 500 documents that each need their own chunking". It is slower and costlier;
  most tasks (including pure aggregation) only need `llm_query`. Default `max_depth`
  is 1.

## Notes

- The sub-LM is a nested headless Claude Code (`claude -p`) and reuses your existing
  login — no API key or SDK. `llm_query` runs it with tools **off** (a plain LLM);
  `rlm_query` runs it with bash + this skill **on** (its own REPL).
- Keep all scratch/state under `.claude/rlm_state/`.
