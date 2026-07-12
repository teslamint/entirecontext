# Design Phase

Turn a feature idea into an approved, committed spec through collaborative dialogue.

## Entry Condition

User provides a feature requirement (via `$release-loop <feature>` in Codex, `/release-loop <feature>` in Claude Code, or `--skip-design` is NOT set).

## Exit Condition

Spec file committed to git + user approved.

## Gate

USER — spec approval is always human. Never auto-skip this gate.

## Protocol

### Step 1: Explore Project Context

Before asking any questions, build situational awareness:

```
1. git log --oneline -20           # recent work
2. Read AGENTS.md/CLAUDE.md and ROADMAP.md  # agent instructions + direction
3. Check related files/modules     # existing patterns to follow
4. Check previous retro files      # carry-forward items that may apply
```

Look for:
- Carry-forward items from the last retrospective that relate to this feature
- Existing patterns the design should follow
- Recent changes that constrain the design space

### Step 2: Scope Check

Assess whether the feature is a single deliverable or needs decomposition.

**Decomposition signals:**
- Multiple independent subsystems
- Different teams/owners for different parts
- Parts that could ship independently

If decomposition is needed, help the user break it into sub-projects first. Each sub-project gets its own release-loop cycle.

### Step 3: Clarifying Questions

Ask questions **one at a time** to refine the idea:

- Purpose and motivation (why build this?)
- Constraints (performance, compatibility, dependencies)
- Success criteria (how do we know it works?)
- Scope boundaries (what's explicitly out?)

**Question style:**
- Prefer multiple choice when possible — easier to answer
- One question per message
- Focus on decisions that affect architecture, not cosmetic details
- Front-load questions that might change the approach entirely

### Step 4: Propose Approaches

Present 2-3 approaches with tradeoffs:

```markdown
**Approach A: [Name]**
- How: [brief description]
- Pro: [main advantage]
- Con: [main disadvantage]

**Approach B: [Name]**
- How: [brief description]
- Pro: [main advantage]
- Con: [main disadvantage]

**Recommendation:** Approach A because [reason].
```

Lead with your recommendation and explain why. The user redirects if they disagree.

### Step 5: Present Design

Once the approach is chosen, present the design in sections scaled to complexity:

- A few sentences for straightforward parts
- Up to 200-300 words for nuanced parts
- Ask after each section whether it looks right

Cover these areas (skip any that don't apply):

1. **Architecture** — module structure, data flow, key abstractions
2. **Interface** — public API, CLI flags, config options
3. **Data model** — schema changes, storage format
4. **Integration** — how it connects to existing code
5. **Testing** — what to test, testing strategy
6. **Risks** — what could go wrong, mitigations

### Step 6: Get Independent Review

Before committing the spec, get a review from a fresh perspective:

- Dispatch a reviewer subagent (most capable model) with the spec content
- Or use the `advisor` tool if the harness provides one
- Focus the review on: internal consistency, missing edge cases, scope creep, feasibility

**From v0.13.0 retro:** Advisor/reviewer caught 2 critical design flaws that self-review missed — a pipeline fork risk and missing FTS trigger rebuild. Independent review before implementation is mandatory for features with schema changes or pipeline modifications.

### Step 7: Write Spec Document

Save to: `docs/specs/YYYY-MM-DD-<feature-name>-design.md`

(Or the project's preferred spec location.)

Spec structure:

```markdown
# <Feature Name> Design

_Created YYYY-MM-DD._

## Overview
[1-3 sentences: what this builds and why]

## Scope
### In
[Bulleted list of what's included]
### Out
[Bulleted list of what's explicitly excluded]

## Architecture
[Module structure, data flow]

## [Domain-Specific Sections]
[Schema, CLI, config, etc. — whatever the feature needs]

## Testing
[Strategy, key test cases]

## Risks
[What could go wrong + mitigations]

## Open Decisions
[Anything deferred or needing user input later]
```

### Step 8: Spec Self-Review

After writing, review with fresh eyes:

1. **Placeholder scan** — any TBD, TODO, incomplete sections, vague requirements?
2. **Internal consistency** — do sections contradict each other?
3. **Scope check** — focused enough for a single implementation plan?
4. **Ambiguity check** — any requirement interpretable two ways?

Fix issues inline. No separate review pass needed.

### Step 9: User Review Gate

Present the committed spec path and ask for approval:

> "Spec written and committed to `<path>`. Review it and let me know if you want changes before we move to planning."

Wait for the user's response. Changes requested → revise and re-commit. Approved → advance to Plan phase.

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Skip straight to implementation | Always present a design first |
| Ask multiple questions at once | One question per message |
| Present only one approach | Show 2-3 with tradeoffs |
| Write a thin spec that says "see conversation" | Spec must be self-contained |
| Skip independent review for "simple" features | Every spec gets a review |
| Auto-approve the spec | USER gate — always wait for human |

## Spec Quality Signals

A good spec:
- Can be handed to someone with zero conversation context
- Has explicit scope boundaries (In/Out)
- Names concrete files, tables, functions — not just concepts
- Addresses risks and mitigations
- Has no placeholders or TODOs

A bad spec:
- References "the discussion above"
- Uses vague language ("appropriate error handling", "proper validation")
- Omits scope boundaries
- Has sections marked TBD
- Doesn't mention testing strategy
