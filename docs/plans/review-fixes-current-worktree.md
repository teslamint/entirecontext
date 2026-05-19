---
title: Stabilize Current Worktree Changes
status: active
created: 2026-05-19
origin: lfg request after code review
---

# Stabilize Current Worktree Changes

## Problem Frame

The current worktree contains post-v0.6.0 stabilization changes spanning Codex notify setup, decision ranking, decision CLI visibility, MCP repo resolution, session lifecycle ordering, generated lessons, and supporting documentation. A review found two merge-blocking behavior risks, one documentation drift issue, and one whitespace validation failure. The goal is to make the full current worktree internally consistent and merge-ready while avoiding additional feature expansion.

## Scope

In scope:
- Preserve upstream Codex `notify` state across repeated `ec enable --agent codex` runs.
- Ensure accepted outcome boost only affects decisions that already have a positive relevance signal.
- Make outcome semantics documentation match the implementation that ships in this worktree.
- Remove trailing whitespace that causes `git diff --check` to fail.
- Add focused regression tests for the two behavior fixes.
- Keep the existing rejected-alternatives CLI addition, MCP runtime cache/timeout changes, session lifecycle ordering fix, generated lessons, Serena config refresh, and proposal documents reviewable as part of this worktree.

Out of scope:
- Redesigning decision ranking beyond the accepted boost relevance gate.
- Implementing rejected-alternative normalization or audit commands beyond the already-present display command.
- Changing the MCP repo resolution cache design beyond the existing cache and timeout behavior.
- Reworking generated lesson content beyond whitespace hygiene.
- Shipping local-only artifacts such as `.omc/`, presentation binaries, or patch backups.

## Key Decisions

1. Accepted boost should be additive only after relevance is established.
   Rationale: outcome history is a quality signal, not a retrieval seed. File, assessment, diff, or commit evidence must keep owning candidate inclusion.

2. Repeated Codex enable should be idempotent with respect to preserved upstream notify.
   Rationale: `ec enable` can be run repeatedly during setup and repair. Re-running it must not destroy the command needed for a later `ec disable` restore.

3. Documentation should describe the worktree behavior being shipped.
   Rationale: a document claiming "current behavior" must not describe accepted boost as unshipped if this branch includes and tests the boost.

## Implementation Units

### Unit 1: Accepted Boost Relevance Gate

Files:
- `src/entirecontext/core/decisions.py`
- `tests/test_decisions_core.py`

Approach:
- Compute the existing relevance base from file, proximity, assessment, diff, and commit signals before applying `accepted_outcome_boost`.
- Skip candidates whose relevance base is zero.
- Add accepted boost only after the positive relevance check.
- Keep `score_breakdown["accepted_boost"]` additive and stable.

Test scenarios:
- A decision with an accepted outcome but no matching relevance signals is not returned.
- A decision with a matching file signal and accepted outcome receives the configured boost.
- The base score and final score formulas remain internally consistent.

### Unit 2: Codex Notify Re-enable Preservation

Files:
- `src/entirecontext/cli/project_cmds.py`
- `tests/test_project_cmds.py`

Approach:
- When enabling Codex notify, preserve an already-saved upstream notify command if the current user config already points at EntireContext and no new upstream command is discovered.
- Avoid overwriting saved upstream state with `None` during idempotent re-enable.
- Keep migration from repo-local notify to user-level notify intact.

Test scenarios:
- Project-local notify is migrated to the state file on first enable.
- A second enable does not erase the saved upstream notify.
- Disable after repeated enable restores the original upstream notify into `~/.codex/config.toml`.

### Unit 3: Documentation and Whitespace Hygiene

Files:
- `docs/decisions_outcomes.md`
- `LESSONS.md`

Approach:
- Update the accepted outcome row and note to describe the accepted boost as active in this change.
- Keep open questions limited to future tuning rather than whether the feature exists.
- Remove trailing whitespace from generated assessment lines.

Test scenarios:
- `git diff --check` passes.
- Outcome documentation no longer contradicts `src/entirecontext/core/decisions.py`.

### Unit 4: Existing Worktree Stabilization Surface

Files:
- `.serena/project.yml`
- `AGENTS.md`
- `CLAUDE.md`
- `src/entirecontext/cli/decisions_cmds.py`
- `src/entirecontext/hooks/session_lifecycle.py`
- `src/entirecontext/mcp/runtime.py`
- `src/entirecontext/mcp/server.py`
- `tests/conftest.py`
- `tests/test_decisions_cli.py`
- `tests/test_mcp.py`
- `tests/test_session_lifecycle_ordering.py`
- `docs/documentation_in_prs_proposal.md`
- `docs/tiered_review_policy_proposal.md`

Approach:
- Treat these as pre-existing worktree changes that must be reviewed and verified rather than silently discarded.
- Keep the changes if they pass focused tests and do not contradict the product decisions applied in this plan.
- Exclude local-only artifacts from commit/PR scope.

Test scenarios:
- MCP repo resolver tests cover cache and slow-path behavior.
- Session lifecycle ordering test proves `ended_at` persists before summary generation.
- Decision CLI test proves rejected alternatives can be displayed.
- `AGENTS.md` and `CLAUDE.md` remain consistent on the MCP restart note.

## Verification Plan

Run targeted tests:
- `uv run pytest tests/test_project_cmds.py::TestCodexIntegration tests/test_decisions_core.py::TestRankingSignals tests/test_decisions_core.py::TestRankingWeightsConfig -q`
- `git diff --check`

If those pass, run the broader previously reviewed set:
- `uv run pytest tests/test_project_cmds.py::TestCodexIntegration tests/test_decisions_core.py::TestRankingSignals tests/test_decisions_core.py::TestRankingWeightsConfig tests/test_mcp.py::TestMCPRepoResolver tests/test_session_lifecycle_ordering.py -q`

For the full worktree before commit, run:
- `uv run pytest tests/test_decisions_core.py tests/test_project_cmds.py tests/test_mcp.py tests/test_session_lifecycle_ordering.py -q`
- `uv run ruff check src/entirecontext/cli/project_cmds.py src/entirecontext/core/decisions.py src/entirecontext/hooks/session_lifecycle.py src/entirecontext/mcp/runtime.py src/entirecontext/mcp/server.py tests/test_project_cmds.py tests/test_decisions_core.py tests/test_mcp.py tests/test_session_lifecycle_ordering.py`
- `uv run ruff format --check src/entirecontext/cli/project_cmds.py src/entirecontext/core/decisions.py src/entirecontext/hooks/session_lifecycle.py src/entirecontext/mcp/runtime.py src/entirecontext/mcp/server.py tests/test_project_cmds.py tests/test_decisions_core.py tests/test_mcp.py tests/test_session_lifecycle_ordering.py`

## Risks

- The accepted boost change affects ranking output ordering. Tests should prove inclusion remains relevance-gated while existing boosted related decisions still rank correctly.
- The Codex notify state file can contain old data from previous runs. The enable logic should preserve valid upstream state only when appropriate and continue replacing it when a new non-EC upstream command is found.
