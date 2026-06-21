# ESG Fund Prospectus RLM Test

Manual eval artifacts copied from `C:\Users\johna\OneDrive\Documents\RLM Test`.

This experiment was run in Claude Code as a comparison between one agent equipped
with the RLM harness and one agent without it. The non-RLM run used Opus 4.8
directly. The RLM run used Opus 4.8 as the root model with Haiku 4.5 as the leaf
model.

Research question:

> Which funds have ESG-related commitments, and how do their sustainability
> labels, benchmarks and risk factors differ?

The context for both runs is the BlackRock Investment Funds prospectus:

- `context/blackrock-investment-funds-prospectus.pdf`
- `context/blackrock-investment-funds-prospectus/blackrock-investment-funds-prospectus.md`

This folder is intentionally outside the active harness paths. It is provenance
for a fund-prospectus ESG analysis comparison, not input consumed by
`run_rlm_skill_eval.py`.

Contents:

- `context/` - BlackRock Investment Funds prospectus source PDF and extracted Markdown.
- `methods/` - Method notes for the non-RLM and RLM approaches.
- `ESG-Commitments-Analysis-Non-RLM.md` - Non-RLM result report.
- `ESG-Commitments-Analysis-RLM.md` - RLM result report.
- `ESG-Answer-Comparison-Scoring.md` - Comparison and scoring notes.

The source folder's local `.agents/`, `.claude/`, and `skills-lock.json` files were
not copied because they are local agent/tooling state rather than eval artifacts.
