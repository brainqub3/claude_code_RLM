# Generate PRD with RLM-Mem Hybrid Analysis

Create a Product Requirements Document informed by both historical context (claude-mem) and current codebase capabilities (RLM).

## When to Use

- Planning a new feature
- After `/dev:start` has provided session context
- When you need a data-driven, context-aware PRD

## What This Command Does

1. **Searches past PRDs** (claude-mem) to learn structure and quality
2. **Analyzes current codebase** (RLM) to understand capabilities
3. **Synthesizes** a PRD that builds on existing work
4. **Saves** PRD to claude-mem for future reference

## Process

### Step 0: Load Profile

Read `~/.claude/active-profile.yaml` if it exists. If not present,
use defaults: rlm=true, memory_backend=claude-mem. Skip claude-mem
steps (Step 2) if `tools.memory_backend` is `none`. Skip RLM
analysis (Step 3) if `tools.rlm` is `false`.

### Step 1: Gather Requirements from User

Ask the user for feature details:
- **JIRA ID**: (e.g., AS-1234) - required for file organization
- **Feature name**: Short descriptive name
- **User problem**: What problem does this solve?
- **Expected outcome**: What should the user be able to do?

### Step 2: Search Claude-Mem for Past PRDs

**2a. Find similar past features**:
```
mcp__plugin_claude-mem_mcp-search__search(
  query="{feature_name} requirements user stories similar features",
  project="{project_name}",
  type="PRD",
  limit=5
)
```

**2b. Get full details of best matches**:
```
mcp__plugin_claude-mem_mcp-search__get_observations(
  ids=[top_3_relevant_ids]
)
```

**Extract from past PRDs**:
- PRD structure and sections used
- Quality of user stories (format, detail level)
- Acceptance criteria patterns
- How requirements were scoped

### Step 3: RLM Analysis of Current Capabilities

**3a. Find related existing features**:
```bash
python3 ~/.claude/rlm_scripts/rlm_repl.py exec <<'PY'
keywords = ['feature_term', 'related_concept']  # fill with terms from the feature name and problem domain

relevant = []
for kw in keywords:
    relevant += find_symbol(kw, type='function')
    relevant += find_files_by_pattern(f'**/*{kw}*')
for f in list(set(relevant))[:5]:
    relevant += get_related_files(f)
paths = write_file_chunks(list(set(relevant))[:20], strategy='file')
import json; print(json.dumps(paths))
PY
```

**3b. Analyze architecture patterns** (if relevant files found):

Use rlm-subcall subagent to analyze sample files:
- Query: "Identify existing architecture patterns, API structure, data models, and integration points that relate to this feature"
- Limit: Top 3-5 most relevant files
- Collect findings about current capabilities

**3c. Identify gaps**:
Based on files found in 3a and rlm-subcall analysis, explicitly list:
- **Existing**: components/patterns already present that this feature can build on
- **Missing**: what needs to be created or extended

### Step 4: Ask Clarifying Questions (MANDATORY)

**🚨 BEFORE writing the PRD, you MUST ask clarifying questions using the
AskUserQuestion tool.** The goal is to understand the "what" and "why" of the
feature. Adapt questions based on the prompt, but common areas to explore:

- **Problem/Goal:** "What problem does this feature solve for the user?" or
  "What is the main business goal we want to achieve?"
- **Target Users:** "Who are the primary users of this feature?"
- **Success Metrics:** "How will we measure success? What metrics matter most?"
- **Use Cases:** "What are the main use cases this feature should support?"
- **Feature Scope:** "What should this feature include? What should it
  explicitly NOT include?"
- **Acceptance Criteria:** "What are the key acceptance criteria that define
  'done' for this feature?"
- **Dependencies:** "Does this feature depend on other systems or services?"
- **Risks:** "What are the main risks or potential blockers?"

**Technical Context Questions (informed by RLM findings from Step 3):**
- "I found [pattern from RLM]. Should this feature follow the same approach?"
- "Existing [similar feature] handles [X]. Should we integrate or build new?"
- "Current architecture uses [finding]. Any constraints for this feature?"

