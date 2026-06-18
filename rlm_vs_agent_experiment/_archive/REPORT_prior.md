# OOLONG long-context aggregation — Claude Code agent baselines (`opus` vs `haiku`)

**Benchmark:** OOLONG `trec_coarse`, 10 tasks @ 131,072 tokens · **Dates:** 2026-06-17 – 2026-06-18

> ## ⚠️ Status: the RLM arm is withdrawn and pending re-run
>
> An earlier version of this report included an **RLM** result (54.2%) produced by
> `run_rlm_eval.py` — a **deterministic, OOLONG-specific harness** whose classify-then-count strategy
> was written and verified **by hand**, not authored by the model at runtime. That measures the RLM
> paradigm's *ceiling when the orchestration is already correct*, not what the **general `/rlm` skill**
> produces cold. It has been **archived** at `_archive/rlm_haiku_prewritten_harness/` and removed from
> the comparison below. The proper RLM experiment (LLM-as-root, self-authored strategy, root + leaf
> cost accounted) is tracked in **issue #6** and will be folded back in when run.
>
> **This report therefore currently covers only the two agent baselines**, which are unaffected and
> stand on their own.

---

## Abstract

We ran a normal Claude Code agent (default tools on) over 10 OOLONG `trec_coarse` aggregation tasks —
each a 131K-token context of 3,182 unlabelled TREC questions plus a distributional question that
depends on *every* item — on two models, **`opus`** and **`haiku`**, scored with the official
OOLONG-synth scorer. **Dropping the agent from `opus` to `haiku` collapses it from 54.6% to 20.0%**
(−34.6 points), for **$72.31 → $2.70**. The collapse is concentrated exactly where the task requires
processing all items: LABEL 100%→0%, NUMERIC ~12%→0%; only comparison tasks partly survive
(75%→50%). The `haiku` agent's own output shows it **sampling/estimating** (counts like 273 vs gold
748) rather than classifying all 3,182 items. **Takeaway: a plain agent's accuracy on whole-context
aggregation is strongly model-dependent — the cheap model takes the shortcut the task is designed to
punish.** Whether an RLM scaffold removes that dependence (the original hypothesis) is deferred to
issue #6. (Scope: 10 tasks over 2 contexts, 2026-06-17/18 list prices — a single reproducible data
point, not a broad sweep.)

---

## 1. The task

OOLONG (Bertsch et al., 2025; arXiv:2511.02817) `trec_coarse` presents a long context — **3,182
short TREC questions**, each with a user and date, **no labels shown** — and asks a distributional
question whose answer is a deterministic function of *every* item:

- **LABEL** — which coarse semantic class is most / least common? (e.g. `numeric value`)
- **NUMERIC** — exactly how many items are class *X*?
- **COMPARISON** — is class *A* more / less common than class *B*, or the same?

The six classes are the standard TREC coarse labels (*numeric value, entity, human being, location,
abbreviation, description and abstract concept*). The labels are never in the input, so a system must
infer the class of essentially every line and aggregate — retrieval/keyword shortcuts can't work.
This subset is **10 tasks over 2 distinct 131K-token contexts** (2 LABEL, 4 NUMERIC, 4 COMPARISON);
every gold answer was independently re-derived, and the scorer self-test scores 1.00. For reference,
the paper's Table 1 reports **GPT-5 base = 44.0 → RLM = 56–58** on OOLONG `N=131K`.

**Scoring** (`score.py`, a faithful re-implementation of the upstream OOLONG-synth scorer): parse the
text after the last `:`; **exact match → 1.0**; COMPARISON by phrase; **NUMERIC partial credit
`0.75^|gold−pred|`** (≈0 past a difference of ~8); else 0.0.

---

## 2. Setup — a normal Claude Code agent on two models

Plain Claude Code, headless, **default tools on** (`claude -p --model <opus|haiku>
--permission-mode bypassPermissions`, web tools disabled). It is given the **absolute path** to the
context file and the task, told the file holds 3,182 items and is larger than a single read returns
(so it must account for all of them — avoiding the silent file-read truncation trap; it is *not* told
how to classify), and left to solve however it likes (read in chunks, write/run a script, reason
directly). Each task is an **independent** session (no caching across tasks). The two runs differ only
in `--model`. Driver: `agent_*/run_plain_eval.py`.

> The RLM arm that will accompany these baselines (the general `/rlm` skill, LLM-as-root) is specified
> in **issue #6**; it is intentionally *not* the archived pre-written harness.

**Operational notes.** (a) The `opus` run executed in two phases for unrelated reasons (initial tasks
206/208/222/223, then an agent-only resume); consolidated in `agent_opus/diagnostics.json`. (b) The
`haiku` run hit a **Windows-only logging crash** after task 6 (a `✓` in the model output vs. cp1252);
the driver was hardened (UTF-8 logging) and tasks 7–10 resumed. Neither affects any per-task figure.

