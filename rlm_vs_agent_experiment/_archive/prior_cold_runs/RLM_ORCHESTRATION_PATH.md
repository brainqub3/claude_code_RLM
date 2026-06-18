# How the RLM root actually solved each task — the orchestration trace

This document reconstructs the **actual path the RLM root took at runtime** on the
OOLONG `trec_coarse` tasks — the real sequence of steps, the code the root authored
itself, the leaf calls it made, and how it aggregated. Nothing here is the intended
or idealised flow: it is read back verbatim from the captured stream-json
transcripts.

**Provenance.** Every claim below is traceable to the raw transcripts:

- Root transcripts: `rlm_skill_<root>/_runs/task_<id>.stream.jsonl` (full turn-by-turn
  stream-json: assistant reasoning + every tool call + the stdout the root saw).
- Leaf-call usage: `rlm_skill_<root>/_runs/leaf_usage_<id>.jsonl` (one record per
  `claude -p` leaf call: model, tokens, cost).
- Reconstruct any task yourself:
  `python _runs_extract_path.py rlm_skill_opus/_runs/task_17000206.stream.jsonl`

**What the harness handed the root.** Only `context=<file path>` and
`query=<the OOLONG question>`, plus an operational instruction to use the `rlm`
skill and finish synchronously. **No** label taxonomy, **no** classify-then-count
recipe, **no** OOLONG parsing. The root discovered everything else. (See
`run_rlm_skill_eval.py` → `ROOT_PROMPT_TEMPLATE`.)

**Scope.** The **opus-root arm is complete (10/10)**. The **haiku-root arm (H3) is a
partial 3/10** — the run was stopped early; its three transcripts are included
because they document the weak-root failure modes clearly.

---

## 1. The canonical path (opus root) — followed on 9 of 10 tasks

Worked example: **task 17000206** (`LEAST_FREQ`, gold = `numeric value`). The opus
root took an **8-step path** and finished in 11 turns. Reproduce with
`python _runs_extract_path.py rlm_skill_opus/_runs/task_17000206.stream.jsonl`.

**Step 1 — invoke the skill.** `Skill(rlm)` → loads the procedure.

**Step 2 — init the REPL on metadata only.**
```
python .claude/skills/rlm/scripts/rlm_repl.py init ".../contexts/trec_coarse_cw6.txt"
# -> context : str (308,367 chars, ~3,191 lines, ~77,091 tokens est.) ; final : not set
```
The root never reads the file into its own window — only this metadata + a 600-char
preview. (`read_context_directly = False` for all 10 opus tasks.)

**Step 3 — probe the format.** Small diagnostic code (not bulk):
```python
lines = [l for l in content.splitlines() if l.strip()]
print("total non-empty lines:", len(lines))           # 3186
inst = [l for l in lines if "Instance:" in l]
print("lines with 'Instance:':", len(inst))           # 3182
```

**Step 4 — extract the items.**
```python
items = [l.split("Instance:",1)[1].strip() for l in lines if "Instance:" in l]
# extracted items: 3182 ; sample 0: 'What is splatterpunk ?' ; sample last: 'What is BPH ?'
```

**Step 5 — author the classification prompt (self-written labels + definitions).**
The six labels are **inferred from the context file's own header**; the harness never
supplied them. The root also wrote its own per-class definitions and chose a batch
size:
```python
CATS = ["numeric value", "entity", "human being", "location",
        "abbreviation", "description and abstract concept"]
def build(batch, start):
    body = "\n".join(f"{start+i}: {q}" for i, q in enumerate(batch))
    return ("You are classifying general-knowledge questions by the TYPE OF ANSWER "
            "they expect.\nAssign each question to EXACTLY ONE of these 6 categories:\n"
            f"{catlist}.\nDefinitions:\n"
            "- 'numeric value': answer is a number, count, date, amount, distance...\n"
            "- 'entity': a thing/object/animal/substance/product/work...\n"
            "- 'human being': a person or group of people.\n"
            "- 'location': a place (city, country, region...).\n"
            "- 'abbreviation': an abbreviation/acronym or its expansion.\n"
            "- 'description and abstract concept': a definition, reason, manner...\n"
            "Output EXACTLY one line per question 'N: <category>'...\n\n" + body)
BATCH = 50          # -> 64 batches over 3182 items
```

