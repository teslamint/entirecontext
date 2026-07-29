---
schema: plan/v1
title: Consolidate PR enrichment state transitions
type: refactor
status: draft
date: 2026-07-29
execution: code
origin: docs/specs/2026-07-29-consolidate-pr-enrichment-state-design.md
---

# Consolidate PR Enrichment State Transitions Plan

## Goal

Centralize four duplicated PR enrichment state-transition sites in `archaeology.py` into two methods on `_ProcessingState` and one new `_CommitAction` dataclass, preserving all four observable per-commit outcome branches (A-D from the spec's outcome table) with their distinct counter, DB, and callback side effects.

## Architecture Notes

- `_CommitAction` is a frozen dataclass in `archaeology.py`, not a new module. It holds `needs_patch` and `needs_pr` with `skip` and `pr_only` properties.
- `_ProcessingState.action(pr_bodies)` is the single source of truth for what a commit needs. Token availability is NOT folded into `needs_pr` — it stays a caller concern, preserving the distinct Branch B (tokenless PR-only with callback) behavior.
- `_ProcessingState.resolve_pr_completion(pr_fetch, parsed_ok)` is the single source of truth for whether `pr_body_processed` should be set true, replacing the inline `pr_complete` boolean.
- `_is_processed()` stays unchanged — it delegates to `_get_processing_state().patch_processed` and is not part of this refactor.
- Known Pattern: the v0.14.0 retro (Finding 2) established the conservation invariant: "every selected commit lands in exactly one terminal or retryable bucket." Characterization tests must assert this invariant before the refactor begins.

## Assumption Recheck

Origin spec retains no live assumptions with retained commands; no assumption recheck required. The spec's equivalence claim about `needs_pr` guard redundancy is verified by code inspection: `pr_fetch` is non-None only when `needs_pr and token and consecutive_failures < threshold` (line 531), so checking `pr_fetch is not None` implies `needs_pr` was true.

## File Structure

- Modify `src/entirecontext/core/archaeology.py` — add `_CommitAction`, add `action()` and `resolve_pr_completion()` to `_ProcessingState`, refactor `archaeologize()` and `_process_batch()`.
- Modify `tests/test_archaeology_integration.py` — add characterization tests for the four outcome branches.
- Modify `tests/test_archaeology.py` — add unit tests for `_CommitAction`, `action()`, `resolve_pr_completion()`.

## Carry-forward Trigger Audit

Open ROADMAP items examined at `28799ba`:

| Row | Trigger class | File overlap | Fired? | Disposition |
|-----|--------------|-------------|--------|-------------|
| Consolidate PR enrichment state transitions (v0.14.0, line 337) | edit-based: "when archaeology is next modified" | `archaeology.py` ∈ planned files | **fired** | This plan IS that item |
| Consolidate PR enrichment state transitions (v0.15.0, line 358) | edit-based: "when that code is next modified" | `archaeology.py` ∈ planned files | **fired** | Duplicate of above; both close with this plan |
| General Git C-style path escapes (lines 338, 359) | event-based: "if real repositories surface them" | `archaeology.py` ∈ planned but `_decode_git_quoted_path` not touched | not fired | Not relevant — no path decoding changes in this plan |
| Post-squash archaeology convergence (line 354) | event-based: "with explicit repository-content export authorization" | `archaeology.py` ∈ planned but no export work | not fired | Not relevant |
| TQL --until semantic/global (lines 355-356) | edit-based: names search paths | No file overlap | not fired | Not relevant |
| Maturity 75 dogfooding (lines 336, 357) | drift-based: measurement | No file overlap | not fired | Not relevant |

Attestation: all open ROADMAP items at `28799ba` examined. Two fired (both name this exact consolidation); both are resolved by this plan. No fired trigger is left without disposition.

## Scenario Coverage Map

The spec has no User Scenarios section (it is a pure refactor with no new user-facing behavior). Coverage is defined by preservation of the four-branch outcome table.

| Scenario | Ordered unit chain | Scenario evidence |
|----------|-------------------|-------------------|
| Branch A: fully processed → skip, no callback | U1 characterization, then U3 preservation | `test_branch_a_fully_processed_skip` |
| Branch B: tokenless PR-only → skip + callback | U1 characterization, then U3 preservation | `test_branch_b_tokenless_pr_only_skip_with_callback` |
| Branch C: patch-done + PR EMPTY → terminal, DB write, no extraction | U1 characterization, then U3 preservation | `test_branch_c_patch_done_pr_empty_terminal` |
| Branch D: patch-done + PR FAILURE → retryable, no counter | U1 characterization, then U3 preservation | `test_branch_d_patch_done_pr_failure_retryable` |
| Dry-run PR enrichment pending count | U3 preservation | Existing `test_archaeology_cli.py:134` |

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Implementation Units

### U1: Characterization tests for four outcome branches

Execution note: test-first — these tests must pass on current `main` code before any refactoring begins.

**Goal**: Lock the four-branch outcome table's observable side effects against current code, so the refactor in U3 has a regression net.

**Files**: `tests/test_archaeology_integration.py`

**Key Technical Decisions**: None — the tests assert current behavior, not new behavior.

**Consumes**: `archaeologize()`, `_mark_processed()`, `_PrBodyFetch`, `_PrBodyStatus` from `archaeology.py`.

**Produces**: Four test functions that each assert the exact side-effect tuple `(commits_skipped, commits_processed, callback_call_count, archaeology_processed_rows)`.

**Environment isolation**: All four tests use a single-commit fixture (one commit created, `limit=1`) to avoid interaction from other `arch_repo` commits. Branches C and D monkeypatch `entirecontext.core.archaeology._get_github_token` to return a fixed fake string (`"fake-token-for-test"`), and monkeypatch `entirecontext.core.archaeology._fetch_pr_body` to the desired `_PrBodyFetch` result. Branch C additionally patches `entirecontext.core.archaeology.run_extraction` to assert it is NOT called (EMPTY bypasses extraction). Branch B monkeypatches `_get_github_token` → `None`.

**Test Scenarios**:

Happy:
- `test_branch_a_fully_processed_skip`: pre-mark a commit as fully processed (patch + PR body), run `archaeologize(pr_bodies=True, limit=1)`, assert `commits_skipped=1, commits_processed=0`, callback call count = 0, no new DB rows.
- `test_branch_b_tokenless_pr_only_skip_with_callback`: pre-mark a commit as patch-processed but not PR-processed, monkeypatch `_get_github_token` → `None`, run `archaeologize(pr_bodies=True, limit=1)` with `progress_callback`, assert `commits_skipped=1, commits_processed=0`, callback called exactly once.

Edge:
- `test_branch_c_patch_done_pr_empty_terminal`: pre-mark a commit as patch-processed, monkeypatch `_get_github_token` → `"fake-token-for-test"`, monkeypatch `_fetch_pr_body` → `_PrBodyFetch(EMPTY)`, monkeypatch `run_extraction` → assert not called, run `archaeologize(pr_bodies=True, limit=1)`, assert `commits_skipped=0, commits_processed=1`, `archaeology_processed.pr_body_processed=1`.
- `test_branch_d_patch_done_pr_failure_retryable`: pre-mark a commit as patch-processed, monkeypatch `_get_github_token` → `"fake-token-for-test"`, monkeypatch `_fetch_pr_body` → `_PrBodyFetch(FAILURE, warning="test failure")`, run `archaeologize(pr_bodies=True, limit=1)`, assert `commits_skipped=0, commits_processed=0`, `archaeology_processed.pr_body_processed=0` unchanged.

**Acceptance**: All four tests pass on current `main` code before any U2/U3 changes land. Record the test output at the U1 commit as pre-refactor preservation evidence. Run: `pytest tests/test_archaeology_integration.py -v -k "branch_a or branch_b or branch_c or branch_d"`

### U2: Add `_CommitAction` dataclass and `_ProcessingState` methods

Execution note: code-first — add the new types and methods without changing any callers yet.

**Goal**: Introduce `_CommitAction`, `_ProcessingState.action()`, and `_ProcessingState.resolve_pr_completion()` alongside the existing code, without modifying any call sites.

**Files**: `src/entirecontext/core/archaeology.py`, `tests/test_archaeology.py`

**Key Technical Decisions**:
- `_CommitAction` placed immediately after `_ProcessingState` definition (after line 133).
- `action()` and `resolve_pr_completion()` are methods on `_ProcessingState`, not standalone functions, because they derive from state fields.
- `resolve_pr_completion` accepts `pr_fetch: _PrBodyFetch | None` and `parsed_ok: bool`. It returns True when `pr_fetch is not None and (pr_fetch.status is EMPTY or (pr_fetch.status is FOUND and parsed_ok))`. The `needs_pr` guard is intentionally dropped because `pr_fetch` being non-None already implies `needs_pr` was true (see Architecture Notes).

**Consumes**: `_PrBodyFetch`, `_PrBodyStatus` (existing types in same module).

**Produces**: `_CommitAction` dataclass, `_ProcessingState.action()`, `_ProcessingState.resolve_pr_completion()`.

**Test Scenarios**:

Happy:
- `test_action_fresh_state_pr_bodies_true`: `_ProcessingState().action(True)` → `_CommitAction(needs_patch=True, needs_pr=True)`, `skip=False`, `pr_only=False`
- `test_action_fresh_state_pr_bodies_false`: `_ProcessingState().action(False)` → `_CommitAction(needs_patch=True, needs_pr=False)`, `skip=False`

Edge:
- `test_action_patch_done_pr_bodies_true`: `_ProcessingState(patch_processed=True).action(True)` → `_CommitAction(needs_patch=False, needs_pr=True)`, `skip=False`, `pr_only=True`
- `test_action_fully_done`: `_ProcessingState(patch_processed=True, pr_body_processed=True).action(True)` → skip=True, pr_only=False
- `test_resolve_pr_completion_found_parsed`: `resolve_pr_completion(_PrBodyFetch(FOUND, body="x"), True)` → True
- `test_resolve_pr_completion_found_unparsed`: `resolve_pr_completion(_PrBodyFetch(FOUND, body="x"), False)` → False
- `test_resolve_pr_completion_empty`: `resolve_pr_completion(_PrBodyFetch(EMPTY), False)` → True
- `test_resolve_pr_completion_failure`: `resolve_pr_completion(_PrBodyFetch(FAILURE), False)` → False
- `test_resolve_pr_completion_none`: `resolve_pr_completion(None, True)` → False

**Acceptance**: New unit tests pass, all existing archaeology tests still pass. Run: `pytest tests/test_archaeology.py tests/test_archaeology_integration.py tests/test_archaeology_streaming.py tests/test_archaeology_cli.py tests/test_migration_v017.py -v`

### U3: Refactor callers to use new abstractions

Execution note: refactor — replace duplicated logic with calls to new methods.

**Goal**: Replace the four duplication sites in `archaeologize()` and `_process_batch()` with `action()` and `resolve_pr_completion()`. All existing tests (including U1 characterization) must pass unchanged.

**Files**: `src/entirecontext/core/archaeology.py`

**Key Technical Decisions**:
- Batch tuple changes from `(sha, message, patch_text, _ProcessingState)` to `(sha, message, patch_text, _ProcessingState, _CommitAction)`. The `_process_batch` signature's `batch` type annotation updates accordingly. `pr_bodies` kwarg is removed from `_process_batch` since `_CommitAction` already encodes `needs_pr`.
- In `archaeologize()` live path (lines 449-467): replace `needs_patch`/`needs_pr` computation with `act = state.action(pr_bodies)`. Branch A uses `act.skip`, Branch B uses `act.pr_only and not token`. Both retain their distinct side effects.
- In `_process_batch()` per-commit loop: unpack `act` from the batch tuple. Replace lines 528-529 with `act.needs_patch`/`act.needs_pr`. Replace lines 543-546 (Branch C) with `if act.pr_only and state.resolve_pr_completion(pr_fetch, False):` — this adds an `act.needs_pr` guard that the original `not needs_patch` check didn't have, but it's equivalent because line 531 makes `pr_fetch` non-None only when `needs_pr` was true (same equivalence argued in Architecture Notes). Replace line 549 (Branch D) with `if not act.needs_patch and not pr_body: continue`. Replace lines 568-578 (`pr_complete`) with `pr_body_processed=state.resolve_pr_completion(pr_fetch, outcome.parsed_ok)`.
- In `archaeologize()` dry-run path (lines 408-444): replace with `act = state.action(pr_bodies)`. Use `not act.needs_patch` for `already_processed` counting, `act.needs_patch` for `patch_pending`. Use `act.pr_only` for `pr_enrichment_pending` — this is equivalent to the current `pr_bodies and state.patch_processed and not state.pr_body_processed` since `action()` doesn't take a token, and `pr_only = not needs_patch and needs_pr = patch_processed and (pr_bodies and not pr_body_processed)`. The pre-migration `OperationalError` guard stays unchanged.
- Branch C note: `state.resolve_pr_completion(pr_fetch, False)` with `parsed_ok=False` is correct for the EMPTY early-exit path because EMPTY returns True regardless of `parsed_ok`. FAILURE with `parsed_ok=False` returns False, so Branch D falls through correctly.

**Consumes**: `_CommitAction`, `_ProcessingState.action()`, `_ProcessingState.resolve_pr_completion()` from U2.

**Produces**: Refactored `archaeologize()` and `_process_batch()` with centralized state-transition logic.

**Test Scenarios**:

Integration:
- All four U1 characterization tests pass unchanged (Branch A-D preservation). Covers Branch A, B, C, D.
- All existing `test_archaeology_integration.py` tests pass unchanged.
- All existing `test_archaeology_streaming.py` tests pass unchanged.
- All `test_archaeology_cli.py` tests pass unchanged (including line 134 PR enrichment pending count).
- All `test_migration_v017.py` tests pass unchanged.

**Acceptance**: Full archaeology test suite green. Run: `pytest tests/test_archaeology*.py tests/test_migration_v017.py -v`. Then verify deduplication: `grep -c "not state\.patch_processed\|not state\.pr_body_processed" src/entirecontext/core/archaeology.py` should return 0 (these expressions now live inside `action()` as `self.` references). `grep -c "pr_complete" src/entirecontext/core/archaeology.py` should return 0.

## Risks & Dependencies

- **Risk**: Branch C's `resolve_pr_completion(pr_fetch, False)` passing `parsed_ok=False` could be confusing to future readers. **Mitigation**: the `resolve_pr_completion` method itself is self-documenting — EMPTY status short-circuits before checking `parsed_ok`.
- **Dependency**: U3 depends on U1 and U2. U1 and U2 are independent of each other.

## Open Unknowns

**Implementation-time**:
- Exact dry-run path restructuring — the `OperationalError` guard wraps the entire state lookup; the `action()` call must stay inside the same try/except block.

## Deferred to Follow-Up Work

- General Git C-style path escapes (ROADMAP P4) — `_decode_git_quoted_path` is not touched by this refactor.
- Post-squash archaeology convergence (ROADMAP P3) — requires explicit export authorization, orthogonal to this change.
