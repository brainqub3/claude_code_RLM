# RLM skill vs plain agents on OOLONG (`trec_coarse`, 10 samples)

**Question (issue #6):** does the `/rlm` skill — an **Opus 4.8 root orchestrating a cheap
Haiku 4.5 leaf** — beat the *same two models run as plain Claude Code agents* (RLM off) on
the OOLONG `trec_coarse` eval? Does it break the accuracy/cost frontier those two agents
define?

**Run:** `20260618_221644` (started 2026-06-18 22:17, finished 2026-06-19 02:00 UTC).
All three arms ran through the one matched harness (`run_rlm_skill_eval.py`), 10 samples,
single-shot headless `claude -p`, cold per-task state, default per-task timeout. Scored
out-of-band with `score.py` (default manifest). Models: root/agent `claude-opus-4-8`,
leaf/agent `claude-haiku-4-5`.

## How RLMs work

A **Recursive Language Model** (RLM) treats a long prompt not as something to cram into the
model's context window, but as an *external environment* the model interacts with
programmatically. The root LLM is given only metadata about the context (e.g. its length) plus a
REPL in which the full text sits as a variable; it then writes code to peek into and decompose
that variable and to **recursively call an LLM over slices of it**, aggregating the results — so
it never reads the whole input directly. This sidesteps the "context rot" that degrades frontier
models on long inputs and lets the system handle prompts well beyond any single context window.
In our setup the root is **Opus 4.8** (orchestration only) and the recursive leaf calls go to a
cheap **Haiku 4.5** — opus brain, cheap labour.

See *Recursive Language Models*, Zhang, Kraska & Khattab (MIT CSAIL), arXiv:2512.24601 — the
committed PDF is at [`paper/2512.24601v3.pdf`](../paper/2512.24601v3.pdf); our scaffold follows
its Algorithm 1.

## The OOLONG `trec_coarse` task — and why it's hard

**OOLONG** [Bertsch et al., 2025] is a long-context *reasoning* benchmark: the input is a large
corpus of short questions, each already tagged with a semantic label, and each task can only be
answered by **semantically labelling and then aggregating across nearly the whole corpus**. We use
its `trec_coarse` split — ~3,182 questions (~131K tokens) from the TREC question-classification
dataset, where every item belongs to one of six coarse classes (*entity, numeric value, human
being, location, abbreviation, description/abstract concept*) — and sample 10 of its 50 tasks. The
tasks in our run are: the most/least frequent label (`MOST_FREQ` / `LEAST_FREQ`), the exact count
of one class (`NUMERIC_ONE_CLASS`), and pairwise relative-frequency comparisons (`RELATIVE_FREQ`).

**Why it is a hard long-context task — and the right test for an RLM:**

- **The answer depends on almost every line.** This is the property the paper singles out: OOLONG
  is "a task where the answer depends explicitly on almost every line in the prompt." Unlike
  needle-in-a-haystack (find one fact and stop), there is no span to retrieve — every one of the
  ~3,182 items feeds a count or a ranking, and one missed or misclassified line can move the
  answer. Search / grep / RAG, which rescue NIAH, do not help here.
- **Linear-complexity aggregation, so it breaks models *early*.** The paper's central point is that
  a model's *effective* context window depends on the task: NIAH keeps the needle constant, so
  frontier models scale to 1M+ tokens, whereas OOLONG's work grows *linearly* with input (label +
  tally every item) and models hit "context rot" and degrade at far *shorter* lengths. At 131K
  tokens that is already thousands of items to process correctly in a single pass.
- **Two compounding sub-tasks per item.** Each line must first be *classified* into a label and
  then *aggregated*; classification noise and counting error compound over thousands of items.
- **Exact counts are unforgiving.** The `NUMERIC` tasks demand an exact integer over ~3,182 items,
  so a handful of misclassifications scores 0. That is exactly our result below — every arm solved
  the noise-tolerant tasks (dominant label, directional comparison) but **all three scored 0/4 on
  exact counting**, where near-perfect per-item accuracy is required.