---

## 3. Results

### 3.1 Headline

| System | Score | Tokens | Cost | End-to-end time |
|---|---:|---:|---:|---:|
| **Agent — `opus`, tools on** | **54.6%** | 6,445,722 | **$72.31** | ~104 min |
| **Agent — `haiku`, tools on** | **20.0%** | 8,277,515 | **$2.70** | ~47 min |
| *RLM — general `/rlm` skill* | *pending — see issue #6* | — | — | — |
| *Paper Table 1 — GPT-5 base / RLM (reference)* | *44.0 / 56–58* | — | — | — |

### 3.2 Per-task (predicted answer / score)

Grouped by answer type. NUMERIC shows `pred (Δ)` where Δ = |gold − pred|.

| id | task | gold | agent `opus` | | agent `haiku` | |
|---|---|---|---|--:|---|--:|
| 17000206 | LEAST_FREQ | numeric value | numeric value | **1.00** | description & abstract | 0.00 |
| 17000208 | MOST_FREQ | numeric value | numeric value | **1.00** | description & abstract | 0.00 |
| 17000207 | RELATIVE | less common than | less common than | **1.00** | less common than | **1.00** |
| 17000210 | RELATIVE | less common than | less common than | **1.00** | less common than | **1.00** |
| 17000213 | RELATIVE | more common than | more common than | **1.00** | less common than | 0.00 |
| 17000237 | RELATIVE | same frequency as | more common than | 0.00 | more common than | 0.00 |
| 17000222 | NUMERIC | 352 | 414 (Δ62) | 0.00 | 298 (Δ54) | 0.00 |
| 17000223 | NUMERIC | 748 | 737 (Δ11) | 0.04 | 273 (Δ475) | 0.00 |
| 17000238 | NUMERIC | 398 | 401 (Δ3) | **0.42** | 308 (Δ90) | 0.00 |
| 17000239 | NUMERIC | 521 | 547 (Δ26) | 0.00 | 109 (Δ412) | 0.00 |
| | | **mean** | | **0.5465** | | **0.2000** |

By answer type:

| answer_type | agent `opus` | agent `haiku` |
|---|---:|---:|
| LABEL (most/least common) | 2/2 = **100%** | 0/2 = **0%** |
| COMPARISON (A vs B) | 3/4 = **75%** | 2/4 = **50%** |
| NUMERIC (exact count) | 0.46/4 = **11.6%** | 0/4 = **0%** |

### 3.3 Efficiency

| | agent `opus` | agent `haiku` |
|---|---:|---:|
| Total cost | $72.31 | $2.70 |
| Cost / task (mean) | $7.23 | $0.27 |
| Total tokens | 6,445,722 | 8,277,515 |
| Total wall time | ~104 min | ~47 min |
| Effective blended rate | ~$11.22 / MTok | ~$0.33 / MTok |

---

## 4. Finding — the agent approach degrades sharply on a cheaper model

**`opus` agent 54.6% → `haiku` agent 20.0%** (−34.6 points; it keeps ~37% of the score) while cost
falls **~27×** ($72.31 → $2.70). The collapse is not uniform — it lands exactly where the task
demands processing *every* item:

- **LABEL: 100% → 0%.** The `haiku` agent answered "description and abstract concept" for both
  most- and least-common questions (a default-ish guess), where gold is "numeric value".
- **NUMERIC: ~12% → 0%.** Its counts are wildly low (273 vs gold 748; 109 vs gold 521) — the model's
  own output reveals it working from a **small sample / running percentages** (e.g. on task 208 it
  reported "location: 184 (5.79%) … entity: 152 (4.78%)"), not an exhaustive pass over 3,182 items.
