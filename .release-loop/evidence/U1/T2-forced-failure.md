# T2-forced-failure — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: ad hoc verification script (no dedicated pytest test — the committed suite covers the "called once" and "not called" gating cases; this cell specifically needs `generate_embeddings` to raise, which the script isolates from the persistent test suite to avoid adding a test whose only job is exercising a `pass`-swallowed exception path already covered by the identical pattern in `confirm_candidate`'s own tests). Script builds a throwaway `tempfile.TemporaryDirectory()` git repo (same `git init` + `init_project` sequence as `tests/conftest.py`), `HOME` redirected to an isolated scratch dir. No real repo/DB reachable.
- Pre-state: 3 archaeology candidates pending, `confidence=0.9`; config monkeypatched to `auto_embed=True`; `generate_embeddings` monkeypatched with `side_effect=RuntimeError(...)`.
- Command: `HOME=/tmp/u1_evidence_home uv run python /tmp/u1_evidence_check.py` (function `t2_forced_failure()`)
- Exit status: 0
- Sanitized output:
  ```
  T2-FORCED-FAILURE result: {'confirmed': 3, 'failed': []}
  T2-FORCED-FAILURE: PASS (embedding raise swallowed, confirmations stand)
  ```
- Post-state assertion proven: all 3 candidates remain in `result["confirmed"]` (batch return value unaffected by the embedding failure); `result["failed"] == []` — the embedding exception did not get attributed to any candidate.
- Mechanism check: `confirm_candidates_batch`'s batch-end embedding block wraps `load_config` + gate check + `generate_embeddings` in a single `try/except: pass` (mirroring `confirm_candidate`'s own per-candidate embedding tail at :245-255) — the injected `RuntimeError` was swallowed at that boundary and never propagated to the caller or reversed any confirmation.
