# T1-cancellation — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`

This cell's proof is analytical, per the brief (U1-brief.md line 67) and the plan text (line 203: "Cancellation/abort: KeyboardInterrupt between candidates leaves only whole-candidate states (each candidate is atomic); resume = rerun. Abort inside one candidate's promotion → SQLite rolls back the open transaction; worst case is the documented pre-existing 'claim committed, promotion not started' stuck state (confirm_candidate docstring), unchanged by this plan."). No command output is fabricated for this cell.

Reasoning:
- `confirm_candidates_batch`'s per-candidate loop calls `confirm_candidate(conn, candidate["id"], ...)` synchronously, one candidate at a time, with no batching of DML across candidates. A `KeyboardInterrupt` (or any external abort signal) delivered *between* iterations leaves every already-processed candidate in one of exactly two terminal states — `confirmed` with a decision, or `pending` (rolled back) — because each candidate's promotion is already a complete, independently-committed unit of work by the time control returns to the loop. There is no batch-level transaction wrapping multiple candidates that a mid-batch abort could leave half-open.
- An abort *during* one candidate's promotion (inside `confirm_candidate`'s `BEGIN IMMEDIATE` block) is bounded by SQLite's own transaction semantics: an interrupted Python process either lets the `except` handler run (compensating rollback fires, same as T1-rollback) or dies before it can, in which case the pre-existing stuck state documented in `confirm_candidate`'s docstring ("claim committed, Step 2 not started") applies — a state this plan does not change or newly introduce, since `confirm_candidates_batch` reuses `confirm_candidate` unmodified.
- Resume semantics: because `confirm_candidates_batch` re-derives its work list from `list_candidates(status='pending', ...)` on every fresh invocation (see T1-rerun), re-running the batch after any cancellation naturally retries whatever is still `pending` — no special resume logic needed.

Verification pointer: the T1-rerun evidence record demonstrates the "re-run retries pending state" half of this claim executably; the "whole-candidate atomicity" half is inherited unmodified from `confirm_candidate`, which is out of scope for U1 to re-verify.
