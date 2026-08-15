# Transition T1 — Success

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Success.
- Execution timestamp: `2026-08-14T21:35:21.135692+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.
- This is a disposable replay of the already-completed global U4 install; it does not mutate the machine-global tool.

## Fixture identity and isolation

- Fixture: `$TMP/T1-cancellation-recovery`.
- Source: a disposable copy of the reviewed checkout.
- Tool target: `$TMP/T1-cancellation-recovery/tool` via `UV_TOOL_DIR`.
- Executable target: `$TMP/T1-cancellation-recovery/bin` via `UV_TOOL_BIN_DIR`.
- Real shim sentinel: `/Users/teslamint/.local/bin/ec`, SHA-256 `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7` before and after.
- Complete writable target inventory: only the two fixture directories above; the source copy and rollback-source copy are read inputs.

## Pre-state

The interrupted first attempt left no installed `entirecontext/core/futures.py` candidate in the fixture tool directory. The fixture bin directory contained no `ec` executable.

## Exact injection / command

No failure injection. Recovery command:

```text
UV_TOOL_DIR=$TMP/T1-cancellation-recovery/tool \
UV_TOOL_BIN_DIR=$TMP/T1-cancellation-recovery/bin \
uv tool install --force .
```

## Exit status and concise output

- Exit status: `0`.
- Output: `Built entirecontext ...`; `Installed 16 packages`; `Installed 1 executable: ec`.

## Post-state

- Fixture executable exists at `$TMP/T1-cancellation-recovery/bin/ec`.
- Installed `core/futures.py` contains `min_per_verdict` 9 times, satisfying the plan's `>=8` verification.
- The real shim hash is unchanged.

## Next invocation result

```text
$TMP/T1-cancellation-recovery/bin/ec --help
```

Exit status `0`; output contains `Usage: ec [OPTIONS] COMMAND [ARGS]...`.

## Mechanism check

The recovery wrote only to the fixture target, produced the expected executable and installed source, and left the real machine-global shim byte-identical. This proves the success path rather than merely observing a zero exit code.
