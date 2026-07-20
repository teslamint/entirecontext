# T3 - archaeology processing marks

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T3
- Source commit: `4ee7905` (v0.14.0 archaeology state model; unchanged by v0.15.0)
- Verified: 2026-07-20T15:50:00+09:00
- Fixture identity: five focused tests under `tests/test_archaeology.py::TestArchaeologize`, using the repository's `ec_repo` and `ec_db` pytest fixtures under `tmp_path`. The fixtures isolate the git repository and SQLite DB; monkeypatched extraction responses prevent external LLM or production targets from being reachable.
- Complete live target inventory: 334 eligible non-merge commits, proven by `git rev-list --count --no-merges HEAD`.
- Pre-state: 292 rows in `archaeology_processed`; 42 patch extractions pending; 0 PR enrichments pending.
- Action: user-approved temporary Codex extraction fallback processed the remaining local commit messages and patches after the configured Claude CLI returned `authentication_failed`. Transcript: `step2e-codex-fallback.txt`.
- Exit status: 0. The run processed 42 commits and generated 15 candidates.
- Post-state: 334 rows in `archaeology_processed`; final dry-run reports 334 already processed, 0 patch extractions pending, and 0 PR enrichments pending. Metrics: `step5-post-confirm-metrics.txt`.
- Boundary sentinel: the eligible non-merge commit count and processing-row count are both exactly 334; pending archaeology candidates reached 0 only after the separate confirmation transition.
- Rerun: `test_rerun_skips_already_processed` proves processed commits are not replayed; the live final dry-run estimated 0 tokens and performed no writes.
- Forced failure and compensation: `test_failed_extraction_not_marked_processed` proves an unparsed extraction does not write the idempotency marker; `test_failed_extraction_retried_on_next_run` proves the next invocation retries it. Append-only processing marks require no rollback once a parse succeeds.
- Cancellation: `test_interrupt_processes_each_commit_exactly_once` proves the next invocation resumes without duplicating already completed commits.
- Headless: the core transition and CLI are non-interactive; the focused regression tests completed without a TTY.
- Sanitized regression output: `T3-regression-tests.txt` (`5 passed in 5.89s`).
- Mechanism check: the live pre/post counts and the isolated tests jointly prove the intended `archaeology_processed` boundary changed, rather than an unrelated DB or fixture setup path.