**Step 6 — fan out to the cheap leaf, synchronously.** This is the recursion: one
`claude -p` (`haiku`, tools off) per batch, 8 in parallel.
```python
outs = llm_query_map(prompts, max_workers=8)   # done in 283.3 s ; 64 outputs
```

**Step 7 — parse + aggregate in Python (LLM does meaning, Python does arithmetic).**
The root wrote tolerant parsing with alias normalisation and **verified coverage**:
```python
labels = {}            # idx -> canonical category, via regex + alias map
...
print("classified:", len(labels), "/", len(items))   # 3182 / 3182
print("unparsed lines:", 0, "missing:", 0)
counts = Counter(labels.values())
# {'description and abstract concept':628,'human being':503,'entity':597,
#  'abbreviation':529,'location':524,'numeric value':401}
```

**Step 8 — set the answer in the REPL.** `numeric value` (401) is least common →
`FINAL("Label: numeric value")`. Correct.

### The other standard tasks took the identical shape

All 8 remaining opus tasks (the 9th being the tie outlier in §3) followed the same
init → probe → extract → classify-in-batches → parse+aggregate → `FINAL` path, varying
only the batch size and the final arithmetic the question asked for:

| id | task | batch→leaf calls | coverage | the root's answer | gold | score |
|---|---|---|---|---|---|---|
| 17000206 | LEAST_FREQ | 50 → 64 | 3182/3182 | Label: numeric value | numeric value | ✅ 1.00 |
| 17000208 | MOST_FREQ | 50 → 64 | 3182/3182 | Label: numeric value | numeric value | ✅ 1.00 |
| 17000207 | RELATIVE | 50 → 64 | 3182/3182 | …less common than… | less common | ✅ 1.00 |
| 17000210 | RELATIVE | 50 → 64 | 3182/3182 | …less common than… | less common | ✅ 1.00 |
| 17000213 | RELATIVE | 40 → 80 | 3182/3182 | …more common than… | more common | ✅ 1.00 |
| 17000222 | NUMERIC (desc) | 40 → 80 | 3182/3182 | Answer: 388 | 352 | ❌ 0.00 (Δ36) |
| 17000223 | NUMERIC (entity) | 40 → 80 | 3182/3182 | Answer: 794 | 748 | ❌ 0.00 (Δ46) |
| 17000238 | NUMERIC (numeric) | 50 → 64 | 3182/3182 | Answer: 401 | 398 | ◐ 0.42 (Δ3) |
| 17000239 | NUMERIC (entity) | 50 → 64 | 3182/3182 | Answer: 643 | 521 | ❌ 0.00 (Δ122) |

The pattern: **the scaffold reliably forces exhaustive classification and exact
Python counting (3182/3182 every time)**, so LABEL and direction-of-comparison tasks
land; the residual error is entirely the **haiku leaf's per-item classification
accuracy**, which shows up as small biases that wreck the exact-count NUMERIC tasks.

---

## 2. What the root decided for itself (the faithfulness check)

The strategy was authored at runtime, not handed over. Across the opus transcripts
the root independently:

- **Inferred the six labels** from the context file's own header (the harness prompt
  contains no taxonomy).
- **Wrote its own category definitions** to disambiguate the leaf's classification.
- **Chose the decomposition** — line-oriented extraction on the `Instance:` marker,
  batch size 40–50, 8-way parallelism.
- **Wrote tolerant parsing** (regex + alias/normalisation map) and **verified
  coverage** (`classified == total`, zero unparsed) before trusting the counts.
- **Kept semantics in the LLM and arithmetic in Python** — it never asked the leaf to
  count, and never classified with keyword heuristics.
