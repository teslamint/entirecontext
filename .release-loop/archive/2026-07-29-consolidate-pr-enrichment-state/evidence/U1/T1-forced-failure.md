# T1-forced-failure — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestErrorHandling::test_single_candidate_failure_rolls_back_and_batch_continues`. Uses `ec_repo`/`ec_db` fixtures; `monkeypatch.setattr(decisions_module, "create_decision", flaky_create_decision)` is scoped to the test and reverted automatically by pytest's `monkeypatch` fixture teardown. The tmp_path root is the isolation proof — no real repo/DB reachable.
- Pre-state: 3 archaeology candidates, `review_status='pending'`, `confidence=0.9`. `create_decision` monkeypatched to raise `RuntimeError` for exactly the middle candidate's title, delegate to the original for the other two.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestErrorHandling::test_single_candidate_failure_rolls_back_and_batch_continues -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.95s
  ```
- Post-state assertion proven: `result["failed"] == [fail_id]`, `len(result["confirmed"]) == 2`, and the failed candidate's row has `review_status == "pending"` and `promoted_decision_id IS NULL` after the batch call — the claim was rolled back, not left stuck.
- Mechanism check: `create_decision` raised inside the `BEGIN IMMEDIATE` promotion block; `confirm_candidate`'s outer `except Exception` (decision_candidates.py:230-243) rolled the CAS-claimed row back to `pending`; `confirm_candidates_batch`'s own `except Exception` around the per-candidate call caught the re-raised error and appended the id to `failed` — observed via `review_status='pending'` on the post-state re-fetch, and the batch did not abort (the other two candidates promoted).