This is the canonical case the `/rlm` skill targets: a question that depends on almost every line
and cannot be answered by a single retrieval — so the root must decompose the corpus, sub-query the
leaf over chunks, and aggregate in code.

---

## Headline

| Arm | Setup | Accuracy | Total cost | Tokens | Wall | Orch-fail |
|---|---|---:|---:|---:|---:|---:|
| **RLM** | opus root + haiku leaf (RLM **on**) | **55.6%** | $47.73 | 44.92 M | 88.6 min | 0/10 (0%) |
| Opus agent | `claude-opus-4-8`, plain agent (RLM off) | 40.0% | $25.43 | 9.34 M | 115.0 min | — |
| Haiku agent | `claude-haiku-4-5`, plain agent (RLM off) | 40.0% | $1.59 | 6.31 M | 19.9 min | — |

**The result is split — and which way it points depends on whether you pay per token or per
subscription.**

- ✅ **Accuracy:** the RLM scaffold won — **55.6% vs 40.0% / 40.0%**, +15.6 points over *both*
  controls, with **0/10 orchestration failures** (every task set `FINAL`, none used a
  forbidden/deferral tool, none read the context directly).
- ✅ **Frontier-model usage:** the RLM spent only **2.54 M Opus tokens** on the root vs the Opus
  agent's **9.34 M** — **~3.7× fewer frontier tokens** — pushing the bulk (42.4 M tokens) onto
  the cheap, abundant Haiku tier. On subscription plans, where the *top tier is the rationed
  resource*, this is the number that matters (see below).
- ✅ **Speed:** the RLM finished the 10 tasks in **88.6 min vs the Opus agent's 115.0 min** —
  **~23% faster** — despite moving far more total tokens, because the Haiku leaf is fast and the
  Opus agent burns wall-clock re-reading the 131K context over many turns.
- ❌ **Raw pay-per-token cost:** the RLM was the **most expensive** arm — **$47.73**, ~1.9× the
  Opus agent and ~30× Haiku. The cheap-per-call leaf is not cheap in aggregate: the root's
  self-authored strategy issued **~1,303 leaf calls** over **42.4 M tokens** ($42.86). For
  pay-per-token API billing this is a real loss and contradicts the original "match Opus accuracy
  at *lower* cost" hypothesis — but see the subscription view below, where the trade-off inverts.

### Cost/accuracy frontier (pay-per-token dollars)

The two agents define the cost/accuracy frontier; the RLM sits above and to the right of it:

```
accuracy
 56% |                                  ● RLM (opus+haiku)  $47.73
     |
 40% | ● Haiku $1.59      ● Opus $25.43
     +----------------------------------------------------------- cost
```

- **Haiku agent Pareto-dominates the Opus agent** on this sample: identical 40.0% accuracy at
  1/16th the cost. There is no cost/accuracy reason to prefer the plain Opus agent here.
- **The RLM is the only arm above 40%.** If you need the extra accuracy it is the only option on
  offer — but you pay the most for it. It does not "match Opus accuracy cheaply"; it buys
  +15.6 points at the highest price.

---

## Frontier-model usage — the subscription view

The pay-per-token dollar figure hides a split in *which* resource each arm consumes. On Claude
subscription plans the binding constraint is not dollars but **usage of the top tier**: Opus (and
Fable) draw down plan limits fastest and are the first models you get rate-limited on. Counted in
*frontier* tokens, the RLM is the frugal arm, not the expensive one:

| Arm | Frontier (Opus) tokens | Cheap-tier (Haiku) tokens | Accuracy |
|---|---:|---:|---:|
| **RLM** | **2.54 M** (root) | 42.38 M (leaf) | 55.6% |
| Opus agent | 9.34 M | — | 40.0% |
| Haiku agent | — | 6.31 M | 40.0% |

The RLM spent **~3.7× fewer Opus tokens than the Opus agent** while scoring 15.6 points higher —
it reserves Opus for orchestration over metadata and offloads the token-heavy reading/counting to
the abundant Haiku tier.

