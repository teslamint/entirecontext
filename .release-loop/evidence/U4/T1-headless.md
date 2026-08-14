# Transition T1 — Headless / No Global Install

## Plan source

- Approved matrix: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`, Transition T1 / Headless or no global install.
- Execution timestamp: `2026-08-14T21:35:23.751970+00:00`.
- Source commit: `edf4f1878d6b2c6a1f9c9f4729bef919bd45c1a7`.
- Source manifest: SHA-256 `4d4371ad619d7435a40ac9f201752d6fa59a64b4c43072c1e8dceb2fa179a113` over 122 files (`pyproject.toml` plus sorted `src/entirecontext/**/*.py`, hashing each relative path, NUL, file bytes, NUL).
- Manifest proof: `.release-loop/evidence/U4/final-source-manifest.txt`.

## Fixture identity and isolation

- Fixture: `$TMP/T1-headless`.
- PATH: `/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin`; this excludes `/Users/teslamint/.local/bin`.
- Tool target and bin target were redirected to empty fixture directories.
- Checkout executable: absolute `/Users/teslamint/.local/bin/uv` invoking `uv run ec`; the global `ec` shim was not resolved or invoked.
- Real shim sentinel SHA-256: `c4a05a1bbcb85a81fffdb0bd61e5021216ea81a88b9936f2752fd7a61caa43d7` before and after.
- Complete writable target inventory: fixture output, tool, and bin directories only.

## Pre-state

- `ec` resolution under the restricted PATH: none.
- Fixture tool and bin directories: empty/nonexistent.

## Exact command

```text
PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin \
UV_TOOL_DIR=$TMP/T1-headless/tool \
UV_TOOL_BIN_DIR=$TMP/T1-headless/bin \
/Users/teslamint/.local/bin/uv run ec futures lessons \
  --output $TMP/T1-headless/LESSONS.md
```

## Exit status and concise output

- Exit status: `0`.
- Stdout: `Written 50 lessons to $TMP/T1-headless/LESSONS.md`.
- Stderr: only the existing `VIRTUAL_ENV` mismatch warning from `uv`.

## Post-state

- `$TMP/T1-headless/LESSONS.md` exists and contains 50 lesson entries.
- Fixture bin files: none. No global installation was attempted.
- Real shim hash: unchanged.

## Next invocation result

The checkout-scoped `uv run ec futures lessons` invocation itself is the next-step path specified by the plan when no global `ec` is resolvable. It completed successfully and generated the artifact.

## Mechanism check

The restricted PATH proves that no global `ec` command was available. `uv run` executed the checkout entry point, produced the expected 50-entry artifact, created no fixture/global tool executable, and left the real shim byte-identical.
