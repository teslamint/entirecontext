# T1-success — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestHappyPath::test_all_eligible_archaeology_candidates_promoted_with_commit_links`. Uses the `ec_repo`/`ec_db` fixtures (real `git init` repo under pytest's `tmp_path`, isolated global DB via `isolated_global_db`). The tmp_path root is the isolation proof — no real repo/DB reachable.
- Pre-state: 3 archaeology `decision_candidates` rows, `review_status='pending'`, `confidence=0.9`, distinct 40-hex `source_id` (commit shas).
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestHappyPath::test_all_eligible_archaeology_candidates_promoted_with_commit_links -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.35s
  ```
- Post-state assertion proven: all 3 candidates end in `result["confirmed"]` (3 decision ids), `result["failed"] == []`, and each source `commit_sha` has a matching `decision_commits` row whose `decision_id` is in `confirmed`.
- Mechanism check: `confirm_candidates_batch` looped `confirm_candidate` per pending row; each call's CAS-claim (`review_status='pending'→'confirmed'`) plus `BEGIN IMMEDIATE` promotion created the `decisions` row and, for archaeology `source_id` (40-hex), the `decision_commits` link — observed directly via the `decision_commits` query keyed on `commit_sha`.