**Implication (argued, not billed by this eval — which prices everything in pay-per-token USD):**
a subscriber who routinely hits the Opus ceiling could get *more* frontier-grade long-context
answers per billing period by running the RLM than by pointing a plain Opus agent at the raw
context — same-or-better accuracy for ~3.7× less of the rationed Opus budget per task, paid for in
cheap, abundant Haiku tokens. In that setting the RLM doesn't merely match the frontier agent's
accuracy in the scarce resource — it *exceeds* it. This inverts the "most expensive arm" headline:
expensive in pay-per-token dollars, frugal in the resource a subscription actually rations, and so
plausibly a net **performance gain** for subscription users who would otherwise be throttled down
to a weaker model once their Opus allowance runs out.

## Speed — the RLM beat the frontier agent

| Arm | Wall (10 tasks) |
|---|---:|
| Haiku agent | 19.9 min |
| **RLM** | **88.6 min** |
| Opus agent | 115.0 min |

Despite moving ~5× more total tokens than the Opus agent (44.9 M vs 9.3 M), the RLM finished
**~23% faster** (88.6 vs 115.0 min). The Haiku leaf is high-throughput and each sub-call is short,
whereas the plain Opus agent spends long, high-reasoning turns repeatedly re-reading the 131K
context (up to 33 turns on a single task). So the leaf's token-hunger does **not** translate into a
wall-clock penalty here — the scaffold is both more accurate *and* faster than the frontier agent
it is meant to replace.

---

## Why the RLM cost what it did (root vs leaf)

| Component | Tokens | Cost | Share |
|---|---:|---:|---:|
| **Root** (opus, orchestration) | 2.54 M | $4.87 | 10% |
| **Leaf** (haiku, per-chunk labour) | 42.38 M | $42.86 | 90% |
| **Total** | 44.92 M | $47.73 | 100% |

The *structural* intent of the scaffold held: the Opus root stayed cheap ($4.87, 10% of spend)
by orchestrating over metadata rather than reading the 131K context. But the labour the root
delegated was enormous — the leaf re-read large slices of context across hundreds of calls. The
counting (`NUMERIC`) tasks and the `same frequency` comparison drove this; classification/label
tasks were comparatively lean.

| # | id | type | leaf calls | leaf tok | task cost | score |
|--:|---|---|--:|--:|--:|--:|
| 1 | 17000206 | LABEL | 160 | 5.25 M | $6.27 | ✓ 1.00 |
| 2 | 17000208 | LABEL | 64 | 2.12 M | $2.74 | ✓ 1.00 |
| 3 | 17000222 | NUMERIC | 64 | 2.12 M | $2.69 | ✗ 0.00 |
| 4 | 17000223 | NUMERIC | 174 | 5.78 M | $6.73 | ✗ 0.00 |
| 5 | 17000238 | NUMERIC | 148 | 4.86 M | $5.70 | ~ 0.56 |
| 6 | 17000239 | NUMERIC | 277 | 8.78 M | $8.65 | ✗ 0.00 |
| 7 | 17000207 | COMPARISON | 64 | 2.12 M | $2.67 | ✓ 1.00 |
| 8 | 17000210 | COMPARISON | 64 | 2.14 M | $2.70 | ✓ 1.00 |
| 9 | 17000213 | COMPARISON | 80 | 2.61 M | $3.05 | ✓ 1.00 |
| 10 | 17000237 | COMPARISON | 208 | 6.60 M | $6.53 | ✗ 0.00 |

Total ≈ 1,303 leaf calls. The most expensive single task (17000239, 277 calls, $8.65) cost more
than the entire Haiku-agent arm ($1.59).

---

## Accuracy by task type

All three arms agree on the easy bands and split only on labels + counting.

| Answer type | items | Opus agent | Haiku agent | **RLM** |
|---|--:|--:|--:|--:|
| LABEL | 2 | 1/2 (50%) | 1/2 (50%) | **2/2 (100%)** |
| NUMERIC (count) | 4 | 0/4 (0%) | 0/4 (0%) | **~0.6/4 (14%)** |
| COMPARISON | 4 | 3/4 (75%) | 3/4 (75%) | 3/4 (75%) |
| **Overall** | 10 | **40.0%** | **40.0%** | **55.6%** |

