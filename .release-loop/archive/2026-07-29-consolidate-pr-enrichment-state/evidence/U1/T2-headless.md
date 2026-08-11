# T2-headless — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: `tests/test_decision_candidates_batch.py::TestEmbeddingIntegration` (all 3 tests: called-once, dry-run-skips, no-repo-path-skips). The embedding tail is entirely config-gated (`config.get("decisions", {}).get("auto_embed", False)`) with no prompt, confirmation dialog, or TTY read anywhere in the path.
- Pre-state: n/a (module-wide non-interactivity check for the embedding integration tests specifically).
- Command: `uv run pytest tests/test_decision_candidates_batch.py::TestEmbeddingIntegration -q`
- Exit status: 0
- Sanitized output:
  ```
  ...                                                                      [100%]
  3 passed in 0.49s
  ```
- Post-state assertion proven: all 3 embedding-integration tests (auto_embed on + repo_path → called once; dry_run → called zero times; repo_path=None → called zero times) complete under pytest with no interactive input, confirming the gate is a pure boolean config read plus a direct function call.
- Mechanism check: static inspection of the embedding tail in `confirm_candidates_batch` (mirroring `confirm_candidate`'s existing tail at :245-255) shows only `load_config`, a dict `.get()` chain, and a direct `generate_embeddings` call inside `try/except: pass` — no branch depends on stdin, a TTY, or any user confirmation.
