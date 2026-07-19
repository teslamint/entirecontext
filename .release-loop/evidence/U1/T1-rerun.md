# T1-rerun — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: ad hoc verification script (not part of the committed suite — this cell has no dedicated pytest test since it requires two sequential `confirm_candidates_batch` calls across a monkeypatch boundary). Script builds its own throwaway `tempfile.TemporaryDirectory()` git repo via the same `git init` + `init_project` sequence `tests/conftest.py`'s `git_repo`/`ec_repo` fixtures use, run with `HOME` redirected to an isolated scratch dir so no real `~/.entirecontext` DB is touched. No real repo/DB reachable.
- Pre-state: 3 archaeology candidates seeded pending, `confidence=0.9`. First call has `create_decision` patched to fail for the middle candidate (same pattern as T1-forced-failure); patch is released before the second call.
- Command: `HOME=/tmp/u1_evidence_home uv run python /tmp/u1_evidence_check.py` (function `t1_rerun()`)
- Exit status: 0
- Sanitized output:
  ```
  T1-RERUN call1: {'confirmed': 2, 'failed': ['b4b917ca-e962-4e0b-83bd-49afd457bd93']}
  T1-RERUN post-call1 status: pending promoted_decision_id: None
  T1-RERUN call2: {'confirmed': 1, 'failed': []}
  T1-RERUN post-call2 status: confirmed promoted_decision_id: 8ae06821-4d1d-477c-9978-2ece88405f52
  T1-RERUN: PASS
  ```
- Post-state assertion proven: after call 1, the failed candidate is `pending`/`promoted_decision_id IS NULL` (retryable). After call 2 (no patch), the same candidate is picked up again by `list_candidates(status='pending', ...)`, promoted, and ends `confirmed` with a non-null `promoted_decision_id`.
- Mechanism check: `confirm_candidates_batch` re-queries `list_candidates(status='pending', ...)` fresh on every invocation with no persistent skip-list across calls (the `attempted` set is local to one call) — so a candidate rolled back to `pending` by a prior failed run is indistinguishable from a never-tried one on the next call, giving idempotent convergence without special-case retry logic.
