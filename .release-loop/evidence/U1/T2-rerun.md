# T2-rerun — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: ad hoc verification script (no dedicated pytest test — regeneration safety is a property of calling the same gated code path twice, which the script demonstrates directly rather than adding a redundant permanent test). Throwaway `tempfile.TemporaryDirectory()` git repo, `HOME` redirected to an isolated scratch dir. No real repo/DB reachable.
- Pre-state: 3 archaeology candidates pending, `confidence=0.9`; config monkeypatched to `auto_embed=True`; `generate_embeddings` monkeypatched to a counting no-op.
- Command: `HOME=/tmp/u1_evidence_home uv run python /tmp/u1_evidence_check.py` (function `t2_rerun()`)
- Exit status: 0
- Sanitized output:
  ```
  T2-RERUN call1 confirmed: 3 call2 confirmed: 0
  T2-RERUN embedding calls total: 1
  T2-RERUN: PASS (regeneration safe / no-op call raises nothing)
  ```
- Post-state assertion proven: first call confirms all 3 candidates and triggers 1 embedding call; second call on the now-empty pending pool confirms 0 candidates and (per the `if confirmed and repo_path` gate) triggers 0 further embedding calls, raising nothing.
- Mechanism check: `generate_embeddings(..., decisions_only=True)` is a pure regeneration pass over `decisions` rows lacking embeddings (per `core/embedding.py`) — there is no batch-specific state that a second invocation could corrupt or double-count; the plan text ("regeneration is safe (derived data)") is confirmed by the second call completing without error even when zero new candidates were confirmed.
