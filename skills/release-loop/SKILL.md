---
name: release-loop
description: "Drive a feature from idea to merged PR to retrospective. Six phases: Design → Plan → Implement → Review → Ship → Retro. Use /release-loop <feature> to start, /release-loop resume to continue."
---

# Release Loop

Drive a feature through six phases — from idea to merged PR to retrospective — in a single orchestrated loop. Self-contained: works with vanilla Claude Code + git. No external skill dependencies.

## Install

The skill lives in `skills/release-loop/`. To make it invocable via `/release-loop`:

```bash
ln -s ../../skills/release-loop .claude/skills/release-loop
```

## Trigger

- `/release-loop <feature description>` — start a new loop
- `/release-loop resume` — continue from saved state
- `release-loop` keyword in conversation

## Flags

| Flag | Effect |
|------|--------|
| `--auto` | Minimize human gates (Design gate remains — spec always needs human approval) |
| `--skip-design` | Start from Plan; requires `--spec <path>` |
| `--skip-plan` | Start from Implement; requires `--plan <path>` |

## Phases

| # | Phase | Gate | Reference |
|---|-------|------|-----------|
| 1 | Design | USER | [design-phase.md](references/design-phase.md) |
| 2 | Plan | AUTO | [plan-phase.md](references/plan-phase.md) |
| 3 | Implement | AUTO | [implement-phase.md](references/implement-phase.md) |
| 4 | Review | AUTO | [review-phase.md](references/review-phase.md) |
| 5 | Ship | USER (AUTO with `--auto` when CI passes + no Critical comments) | [ship-phase.md](references/ship-phase.md) |
| 6 | Retro | AUTO | [retro-phase.md](references/retro-phase.md) |

## Phase Transition Table

| From → To | Condition | Gate |
|-----------|-----------|------|
| Design → Plan | spec committed + user approved | USER |
| Plan → Implement | plan committed | AUTO |
| Implement → Review | all tasks complete | AUTO |
| Review → Ship | review clean (no Critical/Important) | AUTO |
| Ship → Retro | PR merged | AUTO |
| Retro → Done | retro committed | AUTO |

## Orchestrator Protocol

### Starting a New Loop

1. Parse flags (`--auto`, `--skip-design`, `--skip-plan`)
2. Detect the base branch:
   ```bash
   BASE_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|origin/||' || echo main)
   ```
3. Check for existing `.release-loop/progress.md` — warn if present
4. Create feature branch from current HEAD (unless `--skip-*` with existing branch)
5. Record initial state in `.release-loop/progress.md` (include `BaseBranch: $BASE_BRANCH`)
6. Enter the first applicable phase

### Resuming

1. Read `.release-loop/progress.md`
2. Verify branch exists and is checked out
3. Resume at the recorded phase and task
4. Trust the progress file and `git log` over conversation memory

### Phase Execution

For each phase:

1. Read the phase's reference file (`references/<phase>-phase.md`)
2. Follow the protocol defined there
3. On completion, check the exit condition
4. If gate is USER: present results, wait for approval
5. If gate is AUTO: verify exit condition, advance immediately
6. Update `.release-loop/progress.md` with new phase

### Completion Rule

The release loop is complete ONLY when Retro phase finishes and the retro document is committed. Ship phase (merge + tag) is NOT the end — always advance to Retro immediately. Never report "release done" or "release loop complete" before Retro is committed.

### Failure Handling

- Any phase can be interrupted — state is saved to `progress.md`
- Within a phase: retry logic (3 attempts) → escalate to user
- Review fix rounds capped at 3
- Ship review-comment rounds capped at 4
- CI fix attempts capped at 3

## State Tracking

File: `.release-loop/progress.md` — **tracked in git** (survives `git clean -fdx` and context compaction).

Format:

```markdown
# Release Loop Progress
Phase: <design|plan|implement|review|ship|retro>
Feature: <feature description>
Branch: <branch name>
Base: <base commit SHA>
BaseBranch: <main|master|develop|...>
Spec: <path to spec file, if exists>
Plan: <path to plan file, if exists>
PR: <PR number, if created>
Tasks: <completed>/<total> complete
DeliverableType: <code|non-code>
MinorFindings: <list of minor findings from task reviews, if any>
```

Progress updates are committed alongside task work (not separate commits).

**Gitignore split:** Only `progress.md` is tracked. Scratch directories are gitignored:

```gitignore
# .release-loop/.gitignore
briefs/
reports/
reviews/
```

Create this `.gitignore` when initializing the `.release-loop/` directory.

## Deliverable Type Detection

The Plan phase auto-detects deliverable type from spec content:

- **Code**: spec describes source code changes, new modules, API changes, schema migrations
- **Non-code**: spec describes documentation, skill files, config, markdown-only deliverables

This determines which protocol the Implement phase follows (TDD vs write-review-commit).

## Model Selection

Use the least capable model that handles each role:

| Role | Model tier |
|------|-----------|
| Mechanical implementation (clear spec, 1-2 files) | cheapest available |
| Integration tasks (multi-file, pattern matching) | standard |
| Architecture/design decisions | most capable |
| Final branch review | most capable |
| Task review (small diff) | standard |
| Task review (complex/risky diff) | most capable |

Always specify the model explicitly when dispatching subagents.

## Non-Goals

- IDE integration or UI
- Multi-PR orchestration (one feature = one PR)
- Release tagging / PyPI publishing (separate concern)
- Team coordination (single-developer workflow)
