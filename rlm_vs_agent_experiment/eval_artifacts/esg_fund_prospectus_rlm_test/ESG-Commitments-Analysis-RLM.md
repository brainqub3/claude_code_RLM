# BlackRock Investment Funds — ESG Commitments, Labels, Benchmarks & Risk Factors

**Source:** `blackrock-investment-funds-prospectus.pdf` (BlackRock Investment Funds Prospectus, 15 June 2026 — 172 pages, Appendix 1 "Details of each of the Funds")
**Question:** Which funds have ESG-related commitments, and how do their sustainability labels, benchmarks and risk factors differ?
**Method:** RLM loop — PDF converted to Markdown (~178K tokens), split into 26 per-fund sections, a sub-LM extraction run over each fund, results aggregated and verified in Python. No raw PDF text was loaded into the main context.

---

## Headline

Of the **26 funds** in Appendix 1:

- **17 make binding ESG / sustainability commitments**
- **9 make none**
- **Only 1 fund carries an actual UK SDR sustainability label** (Brown To Green Materials Fund — *Sustainability Improvers*).
- The other **16 ESG funds** all carry the identical disclaimer that they *"do not have a UK sustainable investment label."*

---

## Funds with ESG-related commitments (17)

| Group | Fund | SDR label | ESG approach |
|---|---|---|---|
| **Labelled (1)** | **Brown To Green Materials Fund** | **Sustainability Improvers** (only labelled fund) | Formal *sustainability objective*; ≥70% in "transition improvers" judged against an evidence-based standard tied to SBTi targets / temperature alignment; decarbonisation KPIs + engagement |
| **Screened active (4)** | Sterling Strategic Bond | No UK label | EMEA Baseline Screens + 20% carbon-intensity cut vs Bloomberg + PEXT/NEXT externality tilt |
| | ESG Screened and Selected Strategic Growth | No UK label | Baseline Screens + min MSCI ESG rating **BBB** + 70% of underlying schemes must apply ESG |
| | Systematic Multi Allocation Credit | No UK label | Baseline Screens; max 20% non-compliant exposure |
| | Sterling Short Duration Credit | No UK label | Baseline Screens + 20% carbon-intensity cut + PEXT/NEXT |
| **MyMap "Select ESG" (3)** | MyMap 3 Select ESG | No UK label | Exclusions + govt-bond ESG rating **≥BB+** + ≥80% of holdings apply ESG + carbon intensity ~30% below comparator |
| | MyMap 5 Select ESG | No UK label | As above |
| | MyMap 8 Select ESG | No UK label | As above, **plus** absolute carbon-reduction targets through 2028 |
| **LifePath target-date suite (9)** | LifePath Retirement | No UK label | ≥80% of govt-bond funds track ESG-rated indices (≥BB); ≥80% of other funds apply ESG exclusions + ESG/carbon-score uplift; monitored |
| | LifePath Target Date 2030 | No UK label | As above |
| | LifePath Target Date 2035 | No UK label | As above |
| | LifePath Target Date 2040 | No UK label | As above |
| | LifePath Target Date 2045 | No UK label | As above |
| | LifePath Target Date 2050 | No UK label | As above |
| | LifePath Target Date 2055 | No UK label | As above |
| | LifePath Target Date 2060 | No UK label | As above |
| | LifePath Target Date 2065 | No UK label | As above |

## Funds with no ESG commitments (9)

| Fund | Note |
|---|---|
| BlackRock Dynamic Return Strategy Fund | Being terminated |
| BlackRock Systematic Global Long / Short Equity Fund | Being terminated |
| MyMap 3 Fund | — |
| MyMap 4 Fund | — |
| MyMap 4 Select Income Fund | Being terminated |
| MyMap 5 Fund | — |
| MyMap 6 Fund | — |
| MyMap 7 Fund | — |
| BlackRock Global Smaller Companies Fund | — |

These funds make no SDR statement and disclose no ESG-specific risk factors.

---

## How they differ

### 1. Sustainability labels — a one-vs-sixteen split

Brown To Green is the **sole** fund using a UK SDR label ("sustainability improvers"), which is why it alone has a stated *sustainability objective*. The other 16 ESG funds all carry the identical disclaimer that they **"do not have a UK sustainable investment label"** — they integrate binding ESG criteria but don't meet (or don't seek) the formal labelling threshold. The 9 non-ESG funds make no SDR statement at all.

> Verified programmatically: 16 occurrences of the exact line *"does not have a UK sustainable investment label"* + 1 *"sustainability improvers label"* = 17 ESG funds, reconciling to all 26 funds.

### 2. Benchmarks — ESG is mostly applied *on top of* conventional indices, not *via* ESG indices

Most ESG funds still measure performance against standard market indices (MSCI ACWI, Bloomberg Global Aggregate, MSCI ACWI Materials) — ESG enters as **screens / tilts**, not index choice. Notably even Brown To Green benchmarks to plain MSCI ACWI / ACWI Materials; its sustainability is delivered through its objective and methodology rather than an ESG index.

Exceptions where the **index itself** is ESG-constructed:

- **Systematic Multi Allocation Credit** — uses the **J.P. Morgan EMBI ESG Global Diversified** index as one of three target indices.
- **LifePath and MyMap "Select ESG" funds** — use internal **"Reference Comparators"** that blend **ESG-rated government-bond indices (≥BB)**, so the constraint is partly ESG-built.

The carbon-reduction funds also differ by expressing benchmarks as *relative* targets (e.g. "20–30% below" a named index) rather than simply tracking it.

### 3. Risk factors — scale with how binding the commitment is

The non-ESG funds disclose no ESG-specific risks. Among ESG funds, recurring themes are:

- reliance on **third-party ESG data** (MSCI);
- ESG **data gaps / estimation error**;
- ESG **screening shrinking the investable universe** (concentration);
- **no guarantee** ESG / carbon targets are met.

The **screened credit funds carry the most granular ESG risk disclosure** — Sterling Strategic Bond and Sterling Short Duration Credit specifically warn that:

- carbon-intensity scores **exclude Scope 3** emissions;
- screens cover only **direct corporate holdings** (derivatives / funds / money-market instruments bypass them);
- **PEXT/NEXT** tilts are not quantified or binding;
- there is no minimum portfolio ESG-compliance threshold.

> **Completeness caveat:** Risk extraction was per-fund-section, so trust-wide sustainability risks defined in the general *Risk Factors* section (which apply to all ESG funds, including Brown To Green) are not attributed in the table above — it reflects only what each fund's own section spells out.

---

*Generated from the prospectus via the RLM (Recursive Language Model) skill. Figures were cross-checked against the source text rather than estimated.*
