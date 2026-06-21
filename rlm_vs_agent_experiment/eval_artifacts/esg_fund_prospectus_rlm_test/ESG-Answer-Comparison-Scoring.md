# ESG Answer Comparison Scoring

**Question assessed:** Which funds have ESG-related commitments, and how do their sustainability labels, benchmarks and risk factors differ?

**Answers compared:**

- `ESG-Commitments-Analysis-Non-RLM.md`
- `ESG-Commitments-Analysis-RLM.md`

**Method notes compared:**

- `methods/ESG-Analysis-Methodology.md`
- `methods/RLM-Method-ESG-Analysis.md`

## Source Checks

I checked both answers against the converted prospectus context in:

`context/blackrock-investment-funds-prospectus/blackrock-investment-funds-prospectus.md`

Key checks:

- The front-page fund list contains **26 named funds**.
- Appendix 1 also resolves to **26 fund sections** once the terminating funds are counted correctly.
- There are **16** occurrences of the statement that a fund "does not have a UK sustainable investment label".
- There is **1** occurrence of the statement that a fund "applies a sustainability improvers label".
- Therefore the source supports the RLM headline count: **17 ESG-commitment funds and 9 non-ESG funds**.

The non-RLM answer is internally inconsistent: it says **14** funds have ESG commitments, but its own list contains **17** funds if the LifePath family is expanded. It also says "all 13 other ESG funds" disclaim a label, where the source-backed count is **16 other ESG funds**.

## Scorecard

| Dimension | Non-RLM | RLM | Notes |
|---|---:|---:|---|
| Fund universe / classification | 3.0 | 4.5 | Source shows 26 funds and 17 ESG-commitment funds. RLM gets this right. Non-RLM says 27 and 14, but then effectively lists 17, so the substance is partly right but the headline arithmetic is wrong. |
| Sustainability labels | 3.5 | 5.0 | RLM correctly lands the 16 no-label plus 1 Sustainability Improvers split. Non-RLM correctly identifies Brown to Green as the only labelled fund, but says "13 other" ESG funds instead of 16. |
| Benchmarks / carbon targets | 4.5 | 3.0 | Non-RLM is stronger: it distinguishes target, comparator, no benchmark, and carbon Reference Comparator use. RLM wrongly implies LifePath and MyMap Reference Comparators are ESG-built; the source says they represent assets with no specific ESG criteria. |
| Risk factor analysis | 4.5 | 2.5 | Non-RLM is much better because it incorporates the general ESG risk section, Scope 3/carbon data risks, Brown-to-Green transition risks, and fund-of-funds risks. RLM admits it only extracted per-fund-section risks, so it misses important cross-cutting risk material. |
| Method quality | 3.5 | 4.5 | RLM has the better scalable method: split all funds, structured JSON extraction, programmatic counts, and verification. Non-RLM's method is more manual and made reconciliation errors, but it did better cross-document synthesis. |

## Totals

| Category | Non-RLM | RLM |
|---|---:|---:|
| Answer quality, first 4 dimensions | 15.5 / 20 | 15.0 / 20 |
| Method | 3.5 / 5 | 4.5 / 5 |
| Combined | 19.0 / 25 | 19.5 / 25 |

## Verdict

The RLM method is better for coverage and count discipline. It correctly finds the 26-fund universe and the 17 ESG-commitment / 9 non-ESG split.

The non-RLM answer is the better analytical answer after correcting its headline count errors. It gives a more useful explanation of benchmarks and risk factors, especially because it uses the general ESG risk sections rather than only per-fund snippets.

Best combined approach: use RLM to extract every fund into a structured table, then add a second extraction pass over the general ESG, risk, and benchmark methodology sections before synthesis. That would likely keep RLM's coverage advantage while avoiding its risk-factor blind spot.
