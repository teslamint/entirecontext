---
module: repository-resolution
date: 2026-09-25
problem_type: workflow_issue
component: repo-roots
severity: high
applies_when:
  - "A new CLI command, hook, MCP tool or worker opens the database or reads config"
  - "New code runs git or changes an absolute path to a repository-relative path"
  - "A change calls find_git_root, get_db or load_config"
tags:
  - git-worktree
  - project-root
  - workspace-root
  - get-db-guard
---

# Canonical Project Root vs. Workspace Root

## Context

Issue #247: `ec init` and all hooks used `git rev-parse --show-toplevel` to find the repository. Then they opened `<toplevel>/.entirecontext/db/local.db`.

In a linked worktree, the toplevel is the checkout of that worktree. Thus, each worktree had a separate project and a separate decision corpus. A decision from one worktree was not visible in a different worktree.

Schema v21 uses two roots. `src/entirecontext/core/repo_roots.py` finds the two roots:

- **project_root** — The canonical root. `git rev-parse --git-common-dir` gives this root. For a linked worktree of a regular repository, this root is the main worktree. It contains `local.db`, `config.toml`, `content/` and the pid files. The `projects` row and the `repo_index` entry point to it.
- **workspace_root** — The `--show-toplevel` of the current checkout. All git subprocesses run in this root. All checkout-relative paths start at this root.

For bare repositories with worktrees, `--separate-git-dir` checkouts and submodules, `project_root` is equal to `workspace_root`.

## Guidance

Use the operation of the code to select the root. Do not use the variable name.

| The code... | Use |
|---|---|
| opens a DB, reads or writes config, reads or writes `.entirecontext/*`, or uses a registry key or pid file | `find_project_root()` / `roots.project_root` |
| runs git, changes absolute paths to relative paths, scans checkout files, or restores files | `find_git_root()` / `roots.workspace_root` |
| does git work for a recorded session (auto-apply, auto-checkpoint, post-session assessment) | the `workspace_root` of the session row; if it is NULL, the workspace of the caller |

Entry points:

- `core.project.get_repo_roots()` gives the two roots for the cwd. `find_git_root()` gives the workspace root. `find_project_root()` gives the canonical root.
- `cli.helpers.get_repo_roots_connection()` opens the canonical DB and gives the two roots. `get_repo_connection()` gives the canonical root. Use it for commands that only use the DB.
- Hooks get the roots from `_find_git_root` of their module and from `roots_for_workspace`. `_find_git_root` runs one cached `git rev-parse`. `roots_for_workspace` uses only the filesystem.
- The `PostToolUse` decision hook uses `resolve_repo_roots_fs`, which does not run git. `PostToolUse` turn capture (`turn_capture.on_tool_use`) runs one cached `git rev-parse`.
- Workers use the canonical root for their pid file. They use the workspace as `cwd`.

### Safety net

`get_db()` raises `LinkedWorktreeDatabaseError` if it gets a linked-worktree root. The check does not start a subprocess. It reads `<path>/.git` and the `gitdir` back-pointer of that worktree.

Thus, a call site that uses the wrong root fails with an error. It does not make a second database. Hooks catch exceptions. For a hook, the failure shows as missing capture and a telemetry warning. The worktree hook tests cover each hook.

`tests/test_contract_worktree_roots.py` includes these checks:

- It permits `--show-toplevel` only in `repo_roots.py` and in the `ec-inject.sh` script.
- It runs usual CLI commands in a linked worktree. Then it makes sure that `<worktree>/.entirecontext/db` does not exist.

### Legacy per-worktree databases

Before v21, EntireContext made a database in each linked worktree. `ec status`, `ec init` and `ec doctor` find these databases. They open them read-only (`mode=ro`) and show them. EntireContext does not open them read-write, merge them, copy them or symlink them.

A merge command is not available yet. Until it is available, use `ec decision verify-docs --promote-from <path>`. This command copies only the decisions that `docs/adr`, `docs/specs`, `docs/plans` and `ROADMAP.md` refer to. It accepts a v20 source without a migration, because v21 did not change the tables that it copies.

### Prevention checklist

- [ ] Make sure that new DB or config access uses `project_root`. Do not use `--show-toplevel` directly.
- [ ] Run new git subprocesses in `workspace_root` or in the recorded workspace of the session.
- [ ] Do not add git calls to query paths or `PostToolUse` paths. Read the workspace fields from the session row.
- [ ] For each new hook or command, add a linked-worktree test that uses the `ec_worktree` fixture.
