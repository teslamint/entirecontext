# Transition T1 — Rollback / Compensation

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Rollback or compensation.
- Execution timestamp: `2026-08-14T21:35:22.877575+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.
- Compensation source: base commit `74212bb`.

## Fixture identity and isolation

- Fixture: `$TMP/T1-cancellation-recovery`.
- Compensation source: a disposable `git archive` extraction of `74212bb`.
- Tool target: fixture `tool`; executable target: fixture `bin`.
- Real shim sentinel: `/Users/teslamint/.local/bin/ec`, SHA-256 `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7` before and after.
- Complete writable target inventory: the fixture tool and bin directories only.

## Pre-state

The fixture held the reviewed selector implementation. Installed `core/futures.py` SHA-256 was `b693374ea42345d82557ca27f42d655d03a5267cc5f1a803c75e3f58f846a597`, with `min_per_verdict` count 9.

## Exact command

```text
UV_TOOL_DIR=$TMP/T1-cancellation-recovery/tool \
UV_TOOL_BIN_DIR=$TMP/T1-cancellation-recovery/bin \
uv tool install --force $TMP/T1-cancellation-recovery/rollback-source-74212bb
```

## Exit status and concise output

- Exit status: `0`.
- Output: built `entirecontext` from the archived base source; installed 16 packages and one `ec` executable.

## Post-state

- Installed `core/futures.py` `min_per_verdict` count: `0`, matching the selected base revision.
- Real shim hash: unchanged.

## Next invocation result

Fixture `ec --help` exited `0` and printed `Usage: ec [OPTIONS] COMMAND [ARGS]...`.

## Mechanism check

The compensation used the plan's forward-reinstall strategy rather than filesystem rollback. The installed selector changed from reviewed state (count 9) to base state (count 0), the executable remained runnable, and the machine-global shim remained byte-identical.