Always include an **"All clear, proceed"** option for users with clear
requirements. If user selects it, skip to Step 5.

**Take the user's answers and incorporate them into the PRD below. Do NOT leave
answered questions in an "Open Questions" section.**

### Step 5: Synthesize PRD

Create PRD combining insights + user's clarifications:

```markdown
# {JIRA-ID}: {Feature Name} - PRD

**Status**: Draft
**Created**: {date}
**JIRA**: [{JIRA-ID}](https://jira.example.com/browse/{JIRA-ID})
**Author**: Claude (via dev workflow analysis)

---

## Context

{User-provided problem statement}

### Current State (observed)

Each factual claim about the codebase or runtime MUST be sourced:
append `— verified via: <file:line | command | host>, <date>` or
tag with `[assumption, verify in tech-design]`. Unsourced claims
are rejected by the reality-check pass (Step 5.5).

- {Observation 1} — verified via: `{source}`, {date}
- {Observation 2} — [assumption, verify in tech-design]

### Past Similar Features (from claude-mem)
{Reference to similar features we've built, what we learned}

## Problem Statement

**Who**: {Target user persona}
**What**: {Specific problem they face}
**Why**: {Impact of the problem}
**When**: {Context/triggers}

## Goals

### Primary Goal
{Main objective this feature achieves}

### Secondary Goals
- {Supporting objective 1}
- {Supporting objective 2}

## User Stories

### Epic
As a {user type}, I want to {capability}, so that {benefit}.

### User Stories
1. **As a** {user type}
   **I want** {specific functionality}
   **So that** {specific benefit}

   **Acceptance Criteria**:
   - [ ] {Testable criterion 1}
   - [ ] {Testable criterion 2}
   - [ ] {Testable criterion 3}

2. {Additional user stories following same pattern}

## Requirements

**Describe by class and sensitivity, not by concrete identifier.**
PRDs drift when they enumerate specific keys, column names, routes,
or env vars — those belong in tech-design, where they're validated
against code. Prefer "5 database connection parameters including
one high-sensitivity password" over listing each by name. Concrete
identifiers are allowed only when the identifier itself IS the
requirement (e.g. "expose endpoint `POST /v2/webhooks` for
backward compat").

### Functional Requirements
1. **FR-1**: {Requirement description}
   - **Priority**: High/Medium/Low
   - **Rationale**: {Why this is needed}
   - **Dependencies**: {What this depends on from RLM analysis}

2. **FR-2**: {Next requirement}

### Non-Functional Requirements
1. **NFR-1**: Performance - {Specific metric}
2. **NFR-2**: Security - {Specific requirement}
3. **NFR-3**: Usability - {Specific expectation}

### Technical Constraints
{Based on RLM analysis of existing architecture}
- Must integrate with: {Existing systems found via RLM}
- Should follow patterns: {Patterns discovered in codebase}
- Cannot change: {Constraints from existing architecture}

## Out of Scope

{What we explicitly won't do in this iteration}
- {Out of scope item 1}
- {Out of scope item 2}

## Success Metrics

**How we'll measure success**:
1. {Metric 1}: {Target value}
2. {Metric 2}: {Target value}
3. {Metric 3}: {Target value}

## References

### From Codebase (RLM)
- Relevant files: {List of files from RLM analysis}
- Existing patterns: {Patterns to follow}
- Integration points: {Where this connects}

### From History (Claude-Mem)
- Similar features: {Reference to past PRDs}
- Lessons learned: {What to avoid/replicate}

---

**Next Steps**:
1. Review and refine this PRD
2. Run `/dev:tech-design` to create technical design
3. Run `/dev:tasks` to break down into tasks
```

### Step 5.5: Reality-Check Pass (MANDATORY)

Before saving, scan the draft for factual claims about the
codebase, runtime, or environment. Every such claim must be one of:

1. **Sourced** — followed by `— verified via: <file:line | command
   output | host>, <date>`. If the source is an RLM call, name the
   exact helper (`find_symbol`, `grep`) and the term queried.
