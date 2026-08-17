---
title: Codex Git Hook Installation
status: approved
date: 2026-08-16
schema: spec/v1
---

# Codex Git Hook Installation Design

_Created 2026-08-16._

## Overview

Make repository Git-hook installation independent of the selected agent integration. `ec init` and `ec enable` install EntireContext's `post-commit` checkpoint and `pre-push` sync hooks by default for `claude`, `codex`, and `both`; `--no-git-hooks` remains the explicit opt-out.

## User Scenarios

### S1: Enable Codex integration

A user runs `ec enable --agent codex` in a Git repository. EntireContext installs Codex notify, the MCP registration, and both repository Git hooks without creating `.claude/settings.local.json`.

### S2: Initialize a repository for Codex

A user runs `ec init --agent codex`. Initialization creates the repository database and installs the same Codex and repository integrations as `ec enable --agent codex`.

### S3: Opt out of repository Git hooks

A user runs either command with `--no-git-hooks`. Codex notify and MCP registration are installed, but `post-commit` and `pre-push` are not.

## Scope

### In

- Install EntireContext-owned repository Git hooks for every valid `--agent` value unless `--no-git-hooks` is present.
- Keep Claude agent hooks limited to `claude` and `both`.
- Keep Codex notify limited to `codex` and `both`.
- Preserve existing foreign-hook and custom-`core.hooksPath` safeguards.
- Close the corresponding `ROADMAP.md` item.

### Out

- Changing Git-hook script contents.
- Changing Codex notify ingestion or configuration format.
- Changing `ec disable` cleanup behavior.
- Replacing foreign Git hooks or writing through a custom `core.hooksPath`.
- Changing MCP registration behavior.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The shipped integration helper installs Git hooks only inside the Claude branch. | `git show ea66322:src/entirecontext/cli/project_cmds.py \| sed -n '497,543p'` | 2026-08-16 | `_install_git_hooks()` is nested under `agent in {"claude", "both"}`. | commit `ea66322` |
| Existing Codex enable and init tests encode the omission. | `git show ea66322:tests/test_project_cmds.py \| sed -n '774,786p;1005,1021p'` | 2026-08-16 | Both tests assert that the Git-hook files do not exist for `--agent codex`. | commit `ea66322` |
| The hook writer already handles ownership, executable bits, linked worktrees, and custom hook paths. | `uv run pytest -q tests/test_project_cmds.py -k 'install_git_hooks'` | 2026-08-16 | Existing focused hook-writer tests pass. | `tests/test_project_cmds.py` |

## Architecture

EC decision `f3dde400-139f-485b-ba39-9c4f5ff11fd3` defines repository Git hooks as agent-neutral lifecycle integrations. `_install_integrations()` retains separate branches for Claude settings and Codex notify, while the existing `_install_git_hooks()` call runs once after agent-specific settings installation and before Codex notify installation. The existing `no_git_hooks` flag gates this call for every agent value.

No schema, data model, hook script, or public option changes are introduced.

## Testing

1. Change the Codex enable integration test to require both Git hooks and reject Claude settings creation.
2. Change the Codex init integration test to require the same behavior.
3. Keep a Codex `--no-git-hooks` assertion proving the opt-out still suppresses both files.
4. Run the full `tests/test_project_cmds.py` module.
5. Smoke-test the checkout's `ec` executable in an isolated Git repository and temporary home directory.

## Risks

- **Accidental Claude configuration for Codex:** moving too much code outside the Claude branch would create `.claude/settings.local.json`. Mitigation: integration assertions require its absence.
- **Broken opt-out:** moving the call without its guard would ignore `--no-git-hooks`. Mitigation: retain the shared guard and assert both hook files remain absent.
- **Duplicate installation for `both`:** leaving the original call in place would invoke the writer twice. Mitigation: one shared call site only.

## Success Criteria

1. `ec enable --agent codex` installs EntireContext `post-commit` and `pre-push` hooks without creating Claude agent settings.
   - **Measured by**: `test_enable_codex_installs_git_hooks_without_claude_hooks` passes.
2. `ec init --agent codex` installs the same repository Git hooks without creating Claude agent settings.
   - **Measured by**: `test_init_agent_codex_installs_git_hooks_without_claude_hooks` passes.
3. `--no-git-hooks` continues to suppress both repository hook files for Codex.
   - **Measured by**: `test_enable_codex_writes_user_notify` asserts both hook paths are absent and passes.
4. Existing project integration behavior remains green.
   - **Measured by**: `uv run pytest -q tests/test_project_cmds.py` and `uv run ruff check src/entirecontext/cli/project_cmds.py tests/test_project_cmds.py` both exit 0.
5. The actual checkout executable produces the intended filesystem state.
   - **Measured by**: an isolated smoke run reports Codex notify plus two Git hooks installed, with `.claude/settings.local.json` absent.

## Open Decisions

None. The user approved continuing the explicit `ROADMAP.md` P2 item on 2026-08-16; the roadmap already fixed the behavior boundary by identifying repository Git hooks as agent-independent and retaining `--no-git-hooks` as the opt-out.
