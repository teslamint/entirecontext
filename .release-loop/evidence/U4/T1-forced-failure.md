# Transition T1 — Forced Failure

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Forced failure.
- Execution timestamp: `2026-08-14T21:35:20.343006+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.

## Fixture identity and isolation

- Fixture: `$TMP/T1-forced-failure`.
- Source: disposable checkout copy.
- Tool target: `$TMP/T1-forced-failure/tool` via `UV_TOOL_DIR`.
- Executable target: `$TMP/T1-forced-failure/bin` via `UV_TOOL_BIN_DIR`.
- Real shim sentinel: `/Users/teslamint/.local/bin/ec`, SHA-256 `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7` before and after.
- Complete writable target inventory: the fixture source copy, tool directory, and bin directory only.

## Pre-state

The fixture tool and bin directories did not exist. The real shim hash was captured without opening it for write.

## Exact failure injection and command

The disposable `pyproject.toml` version was changed to:

```toml
version = "not valid !!!"
```

Then:

```text
UV_TOOL_DIR=$TMP/T1-forced-failure/tool \
UV_TOOL_BIN_DIR=$TMP/T1-forced-failure/bin \
uv tool install --force .
```

## Exit status and concise output

- Exit status: `2`.
- Stderr:

```text
error: Failed to parse metadata from built wheel
  Caused by: TOML parse error at line 3, column 11
    3 | version = "not valid !!!"
      |           ^^^^^^^^^^^^^^^
    expected version to start with a number, but no leading ASCII digits were found
```

## Post-state

- Fixture bin files: none.
- Fixture tool files: none.
- Real shim hash: unchanged.

## Next invocation result

The clean-source recovery is recorded in `T1-success.md`: exit `0`, `ec` created in the isolated bin, installed selector count 9, and `ec --help` exit `0`.

## Mechanism check

The injected invalid version is named by the parser at the exact changed line. No executable or tool files were created and the real shim remained byte-identical. The failure is therefore attributable to package metadata parsing inside the isolated boundary, not to an unrelated command failure.
