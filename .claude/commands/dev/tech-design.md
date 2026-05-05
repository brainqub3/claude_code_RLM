# Generate Technical Design with RLM-Mem Hybrid Analysis

Create a technical design informed by past architectural decisions (claude-mem) and current code patterns (RLM).

## When to Use

- After PRD is approved
- When planning implementation approach
- Before breaking down into tasks

## Process

### Step 0: Load Profile

Read `~/.claude/active-profile.yaml` if it exists. If not present,
use defaults: rlm=true, memory_backend=claude-mem. Skip claude-mem
searches if `tools.memory_backend` is `none`. Skip RLM discovery
(Step 2-3) if `tools.rlm` is `false`.

### Step 1: Load Context

**Read PRD**:
- From file: `tasks/{jira-id}-{feature}/...-prd.md`
- Or search claude-mem for recent PRD
  (skip if profile `tools.memory_backend` is `none`)

**Search past tech designs** (claude-mem)
(skip if profile `tools.memory_backend` is `none`):
```
mcp__plugin_claude-mem_mcp-search__search(
  query="{feature_keywords} architecture design patterns technical",
  type="TECH-DESIGN",
  limit=5
)
```

### Step 1.5: Verify Inherited PRD Facts

Treat every factual claim in the PRD's "Current State (observed)"
section and any concrete identifier that leaked into Requirements
(config keys, column names, routes, counts, version numbers) as an
**input to verify**, not a truth to build on.

For each claim:
- If it carries `— verified via: ...`, re-run the named source
  (read the file, run the command, query RLM) and confirm it still
  holds. Stale verification is worse than none.
- If it carries `[assumption, verify in tech-design]`, resolve it
  now via RLM / file read / command — or flag it as a blocker.
- If a concrete identifier appears in the PRD, independently
  confirm it against code before reusing it. Do not copy
  identifiers verbatim without a code-level check.

Record each resolved claim in the tech-design's "Current
Architecture (RLM-verified)" section with its own source citation
(file:line, command, date). A PRD fact that fails verification
invalidates the dependent requirement — stop and loop back to
`/dev:prd` rather than designing against a false premise.

### Step 2: RLM Architecture Discovery

**Discover existing patterns**:
```bash
python3 ~/.claude/rlm_scripts/rlm_repl.py exec <<'PY'
# Find architecture-relevant files
arch_files = []

# Look for main architectural components
patterns = ['handler', 'service', 'controller', 'manager', 'repository', 'model']
for pattern in patterns:
    matches = [
        path for path, meta in repo_index['files'].items()
        if pattern in path.lower()
        and not meta['is_binary']
        # optionally filter by language: and meta['lang'] in ['C++', 'TypeScript', 'Python']
    ]
    arch_files.extend(matches[:5])  # Top 5 per pattern

print('\n'.join(set(arch_files)[:30]))
PY
```

**Analyze patterns with rlm-subcall**:
- Query: "Extract architectural patterns: layering, dependency injection, error handling, data flow, module structure"
- Files: Top 10 most representative architecture files
- Collect: Design patterns, conventions, anti-patterns

### Step 3: Identify Integration Points

**Find where new code will connect**:
```bash
python3 ~/.claude/rlm_scripts/rlm_repl.py exec <<'PY'
# Based on PRD requirements, find integration points
# Example: If adding auth, find where current auth is used

integration_points = {
    'will_modify': [],   # Existing files we'll change
    'will_create': [],   # New files we'll add
    'dependencies': [],  # External deps we'll use
}

# Analyze based on feature requirements
# ...

import json
print(json.dumps(integration_points, indent=2))
PY
```

### Step 4: Learn from History

**Query past decisions** (claude-mem):
```
mcp__plugin_claude-mem_mcp-search__search(
  query="why we chose {relevant_tech} architecture decision trade-offs",
  limit=5
)
```

Extract:
- Past architectural decisions and rationale
- Trade-offs made and lessons learned
- Patterns that worked well
- Patterns that caused problems

### Step 5: Ask Technical Clarifying Questions (MANDATORY)

**🚨 BEFORE writing the technical design, you MUST ask clarifying questions
using the AskUserQuestion tool.** Adapt questions based on the feature, but
common technical areas to explore:

- **Architecture Pattern:** "What architectural pattern should this follow?"
- **Technology Stack:** "Are there specific technologies or libraries that must
  be used?"
- **Integration Points:** "What existing systems will this feature integrate
  with?"
- **Data Storage:** "What are the data storage requirements?"
- **Performance Constraints:** "Are there specific performance requirements?"
- **External Dependencies:** "Does this feature depend on external services?"
- **Error Handling:** "What error handling and recovery strategies should be
  used?"
- **State Management:** "How should state be managed?"

**Architecture Trade-offs (informed by RLM findings from Steps 2-3):**
- "I found patterns [X] and [Y] in the codebase. Which should this feature
  follow?"
- "Existing [component] uses [approach]. Should we extend it or build new?"
- "Past design for [similar feature] used [pattern]. Reuse or diverge?"

Always include an **"All clear, proceed"** option for users with clear
requirements. If user selects it, skip to Step 6.

**Take the user's answers and incorporate them into the design below. Do NOT
leave answered questions in an "Open Questions" section.**

### Step 5b: Content Quality Rules

