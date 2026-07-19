# T1-rollback — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: same test as T1-forced-failure — `tests/test_decision_candidates_batch.py::TestErrorHandling::test_single_candidate_failure_rolls_back_and_batch_continues`. The plan text is explicit that for T1 "the claim-rollback IS the compensation" (plan line 203), so rollback and forced-failure are proven by the same mechanism/test rather than a separate scenario. The `ec_repo`/`ec_db` tmp_path fixture root is the isolation proof.
- Pre-state: identical to T1-forced-failure — 3 pending archaeology candidates, one rigged to fail inside promotion.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestErrorHandling::test_single_candidate_failure_rolls_back_and_batch_continues -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.95s
  ```
- Post-state assertion proven: `decision_candidates.review_status == 'pending'` and `promoted_decision_id IS NULL` for the failed candidate — no orphan `decisions` row and no orphan join rows were left behind (the `BEGIN IMMEDIATE` block's own rollback removes any partial `decisions`/`decision_files`/`decision_commits` writes, and the outer compensating UPDATE removes the Step-1 claim separately, since SQLite's transaction rollback cannot reach a self-committed autocommit statement).
- Mechanism check: two independent rollback layers cooperate — (1) `transaction()`'s `BEGIN IMMEDIATE` around `create_decision` + link helpers rolls back on the injected `RuntimeError`, so no decision/join rows persist; (2) the separate outer-except `UPDATE ... WHERE review_status='confirmed' AND promoted_decision_id IS NULL` compensates the already-committed Step-1 claim back to `pending`. Both are pre-existing `confirm_candidate` behavior, unchanged by U1 — `confirm_candidates_batch` only observes the resulting exception and files the candidate id under `failed`.
