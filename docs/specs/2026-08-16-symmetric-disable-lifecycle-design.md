---
title: Symmetric Disable Lifecycle
status: approved
date: 2026-08-16
schema: spec/v1
---

# Symmetric Disable Lifecycle Design

## Overview

`ec enable` and `ec init` install three kinds of integration: agent-specific Claude hooks or Codex notify, repository-local Git hooks shared by every agent mode, and one user-level MCP registration shared across repositories and agents. Before this change, `ec disable --agent codex` removed Codex notify but left the repository Git hooks, while no disable path could remove MCP. The lifecycle must become symmetric without deleting shared or manually owned user configuration implicitly.

The governing decision is `30f75661-044d-49e3-a434-b3ca93989be1`.

## Goals

1. Every `ec disable` agent mode removes EntireContext-owned `post-commit` and `pre-push` hooks from the current repository.
2. Claude hooks remain specific to `--agent claude|both`; Codex notify remains specific to `--agent codex|both`.
3. Default disable preserves the user-level MCP entry because another repository or agent may still use it.
4. `--remove-mcp` explicitly removes a standard EntireContext MCP entry as a global cleanup action.
5. MCP cleanup preserves sibling servers, unrelated top-level settings, the `mcpServers` container, and nonstandard `entirecontext` entries.
6. Existing ownership checks continue to preserve foreign Git hooks and user-authored Claude hook structure.

## Non-Goals

- Cross-repository MCP consumer reference counting.
- Reconstructing ownership for integrations created before this release.
- Deleting arbitrary `mcpServers.entirecontext` values.
- Changing `ec enable`, `ec init`, database schema, or dependency versions.

## User Scenarios

### S1: Disable Codex in a repository that still uses Claude

The user enables Claude and Codex integrations, then runs `ec disable --agent codex`. Codex notify and the repository Git hooks are removed. Claude hooks and the user-level MCP entry remain.

### S2: Disable every selected integration and explicitly clean up MCP

The user runs `ec disable --agent both --remove-mcp`. Claude hooks, Codex notify, EntireContext-owned repository Git hooks, and a standard EntireContext MCP entry are removed.

### S3: Preserve other user configuration

The user-level settings contain sibling MCP servers, unrelated top-level keys, or a nonstandard `entirecontext` entry. Disable preserves those values. With `--remove-mcp`, only a standard EC stdio entry is eligible for removal.

### S4: Remove the Python-module fallback registration

An earlier install registered the MCP server through the Python module fallback rather than an `ec` executable. `ec disable --remove-mcp` recognizes and removes that standard form.

## Interface Contract

```text
ec disable [--agent claude|codex|both] [--remove-mcp]
```

- `--agent` selects the agent-specific integration to remove.
- Repository Git hooks are agent-neutral and are removed for every agent selection.
- MCP is global and remains untouched unless `--remove-mcp` is present.
- `--remove-mcp` removes either exact standard form:
  - an `ec` or `ec.exe` executable with `args = ["mcp", "serve"]` and `type = "stdio"`;
  - a Python executable with `args = ["-m", "entirecontext.cli", "mcp", "serve"]` and `type = "stdio"`.
- A standard entry configured manually is indistinguishable from one written by EC. The explicit flag authorizes removing either; default disable removes neither.

## Architecture

`project_cmds.py` keeps agent-specific cleanup in its existing branches. `_remove_git_hooks(repo_path)` moves to the shared disable path so Claude, Codex, and both modes apply the same repository-local cleanup. `_is_ec_git_hook(content, hook_name)` requires the complete three-line generated hook shape and exact EC command before installation or removal treats a file as owned. `_is_ec_mcp_server(value)` validates the exact standard MCP shapes. `_remove_mcp_registration()` edits only `~/.claude/settings.json` and only when the standard `mcpServers.entirecontext` entry is present. The command calls it only when `--remove-mcp` is explicitly supplied.

The MCP settings object is rewritten in place without deleting empty containers. This avoids synthesizing a second configuration convention and preserves all values EC does not own.

## Error and Safety Behavior

- Missing integrations are idempotent no-ops with informational output.
- Malformed JSON behavior is unchanged; disable does not hide configuration parse failures.
- Foreign or composed Git hook files remain untouched under exact generated-shape and `core.hooksPath` ownership guards; a comment that merely mentions EntireContext is insufficient for deletion.
- Nonstandard MCP entries remain untouched even with `--remove-mcp`.
- The command never infers global MCP ownership from executable shape during default cleanup.

## Testing

The implementation must retain these distinct observable tests without merging or renaming them silently:

1. `test_enable_disable_claude_with_explicit_mcp_cleanup`
2. `test_enable_disable_codex_removes_codex_and_repo_integrations_only`
3. `test_enable_disable_both_with_explicit_mcp_cleanup`
4. `test_disable_preserves_unrecognized_entirecontext_mcp_registration`
5. `test_disable_removes_generated_python_module_mcp_registration`
6. `TestHookInstall::test_disable_removes_hooks`

The complete `tests/test_project_cmds.py` and `tests/test_e2e_hooks_install.py` modules must also remain green because their existing ownership and lifecycle contracts are in the immediate blast radius.

## Success Criteria

1. Codex disable removes Codex notify and both EntireContext repository Git hooks while preserving Claude hooks and MCP.
   - **Measured by**: `test_enable_disable_codex_removes_codex_and_repo_integrations_only` passes.
2. Explicit MCP cleanup removes a standard EC entry for Claude and both-agent round trips while preserving sibling and unrelated user settings.
   - **Measured by**: `test_enable_disable_claude_with_explicit_mcp_cleanup` and `test_enable_disable_both_with_explicit_mcp_cleanup` pass.
3. Nonstandard `entirecontext` MCP configuration survives explicit cleanup, while the generated Python-module form is removed.
   - **Measured by**: the two named MCP boundary tests pass.
4. The end-to-end enable/disable flow removes all explicitly selected artifacts.
   - **Measured by**: `TestHookInstall::test_disable_removes_hooks` passes with `--remove-mcp`.
5. Existing project-command and hook-install behavior remains green.
   - **Measured by**: both complete affected test modules and focused Ruff checks exit 0.

## Open Decisions

None. Automatic MCP removal was rejected after review because executable-shape matching cannot prove ownership or liveness across agents and repositories. Decision `30f75661-044d-49e3-a434-b3ca93989be1` replaces that unsafe default with an explicit global cleanup flag.
