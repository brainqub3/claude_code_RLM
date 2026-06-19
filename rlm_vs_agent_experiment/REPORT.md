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

---

## Headline

| Arm | Setup | Accuracy | Total cost | Tokens | Wall | Orch-fail |
|---|---|---:|---:|---:|---:|---:|
| **RLM** | opus root + haiku leaf (RLM **on**) | **55.6%** | $47.73 | 44.92 M | 88.6 min | 0/10 (0%) |
| Opus agent | `claude-opus-4-8`, plain agent (RLM off) | 40.0% | $25.43 | 9.34 M | 115.0 min | — |
| Haiku agent | `claude-haiku-4-5`, plain agent (RLM off) | 40.0% | $1.59 | 6.31 M | 19.9 min | — |

**The result is split, and it does _not_ confirm the headline hypothesis.**

- ✅ **Accuracy:** the RLM scaffold won — **55.6% vs 40.0% / 40.0%**, +15.6 points over *both*
  controls. The Opus root reliably drove the skill: **orchestration-failure rate 0/10** (every
  task set `FINAL`, none used a forbidden/deferral tool, none read the context directly).
- ❌ **Cost:** the RLM was the **most expensive** arm — **$47.73**, ~1.9× the Opus agent and
  ~30× the Haiku agent. The hypothesis was "match Opus accuracy at *much lower* cost." Instead
  the scaffold *exceeded* Opus accuracy at *higher* cost. The cheap-per-call Haiku leaf was not
  cheap in aggregate: the root's self-authored strategy issued **~1,303 leaf calls** over
  **42.4 M tokens** ($42.86).

### The frontier

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
- **The cost story is the real finding.** The scaffold is mechanically sound (0% orchestration
  failure, root stays cheap) and more accurate, but as self-authored here it is **token-hungry**:
  ~1,300 leaf calls / 42 M tokens. To deliver on the original promise (frontier accuracy at low
  cost) the leaf strategy would need to be far more token-frugal — fewer, larger, deduplicated
  passes rather than hundreds of overlapping chunk reads. That is the obvious next lever.
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
