# Release Loop Skill — Design Spec

_Created 2026-07-11. Updated 2026-07-11 (advisor review: fidelity tier, non-TDD path, resume durability, dogfood target)._

> **Status (2026-07-20): Migrated.** The implementation described below was
> moved to the `compound-loop` project and removed from this repository. The
> paths and slash commands in this document describe the historical
> EntireContext implementation; fresh checkouts should install or invoke the
> canonical `release-loop` skill from `compound-loop`. Existing
> `.release-loop/progress.md` files remain durable handoff artifacts that the
> migrated orchestrator can resume.

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
    design-phase.md           # brainstorming + spec protocol (~200-400 lines)
    plan-phase.md             # implementation plan writing guide (~200-300 lines)
    implement-phase.md        # subagent dispatch + review protocol (~300-400 lines)
    review-phase.md           # branch review + fix dispatch (~150-200 lines)
    ship-phase.md             # PR creation + auto-fix loop (~150-200 lines)
    retro-phase.md            # retrospective protocol (~150-200 lines)
```

### Reference File Fidelity

Each reference is a **high-fidelity distillation** — not a thin checklist and not a full reproduction of superpowers internals. Each file contains:

- The phase's **protocol** (step-by-step with decision points)
- **Prompt templates** for subagent dispatch (implementer, reviewer, fixer)
- **Model selection guidance** (when to use cheap vs capable models)
- **Status handling** (DONE, BLOCKED, NEEDS_CONTEXT flows)
- **Completion criteria** (what "done" means for this phase)

Target: 200-400 lines per file. Enough to reproduce this session's quality without importing external skills. The distillation extracts the load-bearing rules and drops the process narration.

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
**Deliverable type detection**: if the spec describes code changes → **code path**; if docs/skills/config only → **non-code path**.

**Code path actions**:
1. File structure derivation from spec
2. Task decomposition (each independently testable)
3. Per-task steps (TDD: failing test → implement → verify → commit)
4. Plan self-review (spec coverage, placeholder scan, type consistency)
5. Plan file committed

**Non-code path actions**:
1. Deliverable inventory (which files to create/modify)
2. Task decomposition (each produces a reviewable artifact)
3. Per-task steps (write → self-review → commit)
4. Verification criteria (inspection-based, not test-based)
5. Plan file committed

**Exit**: plan file committed
**Gate**: AUTO

### Phase 3: Implement

**Entry**: plan file path
**Actions**:
1. Feature branch creation (or verify existing)
2. Per-task subagent dispatch (fresh context each)
3. Per-task review (spec compliance + quality)
4. Fix dispatch for Critical/Important findings
5. Progress ledger tracking

**Code tasks**: subagent follows TDD, runs test suite before commit.
**Non-code tasks**: subagent writes deliverable, self-reviews against spec, commits.

**Exit**: all tasks complete; for code tasks, full test suite passes
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
5. Review comments → fix + respond (max 4 rounds, then batch remaining)
6. Merge

**Exit**: PR merged
**Gate**: USER for merge (AUTO mode: CI pass + no open Critical → auto-merge)

### Phase 6: Retro

**Entry**: PR merged
**Actions**:
1. Collect release data:
   - Code delta (product / test / docs split)
   - Test count (new + total)
   - Review rounds + comment count (fixed / deferred)
   - CI failure count
   - Time from start to merge
2. Check carry-forward items from previous retro
3. Derive findings (each with **Why** + **How to apply**):
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

File: `.release-loop/progress.md` (**tracked in git** — survives `git clean -fdx` and context compaction)

```markdown
# Release Loop Progress
Phase: implement
Feature: Git Archaeology v0.13.0
Branch: docs/v0.13.0-design
Base: eccd70b
Spec: docs/superpowers/specs/2026-07-11-v0.13.0-git-archaeology-design.md
Plan: docs/superpowers/plans/2026-07-11-v0.13.0-git-archaeology.md
Tasks: 3/5 complete
DeliverableType: code
```

On resume, read this file and continue from the recorded phase/task. Progress updates are committed alongside task work (not separate commits).

**Why tracked**: gitignored state dies on `git clean -fdx`. Cross-session resume is a headline feature — the state must be durable. The file is small (< 10 lines) and changes infrequently.

## Failure Handling

- Any phase can be interrupted — state is saved to progress.md
- `/release-loop resume` reads progress.md and continues
- Within a phase: retry logic (3 attempts) → escalate to user
- Review fix rounds capped at 3; Ship review-comment rounds capped at 4
- CI fix attempts capped at 3

## Auto Mode

`/release-loop --auto <feature>`: all gates auto except Design (spec always needs human approval). Ship auto-merges when CI passes and no Critical review comments.

## Supported Flags

- `--auto` — minimize human gates (Design gate remains)
- `--skip-design` — start from Plan phase when spec already exists; requires `--spec <path>`
- `--skip-plan` — start from Implement phase when plan already exists; requires `--plan <path>`

## Non-Goals

- IDE integration or UI
- Multi-PR orchestration (one feature = one PR)
- Release tagging / PyPI publishing (separate concern)
- Team coordination (single-developer workflow)

## Success Criteria

- A single `/release-loop` invocation drives a feature from description to merged PR + retro
- Resume works across sessions (progress.md survives context compaction and `git clean`)
- Each phase produces a durable artifact (spec, plan, commits, PR, retro doc)
- No external skill dependencies — works with vanilla Claude Code + git
- **Dogfood validation**: validated by driving EntireContext v0.14.0 `decision_commits` linkage feature (a real code change from v0.13.0 carry-forward) through the full loop

## Resolved Questions

1. **Retro auto-tag**: No — tagging is a separate release concern. Retro only produces a document.
2. **progress.md location**: Tracked in git (`.release-loop/progress.md`) — durability over cleanliness.
3. **`--skip-phase`**: Supported via `--skip-design` and `--skip-plan` flags with required path arguments.
4. **Reference fidelity**: High-fidelity distillation (200-400 lines per phase). Not thin checklists, not full superpowers reproduction.
5. **Non-code deliverables**: Plan and Implement phases have dual paths (code: TDD, non-code: deliverable + inspection). Deliverable type auto-detected from spec content.
