# T2-success — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_called_once_for_batch_when_auto_embed_and_repo_path`. Uses `ec_repo`/`ec_db` fixtures; `entirecontext.core.config.load_config` and `entirecontext.core.embedding.generate_embeddings` monkeypatched for the test's duration only. The tmp_path root is the isolation proof — no real repo/DB reachable, and `generate_embeddings` (which would otherwise require `sentence-transformers`) never actually runs.
- Pre-state: 3 archaeology candidates pending, `confidence=0.9`; config monkeypatched to `{"decisions": {"auto_embed": True}}`; `repo_path=str(ec_repo)` passed to the batch call.
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestEmbeddingIntegration::test_embedding_called_once_for_batch_when_auto_embed_and_repo_path -q`
- Exit status: 0
- Sanitized output:
  ```
  .                                                                        [100%]
  1 passed in 0.79s
  ```
- Post-state assertion proven: `len(result["confirmed"]) == 3`, `generate_embeddings` recorded exactly 1 call (`len(calls) == 1`), called with `repo_path == str(ec_repo)` and `decisions_only=True`.
- Mechanism check: `confirm_candidates_batch` calls `generate_embeddings` at most once per batch, after the full confirm loop completes, gated on `confirmed` being non-empty and `config["decisions"]["auto_embed"]` being truthy — observed directly via the call-count assertion (1, not 3 — i.e. not once per candidate).