- **Never read the context directly** — `read_context_directly = False` on all 10
  tasks; tool use was only `{Skill, Bash}`.

This is the point of the experiment: the orchestration is what an LLM root produces
cold from the general skill, not a pre-written harness.

---

## 3. The outlier path — task 17000237 (the tie), and an autonomous model escalation

Gold for 17000237 is a genuine **tie** (`location` *same frequency as* `abbreviation`).
The opus root refused to trust a close margin and escalated — a 16-turn,
**405-leaf-call, $23.65** path (45 % of the whole arm's cost). Trace:

1. Standard single haiku pass → `LOC 508` vs `ABBR 524` (margin 16).
2. Root flags the margin as within classification noise; **audits** borderline labels
   (they look correct) and notes the dataset is near class-uniform.
3. Runs a **second** independent haiku pass → it **flips**: `LOC 525` vs `ABBR 504`.
4. Diffs the passes: 94.5 % agreement; isolates the **91 disagreement items** as the
   deciding set.
5. **Escalates the leaf model to `sonnet`** for a **3-vote majority** on those 91.
6. Recombine → `LOC 529` vs `ABBR 531` (margin 2, flipped *again*).
7. Still too close → runs a **full 3-pass `sonnet` re-classification of all 3182**.
8. Sonnet majority → `LOC 525, ABBR 515`; all three passes agree LOC > ABBR →
   `FINAL("Answer: location is more common than abbreviation")`.

**Two things to note.** (a) The root **autonomously switched the leaf from `haiku` to
`sonnet`** on this task — a runtime decision via the skill's `model=` override, not a
harness setting. The leaf-usage log confirms it: 17000237 = **144 haiku calls ($5.53)
+ 261 sonnet calls ($16.99)**, while the other 9 tasks are **pure haiku**. (b) Despite
all that effort it still **got the tie wrong** (answered "more common"): the gold is a
genuine equality that even a sonnet 3-pass majority couldn't confirm. This single task
is the dominant source of the opus arm's cost variance.

---

## 4. Weak-root paths (haiku root) — H3, partial (3/10)

The same skill driven by a **haiku root** orchestrates unreliably. The three completed
transcripts show three different outcomes:

- **17000206 — right answer, wildly inefficient.** Needed to `Read` the
  `rlm_repl.py` source to recover the command syntax (the opus root never did), then
  used tiny batches → **480 leaf calls, $9.81** for a task the opus root did in 64
  calls / $3.10. Answer `numeric value` (correct).
- **17000208 — mechanical failure, no answer.** Backgrounded the classification and
  called **`ScheduleWakeup`** to wait for it — the async-defer trap — then ended after
  21 turns with **`FINAL` never set** (only 26 leaf calls fired). Scored output:
  `[no answer produced]`. Note this happened *despite* the synchronous-completion
  instruction and `Monitor` being disallowed; the weak root found a different way to
  defer.
- **17000222 — completes, worse count.** `Answer: 436` (gold 352) vs the opus root's
  388 — lower per-orchestration quality on the same leaf.

**Takeaway for H3:** holding the leaf fixed at `haiku`, swapping a strong root for a
weak one breaks the scaffold in three ways at once — inefficient decomposition,
failure to run to completion (no `FINAL`), and noisier aggregation. Orchestrator
strength, not just the scaffold, drives the result. (A clean 10/10 H3 score needs the
remaining 7 tasks; this arm was stopped early.)

---

## 5. Reproduce / inspect

```bash
# Full step-by-step trace of any task the root ran:
python _runs_extract_path.py rlm_skill_opus/_runs/task_17000206.stream.jsonl
python _runs_extract_path.py rlm_skill_opus/_runs/task_17000237.stream.jsonl   # the tie blow-up
python _runs_extract_path.py rlm_skill_haiku/_runs/task_17000208.stream.jsonl  # the no-answer failure

# Per-leaf-call model/cost breakdown for a task:
#   cat rlm_skill_opus/_runs/leaf_usage_17000237.jsonl   # shows the haiku->sonnet escalation
```
