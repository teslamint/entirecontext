# T1-headless — candidate claim+promotion

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T1
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`
- Fixture identity: `tests/test_decision_candidates_batch.py` (full module). `confirm_candidates_batch` takes no interactive input (no `input()`, no TTY read, no prompt) — every code path is pure function calls over `conn`. The plan text notes "CLI is non-interactive; no TTY dependency (CliRunner tests prove it)" for T1; the equivalent proof here is that the entire batch module runs to completion under `pytest`, which supplies no stdin/TTY.
- Pre-state: n/a (module-wide non-interactivity check, not a specific data state).
- Command: `uv run pytest tests/test_decision_candidates_batch.py -q`
- Exit status: 0
- Sanitized output:
  ```
  ..........                                                               [100%]
  10 passed in 1.10s
  ```
- Post-state assertion proven: all 10 tests (dry-run, happy path, pagination, forced-failure, already-confirmed-race, embedding gating) complete without any prompt, hang, or TTY wait — `confirm_candidates_batch` and every helper it calls (`list_candidates`, `confirm_candidate`, `load_config`, `generate_embeddings`) are synchronous, argument-driven functions.
- Mechanism check: static inspection of `confirm_candidates_batch`'s implementation confirms it contains no `input()`/prompt/interactive call; the full green run under pytest (which runs with no attached TTY) is the executable confirmation that nothing in the call chain blocks on interactive input.
