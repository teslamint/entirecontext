# T2-forced-failure — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `94d48d47db42a505115fda5bd2fb2618acd589cd`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_failure_during_batch_is_swallowed`. Uses the `ec_repo`/`ec_db` fixtures (real `git init` repo under pytest's `tmp_path`, isolated global DB via `isolated_global_db`). The tmp_path root is the isolation proof — no real repo/DB reachable. This replaces the ad hoc `/tmp/u1_evidence_check.py` script cited in the previous version of this record (never committed, not independently reproducible) with a permanent test in the committed suite.
- Pre-state: 3 archaeology candidates pending, `confidence=0.9`; `load_config` monkeypatched to return `auto_embed=True`; `generate_embeddings` monkeypatched to unconditionally raise `RuntimeError`.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_failure_during_batch_is_swallowed -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.40s
  ```
- Post-state assertion proven: all 3 candidates remain in `result["confirmed"]` (batch return value unaffected by the embedding failure); `result["failed"] == []` — the embedding exception did not get attributed to any candidate, and no exception propagated out of `confirm_candidates_batch`.
- Mechanism check: `confirm_candidates_batch`'s batch-end embedding block wraps `load_config` + gate check + `generate_embeddings` in a single `try/except: pass` (mirroring `confirm_candidate`'s own per-candidate embedding tail at :245-255) — the injected `RuntimeError` was swallowed at that boundary and never propagated to the caller or reversed any confirmation.
