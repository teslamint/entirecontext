# T1-rerun — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `94d48d47db42a505115fda5bd2fb2618acd589cd`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestRerunSemantics::test_second_batch_call_promotes_previously_failed_candidate_without_touching_confirmed`. Uses the `ec_repo`/`ec_db` fixtures (real `git init` repo under pytest's `tmp_path`, isolated global DB via `isolated_global_db`). The tmp_path root is the isolation proof — no real repo/DB reachable. This replaces the ad hoc `/tmp/u1_evidence_check.py` script cited in the previous version of this record (never committed, not independently reproducible) with a permanent test in the committed suite.
- Pre-state: 3 archaeology candidates seeded pending, `confidence=0.9`. `entirecontext.core.decisions.create_decision` is monkeypatched to raise for exactly the middle candidate's title.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestRerunSemantics::test_second_batch_call_promotes_previously_failed_candidate_without_touching_confirmed -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.36s
  ```
- Post-state assertion proven: call 1 (with `create_decision` patched) leaves the target candidate in `result1["failed"]`, the other two in `result1["confirmed"]`. The monkeypatch is then reverted and call 2 runs against the same DB: the previously-failed candidate is now `review_status='confirmed'` with `promoted_decision_id` present in `result2["confirmed"]`, while the two previously-confirmed candidates' `promoted_decision_id` and `reviewed_at` are asserted byte-identical before/after call 2 — proving `confirm_candidate` was never re-invoked on them.
- Mechanism check: `confirm_candidates_batch` re-queries `list_candidates(status='pending', ...)` fresh on every invocation with no persistent skip-list across calls (the `attempted` set is local to one call) — a candidate rolled back to `pending` by a prior failed run is indistinguishable from a never-tried one on the next call, giving idempotent convergence without special-case retry logic; already-confirmed rows are structurally excluded by the `status='pending'` filter, so they are never re-touched.