2. **Tagged as assumption** — annotated
   `[assumption, verify in tech-design]`.

If neither: stop, surface the unsourced claim to the user, ask them
to confirm the source or tag it as an assumption, then retry.

Typical offenders: config key lists, column names, API routes,
version numbers, file counts, "the system currently does X"
statements. If you're tempted to enumerate identifiers, re-check
whether that list belongs in tech-design instead (per the
Requirements guidance above).

### Step 6: Save PRD to File System

```bash
# Create task directory
mkdir -p tasks/{jira_id}-{feature_name_slug}

# Write PRD file
# tasks/{jira_id}-{feature_name_slug}/{YYYY-MM-DD}-{jira_id}-{feature_name_slug}-prd.md
```

After writing, **Read the file back** — the PostToolUse hook captures it
as a claude-mem observation automatically. No explicit save call needed.

### Step 7: Report Completion

```markdown
# ✅ PRD Created: {JIRA-ID}

**Feature**: {Feature Name}
**File**: `tasks/{jira_id}-{feature_name_slug}/{date}-{jira_id}-{feature_name_slug}-prd.md`

## Insights Used

### From Claude-Mem:
- Analyzed {n} past PRDs
- Learned structure from: {best_example_jira_id}
- Referenced similar feature: {similar_feature}

### From RLM:
- Analyzed {m} relevant files
- Discovered existing capabilities: {summary}
- Identified integration points: {list}
- Noted constraints: {constraints}

## Quality Improvements

Thanks to hybrid analysis, this PRD:
✅ Follows proven structure from past PRDs
✅ Aware of current codebase capabilities
✅ References actual integration points
✅ Scoped based on existing patterns
✅ Includes realistic constraints

## Next Steps

**Create technical design**:
```
/dev:tech-design
```

**Or refine PRD first**:
- Review user stories
- Validate acceptance criteria
- Confirm scope
```

## Important Notes

1. **Quality from Examples**:
   - Use past PRDs as quality benchmarks
   - Don't just copy structure, learn what makes them good
   - Adapt to current feature needs

2. **Grounded in Reality**:
   - RLM analysis shows what actually exists
   - Don't assume capabilities, verify with code
   - Constraints come from actual architecture

3. **Iterative**:
   - This is a draft, expect refinement
   - User feedback may change requirements
   - Technical design may reveal gaps

4. **Save Everything**:
   - Save to both claude-mem and file system
   - File system: team collaboration
   - Claude-mem: future AI context

## Example Output

```
# ✅ PRD Created: AS-1290

**Feature**: Cloud Storage Integration
**File**: `tasks/AS-1290-cloud-storage/2025-02-06-AS-1290-cloud-storage-prd.md`

## Insights Used

### From Claude-Mem:
- Analyzed 3 past PRDs
- Learned structure from: AS-1245 (similar integration feature)
- Referenced: OAuth2 auth pattern

### From RLM:
- Analyzed 15 relevant files
- Discovered: Existing storage abstraction layer
- Integration points: FileManager, SyncService classes
- Constraints: Must support existing backup format

## Quality Improvements

✅ Follows proven structure
✅ Aware of storage abstraction layer
✅ References actual FileManager API
✅ Scoped to work with existing auth
✅ Realistic constraints from architecture

## Next Steps
/dev:tech-design
```

## Context7

When referencing any library, framework, or external API — use the Context7 MCP to look up current documentation rather than guessing. Call `mcp__context7__resolve-library-id` then `mcp__context7__get-library-docs`. Never invent API signatures or assume version-specific behaviour.

## Final Instructions

1. Gather requirements from user (JIRA ID, feature name, problem)
2. Search claude-mem for past PRDs to learn from
3. Use RLM to analyze current codebase capabilities
4. **🚨 MANDATORY: Ask clarifying questions using AskUserQuestion tool**
5. Synthesize PRD incorporating user's answers + RLM + claude-mem insights
6. Save to both claude-mem and file system
7. Report what insights were used and quality improvements
8. Suggest `/dev:tech-design` as next step
9. DO NOT start technical design yet, wait for user approval
