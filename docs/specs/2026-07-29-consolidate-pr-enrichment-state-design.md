---
title: Consolidate PR Enrichment State Transitions
status: draft
tier: lightweight
carry-forward-from: v0.14.0, v0.15.0
priority: P3
---

# Consolidate PR Enrichment State Transitions

## Problem

`archaeology.py` has PR enrichment state-transition logic duplicated across four sites:

1. **`archaeologize()` lines 454-459**: computes `needs_patch`/`needs_pr`, applies skip logic
2. **`_process_batch()` lines 528-529**: recomputes identical `needs_patch`/`needs_pr`
3. **`_process_batch()` lines 543-549**: PR-only completion and skip paths interleaved with fetch handling
4. **`_process_batch()` lines 568-578**: inline `pr_complete` boolean encoding completion rules

Adding a new processing dimension or changing transition rules requires coordinated edits in all four locations. The v0.14.0 retro (Finding 2) documented that locally correct state transitions can still produce globally invalid progress counts when cross-site invariants diverge.

## Outcome Table

The current code has four distinct per-commit outcomes with different side effects. The refactor must preserve all four:

| Branch | Condition | `commits_skipped` | `commits_processed` | DB write | Extraction | Callback |
|--------|-----------|-------------------|---------------------|----------|------------|----------|
| A. Fully processed | `!needs_patch && !needs_pr` | +1 | — | — | no | no |
| B. Tokenless PR-only | `!needs_patch && needs_pr && !token` | +1 | — | — | no | **yes** |
| C. Patch-done + PR EMPTY | `!needs_patch && pr_fetch.EMPTY` | — | **+1** | `_mark_processed` | **skipped** | — |
| D. Patch-done + PR FAILURE/no body | `!needs_patch && !pr_body` | — | — | — | no | — |

Branch C is a terminal success that bypasses extraction. Branch D is a deliberately retryable bucket. Both must remain distinct from skip branches A and B. The v0.14.0 retro's conservation invariant ("every selected commit lands in exactly one terminal or retryable bucket") depends on all four staying separate.

## Approach

Add one new frozen dataclass (`_CommitAction`) and two methods to `_ProcessingState`. No new modules.

### `_CommitAction` dataclass

```python
@dataclass(frozen=True)
class _CommitAction:
    needs_patch: bool
    needs_pr: bool

    @property
    def skip(self) -> bool:
        return not self.needs_patch and not self.needs_pr

    @property
    def pr_only(self) -> bool:
        return not self.needs_patch and self.needs_pr
```

`needs_pr` is purely state-derived — it does NOT fold in token availability. Token gating is a caller concern (whether to skip or enqueue), not a state property.

### `_ProcessingState.action(pr_bodies: bool) -> _CommitAction`

Computes what work this commit needs based on processing state alone:

- `needs_patch = not self.patch_processed`
- `needs_pr = pr_bodies and not self.pr_body_processed`

Token availability is NOT an input — it determines caller behavior, not action classification.

### `_ProcessingState.resolve_pr_completion(pr_fetch: _PrBodyFetch | None, parsed_ok: bool) -> bool`

Single source of truth for whether `pr_body_processed` should be set true. Returns true when:

- A fetch was attempted (`pr_fetch is not None`) AND
- Either: status is EMPTY (nothing to process) OR (status is FOUND AND extraction parsed OK)

Equivalence claim: in current code, `pr_complete` checks `needs_pr and pr_fetch is not None and ...`. Since `pr_fetch` is non-None only when `needs_pr and token and consecutive_failures < threshold`, the `needs_pr` guard is redundant with `pr_fetch is not None`. The method drops the redundant check by accepting `pr_fetch` directly.

## Changes

### `archaeologize()` loop (lines 449-467)

Before:
```python
needs_patch = not state.patch_processed
needs_pr = pr_bodies and not state.pr_body_processed
if not needs_patch and not needs_pr:
    ...skip (Branch A)...
if not needs_patch and needs_pr and not token:
    ...skip + callback (Branch B)...
```

After:
```python
act = state.action(pr_bodies)
if act.skip:
    ...skip (Branch A)...
if act.pr_only and not token:
    ...skip + callback (Branch B)...
```

Branch A (fully processed) and Branch B (tokenless PR-only) remain distinct with separate side effects.

### `_process_batch()` per-commit loop (lines 527-583)

Before: recomputes `needs_patch`/`needs_pr`, inline skip logic, inline `pr_complete` boolean.

After: receives `_CommitAction` in the batch tuple (alongside `_ProcessingState`), uses `state.resolve_pr_completion(pr_fetch, outcome.parsed_ok)` for the mark call.

The batch tuple changes from `(sha, message, patch_text, _ProcessingState)` to `(sha, message, patch_text, _ProcessingState, _CommitAction)` so both state and action are available without recomputation.

Branch C (patch-done + PR EMPTY → terminal, `commits_processed += 1`, DB write, no extraction) and Branch D (patch-done + no body → retryable, no counter) are preserved by using `act.needs_patch` and checking `resolve_pr_completion` result.

### Dry-run path (lines 408-444)

Change to `state.action(pr_bodies)` for consistency. `act.needs_patch` for patch pending count, `act.pr_only and not act.needs_patch and state.patch_processed` for PR enrichment pending count — matching current logic which counts PR pending regardless of token availability. The pre-migration `OperationalError` guard stays unchanged.

## What Does Not Change

- `_PrBodyFetch`, `_PrBodyStatus`, `_fetch_pr_body()` — fetch mechanism untouched
- `_mark_processed()` — DB write untouched
- `_get_processing_state()` — DB read untouched (including v16 fallback)
- `_build_signal_bundle()` — signal assembly untouched
- `_stream_commits()` — git streaming untouched
- `ArchaeologyResult` — result shape untouched
- Public API (`archaeologize()` signature) — untouched
- Consecutive PR failure tracking — stays in `_process_batch`, just uses `act.needs_pr`

## Testing Strategy

### Phase 1: Characterization tests (before refactor, must pass on `main`)

Add to `test_archaeology_integration.py`:

1. **Four-branch characterization**: for each of branches A-D in the outcome table, assert `(commits_skipped, commits_processed, callback_call_count, archaeology_processed row state)` against **current** code. These are preservation proofs, not design proofs.

### Phase 2: Unit tests for new abstractions

2. **Action computation**: `_ProcessingState.action(pr_bodies)` returns correct `_CommitAction` for 4 meaningful combinations: (fresh, pr_bodies=True), (fresh, pr_bodies=False), (patch_done, pr_bodies=True), (fully_done, pr_bodies=True)
3. **PR completion resolution**: `resolve_pr_completion()` for FOUND+parsed, FOUND+unparsed, EMPTY, FAILURE, None — 5 cases

### Phase 3: Behavioral regression

4. All existing archaeology tests pass unchanged: `pytest tests/test_archaeology_*.py tests/test_migration_v017.py -v`

## Success Criteria

1. `needs_patch = not state.patch_processed` and `needs_pr = pr_bodies and not state.pr_body_processed` expressions each appear exactly once — in `_ProcessingState.action()`
2. `pr_complete` inline boolean eliminated — `resolve_pr_completion` is the sole completion-determination site
3. All four branches in the outcome table produce identical side effects before and after, verified by characterization tests passing on both `main` and the feature branch
4. All existing archaeology tests pass: `pytest tests/test_archaeology_*.py tests/test_migration_v017.py -v`
5. No change to `archaeologize()` public signature or `ArchaeologyResult` shape
6. Dry-run PR enrichment pending count remains token-independent (verified by `test_archaeology_cli.py:134`)
