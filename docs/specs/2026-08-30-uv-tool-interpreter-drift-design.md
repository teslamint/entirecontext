---
title: uv Tool Interpreter Drift Diagnostics
status: approved
date: 2026-08-30
schema: spec/v1
---

# uv Tool Interpreter Drift Diagnostics

## Overview

An existing uv tool environment can retain Python 3.13 metadata while its
interpreter symlink starts Python 3.14. The `ec` package then remains under the
Python 3.13 site-packages directory and becomes unavailable to the active
runtime. Issue #243 requires stable installation guidance, an import-independent
recovery path, and an `ec doctor` warning after a partial reinstall restores the
entry point without repairing the stale environment binding.

## Goals

1. Recommend a uv-managed Python 3.13 interpreter for global installation.
2. Document clean tool-environment recreation before invoking `ec`.
3. Compare the configured virtual-environment Python major-minor version with
   the active runtime major-minor version in `ec doctor`.
4. Print both versions and exact recreation commands when they differ.
5. Preserve the EntireContext database and repository data during recovery.
6. Keep package health separate from Codex MCP `enabled` state.

## Non-Goals

- Managing uv or Conda interpreter upgrades.
- Enabling a disabled Codex MCP registration.
- Treating Python patch-version changes as interpreter drift.
- Failing `ec doctor` when virtual-environment metadata is unavailable.

## Interface Contract

`ec doctor` reads `pyvenv.cfg` below `sys.prefix`. It parses the `version_info`
field and compares only its major-minor pair with `sys.version_info`.

When the pairs differ, the warning contains both versions and these commands:

```text
uv tool uninstall entirecontext
uv tool install --managed-python --python 3.13 entirecontext
```

When `ec doctor` runs in an EntireContext source checkout, the second command
uses `.` instead of `entirecontext`. Matching versions, patch-only differences,
missing files, unreadable files, missing keys, and malformed values produce no
interpreter-drift warning.

## Recovery Contract

Recovery starts with `uv`, because a broken `ec` entry point cannot run doctor.
Uninstalling and reinstalling the tool environment does not remove
`~/.entirecontext` or repository `.entirecontext` directories. A successful
recovery verifies `ec --help`, the recreated `pyvenv.cfg`, and the imported
`entirecontext` package path. `uv tool install --force` is not the recovery
command because it can restore packages without replacing a stale interpreter
binding.

## Testing

1. `test_doctor_accepts_matching_virtualenv_and_runtime_versions`
2. `test_doctor_warns_for_virtualenv_major_minor_drift`
3. `test_doctor_skips_unavailable_virtualenv_metadata`
4. `test_doctor_skips_invalid_utf8_virtualenv_metadata`
5. `test_doctor_skips_unparseable_numeric_virtualenv_metadata`

The complete `tests/test_project_cmds.py` module must remain green.

## Success Criteria

1. Matching Python major-minor versions produce no drift warning.
   - **Measured by**: test 1 passes.
2. A configured Python 3.13 and active Python 3.14 report both versions and the
   exact clean-recreation commands.
   - **Measured by**: test 2 passes.
3. Missing environment metadata does not crash doctor or create a false warning.
   - **Measured by**: test 3 passes.
4. README installation, recovery, verification, and MCP troubleshooting text
   satisfies the recovery contract.
   - **Measured by**: direct documentation inspection and focused text checks.

## Open Decisions

None. The issue fixes Python 3.13 as the supported managed interpreter command.
