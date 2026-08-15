# Transition T1 — Rerun

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Rerun.
- Execution timestamp: `2026-08-14T21:35:22.669377+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.

## Fixture identity and isolation

- Fixture: `$TMP/T1-cancellation-recovery`, after the successful recovery recorded in `T1-success.md`.
- Tool target: fixture `tool`; executable target: fixture `bin`.
- Real shim sentinel remained `/Users/teslamint/.local/bin/ec` with SHA-256 `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7`.
- Complete writable target inventory: the fixture tool and bin directories only.

## Pre-state

- Fixture `ec` was installed.
- Installed `core/futures.py` SHA-256: `b693374ea42345d82557ca27f42d655d03a5267cc5f1a803c75e3f58f846a597`.
- Installed `min_per_verdict` count: 9.

## Exact command

```text
UV_TOOL_DIR=$TMP/T1-cancellation-recovery/tool \
UV_TOOL_BIN_DIR=$TMP/T1-cancellation-recovery/bin \
uv tool install --force .
```

## Exit status and concise output

- Exit status: `0`.
- Output: `Built entirecontext ...`; `Installed 16 packages`; `Installed 1 executable: ec`.

## Post-state

- Installed `core/futures.py` SHA-256 remained `b693374ea42345d82557ca27f42d655d03a5267cc5f1a803c75e3f58f846a597`.
- Installed `min_per_verdict` count remained 9.
- Real shim hash remained unchanged.

## Next invocation result

Fixture `ec --help` exited `0` and printed `Usage: ec [OPTIONS] COMMAND [ARGS]...`.

## Mechanism check

The second force-install rebuilt and replaced the isolated tool but produced byte-identical reviewed source and preserved the required selector count. The rerun is idempotent at the observable installed-code and executable levels.
