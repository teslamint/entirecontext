# Release Loop Skill — Design Spec

_Created 2026-07-11. Derived from v0.13.0 session process observations._

## Overview

A self-contained orchestrator skill that drives a feature from idea to merged PR to retrospective. No external skill dependencies — works in any Claude Code project with git.

## Trigger

`/release-loop <feature description>` or `release-loop` keyword.
`/release-loop resume` to continue from last saved state.

## Skill Structure

```
skills/release-loop/
  SKILL.md                    # orchestrator: phase transitions, state, gates
  references/
    design-phase.md           # brainstorming + spec checklist
    plan-phase.md             # implementation plan writing guide
    implement-phase.md        # subagent-driven implementation protocol
    review-phase.md           # branch review + fix dispatch
    ship-phase.md             # PR creation + auto-fix loop
    retro-phase.md            # retrospective protocol
```

## Phase Definitions

### Phase 1: Design

**Entry**: user provides feature requirement
**Actions**:
1. Explore project context (git log, related files, existing docs)
2. Clarifying questions (scope, constraints, success criteria)
3. 2-3 approaches with tradeoffs + recommendation
4. Design sections presented for review
5. Spec document written + advisor/reviewer check
6. Spec committed

**Exit**: spec file committed + user approved
**Gate**: USER (never auto-skip — spec approval is always human)

### Phase 2: Plan

**Entry**: approved spec file path
**Actions**:
1. File structure derivation from spec
2. Task decomposition (each independently testable)
3. Per-task steps (TDD: failing test → implement → verify → commit)
4. Plan self-review (spec coverage, placeholder scan, type consistency)
5. Plan file committed

**Exit**: plan file committed
**Gate**: AUTO

### Phase 3: Implement

**Entry**: plan file path
**Actions**:
1. Feature branch creation
2. Per-task subagent dispatch (fresh context each)
3. Per-task review (spec compliance + code quality)
4. Fix dispatch for Critical/Important findings
5. Progress ledger tracking

**Exit**: all tasks complete, full test suite passes
**Gate**: AUTO

### Phase 4: Review

**Entry**: all implementation tasks complete
**Actions**:
1. Generate merge-base..HEAD diff
2. Final branch review (most capable model)
3. Critical/Important findings → fix subagent
4. Re-review after fixes (max 3 rounds)

**Exit**: review clean or only Minor findings remain after 3 rounds
**Gate**: AUTO

### Phase 5: Ship

**Entry**: review clean
**Actions**:
1. Push to remote
2. Create PR (auto-generated title + body)
3. Check CI status
4. CI failure → auto-fix + push (max 3 attempts)
5. Review comments → fix + respond (max 4 rounds, then batch)
6. Merge

**Exit**: PR merged
**Gate**: USER for merge (AUTO mode: CI pass + no open Critical → auto-merge)

### Phase 6: Retro

**Entry**: PR merged
**Actions**:
1. Collect release data:
   - Code delta (product / test / docs split)
   - Test count
   - Review rounds + comment count
   - CI failure count
   - Time from start to merge
2. Check carry-forward items from previous retro
3. Derive findings (each with Why + How to apply):
   - What worked well
   - What to improve
   - Process observations
4. Register carry-forward items
5. Record lessons
6. Commit retro document

**Exit**: retro document committed
**Gate**: AUTO

## Phase Transition Table

| From → To | Condition | Gate |
|-----------|-----------|------|
| Design → Plan | spec committed + user approved | USER |
| Plan → Implement | plan committed | AUTO |
| Implement → Review | all tasks complete | AUTO |
| Review → Ship | review clean | AUTO |
| Ship → Retro | PR merged | AUTO |
| Retro → Done | retro committed | AUTO |

## State Tracking

File: `.release-loop/progress.md` (gitignored)

```markdown
# Release Loop Progress
Phase: implement
Feature: Git Archaeology v0.13.0
Branch: docs/v0.13.0-design
Base: eccd70b
Spec: docs/superpowers/specs/2026-07-11-v0.13.0-git-archaeology-design.md
Plan: docs/superpowers/plans/2026-07-11-v0.13.0-git-archaeology.md
Tasks: 3/5 complete
```

On resume, read this file and continue from the recorded phase/task.

## Failure Handling

- Any phase can be interrupted — state is saved to progress.md
- `/release-loop resume` reads progress.md and continues
- Within a phase: retry logic (3 attempts) → escalate to user
- Review fix rounds capped at 3; Ship review-comment rounds capped at 4
- CI fix attempts capped at 3

## Auto Mode

`/release-loop --auto <feature>`: all gates auto-except Design (spec always needs human approval). Ship auto-merges when CI passes and no Critical review comments.

## Non-Goals

- IDE integration or UI
- Multi-PR orchestration (one feature = one PR)
- Release tagging / PyPI publishing (separate concern)
- Team coordination (single-developer workflow)

## Success Criteria

- A single `/release-loop` invocation drives a feature from description to merged PR + retro
- Resume works across sessions (progress.md survives context compaction)
- Each phase produces a durable artifact (spec, plan, commits, PR, retro doc)
- No external skill dependencies — works with vanilla Claude Code + git

## Open Questions

1. Should the retro phase auto-create a git tag for the release, or leave that to a separate release skill?
2. Should progress.md be gitignored or tracked? (gitignored = private scratch; tracked = team visibility)
3. Should the skill support `--skip-phase design` for cases where spec already exists?