- **COMPARISON: 75% → 50%.** Only direction-only comparisons partly survive (it got the two "less
  common" cases, missed the "more common" one and the tie).

So a plain agent's accuracy on whole-context aggregation is **highly model-dependent**: swap the
frontier model for a cheap one and it falls apart, because the cheap model takes the shortcut the task
is specifically designed to punish.

Note the `opus` agent's own ceiling (~54.6%): it nails LABEL and most COMPARISON but loses the
exact-count NUMERIC tasks (drift of tens; only `numeric value`, the most distinctive class, scores —
Δ3 on task 238) and the one true frequency **tie** (task 237). The shared limiter is **per-item
accuracy of the 6-way TREC classification**, which even `opus` doesn't saturate.

### Deferred — does an RLM scaffold remove the model-dependence?

The original hypothesis was that an RLM (which *forces* exhaustive per-item classification + exact
Python counting) lets a **cheap** model match a frontier agent — i.e. that the scaffold substitutes
for model strength. The earlier 54.2% RLM figure that appeared to support this was produced by a
**hand-written OOLONG harness** and has been withdrawn (see the Status banner and
`_archive/rlm_haiku_prewritten_harness/`). The fair test — the **general `/rlm` skill** with an LLM
root authoring the strategy at runtime, and root + leaf cost both counted — is specified in
**issue #6** and will be added here when run.

---

## 5. Token-pricing assumptions

Per-task **cost was not estimated** — each `claude -p` call reports its own `total_cost_usd`, and we
summed those verbatim. List prices below are recorded so the totals are auditable. Verified against
the Claude API pricing reference (per **million tokens**, USD):

| Model | Input | Output | Cache write — 5-min (1.25×) | Cache write — 1-hour (2×) | Cache read (0.1×) |
|---|---:|---:|---:|---:|---:|
| **Claude Opus 4.8** (`claude-opus-4-8`) | $5.00 | $25.00 | $6.25 | $10.00 | $0.50 |
| **Claude Haiku 4.5** (`claude-haiku-4-5`) | $1.00 | $5.00 | $1.25 | $2.00 | $0.10 |

- **Token total per call** = `input + output + cache_creation + cache_read`.
- **Claude Code caches its CLI system prompt at the 1-hour TTL**, so cache *writes* are billed at
  **2× base** (confirmed: `usage.cache_creation` shows `ephemeral_1h_input_tokens`).
- First-party list prices, no negotiated/volume discount; figures reflect list rates on 2026-06-17/18.

Sanity check (not used to compute anything): blended effective rate = total cost / total tokens →
`opus` agent **~$11.22/MTok**, `haiku` agent **~$0.33/MTok**.

---

## 6. Conclusion

A normal Claude Code agent on whole-context OOLONG aggregation is **strongly model-dependent**:
`opus` reaches 54.6% (limited by per-item TREC classification, not by orchestration), but `haiku`
collapses to **20.0%** because it samples/estimates instead of processing all 3,182 items. The cost
swing is ~27×. The open and more interesting question — whether the **RLM scaffold** lets a *cheap*
model recover frontier-agent accuracy by forcing exhaustive classification + exact counting — is
**not answered here**: the figure that previously suggested it used a pre-written harness and has been
withdrawn. The proper test of the general `/rlm` skill is tracked in **issue #6**.

---

## 7. Auditability — reproduce the scores from this folder

Self-contained for the two agent arms: the scorer, the manifest (with gold answers), both agent
predictions files, and full diagnostics/logs are included. Re-derive both headline scores:

```bash
# Agent (opus):   expect 0.5465, 6,445,722 tok, $72.3138
python score.py --manifest oolong_trec_coarse.jsonl --predictions agent_opus/preds_agent_opus.jsonl

# Agent (haiku):  expect 0.2000, 8,277,515 tok, $2.6994
python score.py --manifest oolong_trec_coarse.jsonl --predictions agent_haiku/preds_agent_haiku.jsonl
```

Both were re-scored from these copied files and reproduce the numbers above exactly. (The archived RLM
predictions under `_archive/` still score to 0.5422 but are **not** part of this comparison — see the
Status banner.)

### Contents

```
rlm_vs_agent_experiment/
├── REPORT.md                       # this report
├── score.py                        # official OOLONG-synth scorer (stdlib-only)
├── oolong_trec_coarse.jsonl        # manifest: 10 tasks + gold answers
├── agent_opus/
│   ├── preds_agent_opus.jsonl      # scored predictions (10 agent tasks)
│   ├── diagnostics.json            # consolidated agent-only per-task diagnostics (all 10 tasks)
│   ├── agent_rest.log              # raw log, agent tasks 5–10
│   └── run_plain_eval.py           # the plain-agent driver
├── agent_haiku/
│   ├── preds_agent_haiku.jsonl     # scored predictions (10 agent tasks)
│   ├── diagnostics.json            # consolidated agent-only per-task diagnostics (all 10 tasks)
│   ├── run1_tasks1-6.log           # raw log, tasks 1–6 (ends with the Windows logging crash)
│   ├── run2_tasks7-10.log          # raw log, tasks 7–10 (resumed with the hardened driver)
│   └── run_plain_eval.py           # same plain-agent driver
└── _archive/
    └── rlm_haiku_prewritten_harness/   # WITHDRAWN pre-written-harness RLM run (see README + issue #6)
        ├── README.md
        ├── preds_rlm.jsonl
        ├── diagnostics.json
        ├── run.log
        └── run_rlm_eval.py
```

## Provenance & license

- **Benchmark:** OOLONG — Bertsch, Pratapa, Mitamura, Neubig, Gormley, *Oolong: Evaluating Long
  Context Reasoning and Aggregation Capabilities*, 2025 (arXiv:2511.02817). Scorer/task code from
  [`abertsch72/oolong`](https://github.com/abertsch72/oolong) (MIT). Cite the OOLONG paper if you use it.
- **RLM:** Zhang, Kraska, Khattab, *Recursive Language Models*, 2025 (arXiv:2512.24601).
- Prices are first-party Claude API list rates as of 2026-06-17/18.
