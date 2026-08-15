# Transition T1 — Cancellation / Abort

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Cancellation or abort.
- Execution timestamp: `2026-08-14T21:35:21.071939+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.

## Fixture identity and isolation

- Fixture: `$TMP/T1-cancellation-recovery`.
- Source: disposable checkout copy.
- Tool target: fixture `tool`; executable target: fixture `bin`.
- Real shim sentinel: `/Users/teslamint/.local/bin/ec`, SHA-256 `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7` throughout.
- Complete writable target inventory: the fixture source, tool, and bin directories only.

## Pre-state

The fixture tool and bin directories did not contain an installed EntireContext tool or executable.

## Exact injection / command

The process was started in a new process group:

```text
UV_TOOL_DIR=$TMP/T1-cancellation-recovery/tool \
UV_TOOL_BIN_DIR=$TMP/T1-cancellation-recovery/bin \
uv tool install --force .
```

After 50 ms, while it was still running, SIGINT was sent to that fixture process group only.

## Exit status and concise output

- Exit status: `-2` (terminated by SIGINT).
- Captured stdout/stderr: empty; interruption occurred before build output.

## Post-state

- No installed `entirecontext/core/futures.py` candidate existed in the fixture tool directory.
- The real shim hash remained unchanged.

## Next invocation result

The same command was rerun without interruption in the same fixture:

- Exit status: `0`.
- Output: built EntireContext, installed 16 packages, installed one `ec` executable.
- Installed `core/futures.py` `min_per_verdict` count: 9.
- Fixture `ec --help`: exit `0`, `Usage: ec [OPTIONS] COMMAND [ARGS]...`.

## Mechanism check

The negative return code identifies SIGINT rather than a package error. The interrupted fixture contained no installed selector, so the plan's count check would fail closed. A clean rerun restored a complete, runnable fixture installation while the real shim remained byte-identical.