Where the RLM's +15.6 points come from:
- **LABEL:** RLM got both (2/2); both agents missed one (the agents answered a different TREC
  label on item 17000208, the RLM did not).
- **NUMERIC:** everyone is bad at exact counting over 3,182 lines, but the RLM at least landed
  *close* on one item (partial credit 0.56; its count was off by ~0.5%), whereas both agents
  missed every count outright — often wildly (the Haiku agent answered `0` and `2` on two of
  them).
- **COMPARISON:** identical across all three (3/4). The one comparison every arm missed
  (17000237) is a `same frequency` item — all three answered a directional "more/less common"
  instead.

> Predictions are shown; the gold answer key is deliberately kept out of this committed report
> to preserve the blind-eval guard for future runs (the manifest is gitignored). Per-item
> predictions and scores live in each arm's `preds_*.jsonl` / `diagnostics.json` and can be
> re-derived with `score.py`.

---

## Honest caveats

- **n = 10.** Single small sample, no repeats. The accuracy gaps (especially the LABEL items
  that account for the RLM's lead) rest on 1–2 questions and should not be over-read. A larger
  sample and multiple seeds are needed before treating 55.6% vs 40% as stable.
- **A stated premise did not reproduce.** Issue #6 motivates the RLM partly by "the plain Haiku
  agent's 20% collapse." On this sample the Haiku agent did **not** collapse — it tied the Opus
  agent at 40.0% for $1.59. So the cheap control was far stronger (and far more cost-efficient)
  than the framing assumed.
- **The cost story has two sides.** The scaffold is mechanically sound (0% orchestration failure,
  root stays cheap) and more accurate, but as self-authored here it is **token-hungry**: ~1,300
  leaf calls / 42 M tokens. In *pay-per-token dollars* that makes it the most expensive arm. In
  *frontier-token* terms (the subscription view above) it is the frugal one. Both are true; which
  one matters depends on how you are billed. Either way, the obvious next lever is a more
  token-frugal leaf strategy — fewer, larger, deduplicated passes rather than hundreds of
  overlapping chunk reads — which would improve the dollar story *and* the frontier story at once.
- **The subscription advantage is an inference, not a billed result.** This eval prices everything
  in pay-per-token USD; the "more out of your subscription" argument follows from the measured
  Opus-vs-Haiku token split, but was not directly measured as subscription throughput or against
  real plan rate-limits. For pay-per-token API users, the RLM here is simply a cost regression.
- **Consistent with the paper's cost profile.** *Recursive Language Models* (arXiv:2512.24601)
  reports RLMs beating Claude Code by ~13% (median) at *comparable* cost, with costs comparable at
  the median but spiking at the tail (their Fig. 11). Our run reproduces that shape: cheap,
  comparable median tasks and a heavy tail on the counting questions (one task alone — 277 leaf
  calls / $8.65 — cost more than the entire Haiku-agent arm).
- **Counting is the shared weakness.** No arm reliably counts label occurrences across the full
  context (combined 0/12 exact on `NUMERIC`, one near-miss). This is the task family most worth
  targeting next, for both agents and the scaffold.

---

## Reproduction

```bash
TS=20260618_221644   # one run-id shared by all three arms
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode agent --root opus
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode agent --root haiku
python rlm_vs_agent_experiment/run_rlm_skill_eval.py --run-id $TS --mode rlm   --root opus
# score (default manifest):
python rlm_vs_agent_experiment/score.py --predictions rlm_vs_agent_experiment/runs/$TS/agent_opus/preds_agent.jsonl
python rlm_vs_agent_experiment/score.py --predictions rlm_vs_agent_experiment/runs/$TS/agent_haiku/preds_agent.jsonl
python rlm_vs_agent_experiment/score.py --predictions rlm_vs_agent_experiment/runs/$TS/rlm_skill_opus/preds_rlm_skill.jsonl
```

Run artifacts (gitignored scratch): `rlm_vs_agent_experiment/runs/20260618_221644/`
— `run_all.log`, plus `agent_opus/`, `agent_haiku/`, `rlm_skill_opus/` each with
`preds_*.jsonl`, `diagnostics.json`, and `_runs/` transcripts.