Every section must answer: "what would a developer not know
without this?" If a section reads like a user manual, it does
not belong in tech design.

**DO include:**
- Component boundaries and responsibilities
- Data contracts (interfaces/types between components)
- Communication patterns (sequence diagrams)
- Reliability/failure handling patterns
- Performance feasibility estimates
- Rejected alternatives with reasons

**DO NOT include:**
- Setup guides, workflow steps (→ README)
- CLI usage examples, sample output (→ README)
- Algorithm parameter values, thresholds (→ code)
- Installation instructions (→ README)
- User-facing documentation (→ README)

Be critical of your own output: if a section reads like a user
manual, remove it or move it to the appropriate place.

### Step 6: Synthesize Technical Design

Create design document:

```markdown
# {JIRA-ID}: {Feature Name} - Technical Design

**Status**: Draft
**PRD**: [{JIRA-ID}-prd.md](link)
**Created**: {date}

## Overview

{High-level technical approach}

## Current Architecture (RLM Analysis)

**Discovered Patterns**:
- {Pattern 1 from codebase}
- {Pattern 2 from codebase}

**Relevant Components**:
- {Component 1}: {Description + file locations}
- {Component 2}: {Description + file locations}

## Past Decisions (Claude-Mem)

**Relevant Historical Context**:
- {Decision 1 from past}: {Why it matters for this feature}
- {Decision 2}: {Lesson learned}

## Proposed Design

### Architecture

{Detailed design following discovered patterns}

**Layering**:
- UI Layer: {What we'll add/modify}
- Application Layer: {What we'll add/modify}
- Domain Layer: {What we'll add/modify}
- Infrastructure: {What we'll add/modify}

### Components

**New Components**:
1. **{Component Name}**
   - **Purpose**: {Why}
   - **Location**: {Where in codebase}
   - **Pattern**: {Following which existing pattern}
   - **Dependencies**: {What it uses}

**Modified Components**:
1. **{Existing Component}** ({file:line})
   - **Changes**: {What we'll modify}
   - **Rationale**: {Why}
   - **Risk**: {Impact assessment}

### Data Models

{New or modified data structures}

### API Design

{New endpoints, methods, or interfaces}

### Integration Points

**Connects To** (from RLM analysis):
- {System 1}: via {interface}
- {System 2}: via {method}

### Error Handling

{Following discovered patterns from codebase}

### Testing Strategy

{Based on existing test patterns}

### Verification Approach

Maps each functional requirement to its verification method and
expected evidence. This section is the primary input to `/dev:test-plan`.

| Requirement | Method | Scope | Expected Evidence |
|-------------|--------|-------|-------------------|
| FR-1: {description} | `auto-test` | unit | pytest: N passed |
| FR-2: {description} | `manual-run-claude` | integration | output shows X |
| FR-3: {description} | `code-only` | — | — |

Methods: `code-only` \| `auto-test` \| `manual-run-claude` \|
`manual-run-user` \| `docker` \| `e2e` \| `observation`
(canonical definitions in `/dev:test-plan`)

## Trade-offs

**Considered Approaches**:
1. **Option A**: {Description}
   - Pros: {Benefits}
   - Cons: {Drawbacks}
   - Historical context: {From claude-mem}

2. **Option B (Recommended)**: {Description}
   - Pros: {Benefits}
   - Cons: {Drawbacks}
   - Why recommended: {Rationale based on RLM + mem}

## Implementation Constraints

**From Existing Architecture** (RLM):
- {Constraint 1}
- {Constraint 2}

**From Past Experience** (Claude-Mem):
- {Lesson 1}
- {Lesson 2}

## Files to Create/Modify

**Create**:
- `{path/to/new/file.ext}` - {Purpose}

**Modify**:
- `{path/to/existing/file.ext:line}` - {Changes}

## Dependencies

**External**:
- {Library 1}: {Version, why}

**Internal**:
- {Module 1}: {How we'll use it}

## Security Considerations

{Security requirements and mitigations}

## Performance Considerations

{Performance requirements and optimizations}

## Rollback Plan

{How to revert if issues arise}

## References

### Code (RLM):
- {File 1}: {Relevant pattern}
- {File 2}: {Example to follow}

### History (Claude-Mem):
- {Past design}: {What to learn}

---

**Next Steps**:
1. Review and approve design
2. Run `/dev:tasks` for task breakdown
```

### Step 7: Save to File

```
tasks/{jira-id}-{feature}/{date}-{jira-id}-{feature}-tech-design.md
```

After writing, **Read the file back** — the PostToolUse hook captures it
as a claude-mem observation automatically. No explicit save call needed.

## Context7

When referencing any library, framework, or external API — use the Context7 MCP to look up current documentation rather than guessing. Call `mcp__context7__resolve-library-id` then `mcp__context7__get-library-docs`. Never invent API signatures or assume version-specific behaviour.

## Final Instructions

1. Load PRD and search past designs
2. Use RLM to discover existing patterns
3. Identify integration points via RLM
4. Learn from historical decisions via claude-mem
5. **🚨 MANDATORY: Ask technical clarifying questions using AskUserQuestion tool**
6. Synthesize design incorporating user's answers + RLM + claude-mem insights
7. Save to both systems
8. Suggest `/dev:tasks` as next step
