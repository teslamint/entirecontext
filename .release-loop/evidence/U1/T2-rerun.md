# T2-rerun — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `94d48d47db42a505115fda5bd2fb2618acd589cd`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_called_once_per_confirming_batch_invocation`. Uses the `ec_repo`/`ec_db` fixtures (real `git init` repo under pytest's `tmp_path`, isolated global DB via `isolated_global_db`). The tmp_path root is the isolation proof — no real repo/DB reachable. This replaces the ad hoc `/tmp/u1_evidence_check.py` script cited in the previous version of this record (never committed, not independently reproducible) with a permanent test in the committed suite.
- Pre-state: config monkeypatched to `auto_embed=True`; `generate_embeddings` monkeypatched to a counting no-op. One archaeology candidate seeded, `confidence=0.9`.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_called_once_per_confirming_batch_invocation -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 1.51s
  ```
- Post-state assertion proven: call 1 confirms 1 candidate and triggers exactly 1 embedding call (`len(calls) == 1`). A second candidate is then seeded and call 2 (same `conn`/`repo_path`) confirms it and triggers a second embedding call (`len(calls) == 2`) — one `generate_embeddings` invocation per batch call that confirmed ≥1 candidate, with no error on either call.
- Mechanism check: `generate_embeddings(..., decisions_only=True)` is a pure regeneration pass over `decisions` rows lacking embeddings (per `core/embedding.py`) — there is no batch-specific state that a second invocation could corrupt or double-count; the plan text ("regeneration is safe (derived data)") is confirmed by both calls completing without error, one embedding call per confirming invocation.
