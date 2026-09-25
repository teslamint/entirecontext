---
module: repository-resolution
date: 2026-09-25
problem_type: workflow_issue
component: repo-roots
severity: high
applies_when:
  - "Adding a CLI command, hook, MCP tool or worker that opens the database or reads config"
  - "Adding code that runs git or turns an absolute path into a repository-relative one"
  - "Reviewing a change that calls find_git_root, get_db or load_config"
tags:
  - git-worktree
  - project-root
  - workspace-root
  - get-db-guard
---

# Canonical Project Root vs. Workspace Root

## Context

Issue #247: `ec init` and every hook resolved the repository with `git rev-parse --show-toplevel` and opened `<toplevel>/.entirecontext/db/local.db`. In a linked worktree the toplevel is the worktree's own checkout, so each worktree got its own project and its own decision corpus. Decisions recorded in one worktree were invisible from another.

Schema v21 splits the single "repo root" into two roots, both resolved in `src/entirecontext/core/repo_roots.py`:

- **project_root** — the canonical root, derived from `git rev-parse --git-common-dir`. For a linked worktree of a regular repository it is the main worktree. It owns `local.db`, `config.toml`, `content/`, pid files, the `projects` row and the `repo_index` entry.
- **workspace_root** — the current checkout's `--show-toplevel`. It owns every git subprocess and every checkout-relative path.

Bare repositories with worktrees, `--separate-git-dir` and submodules keep `project_root == workspace_root`.

## Guidance

Classify each call site by what it does, not by the variable name:

| The code... | Use |
|---|---|
| opens a DB, loads or saves config, reads or writes `.entirecontext/*`, keys a registry or pid file | `find_project_root()` / `roots.project_root` |
| runs git, relativizes absolute paths, scans checkout files, restores files | `find_git_root()` / `roots.workspace_root` |
| does git work for a recorded session (auto-apply, auto-checkpoint, post-session assessment) | the session row's `workspace_root`, falling back to the caller's workspace |

Entry points:

- `core.project.get_repo_roots()` returns both roots for the cwd. `find_git_root()` keeps its workspace meaning; `find_project_root()` returns the canonical root.
- `cli.helpers.get_repo_roots_connection()` opens the canonical DB and returns the roots. `get_repo_connection()` returns the canonical root and is for DB-only commands.
- Hooks derive roots from their module's `_find_git_root` (one cached `git rev-parse`) plus `roots_for_workspace`, a filesystem-only mapping. The `PostToolUse` decision hook uses `resolve_repo_roots_fs`, which never runs git; `PostToolUse` turn capture (`turn_capture.on_tool_use`) still makes the one cached `git rev-parse` probe.
- Workers take the canonical root for their pid file and the workspace as `cwd`.

### Safety net

`get_db()` raises `LinkedWorktreeDatabaseError` when handed a linked-worktree root. The check is a stat of `<path>/.git` plus reading the gitdir and commondir files, with no subprocess. A missed call site fails loudly instead of silently creating a second database. Hooks swallow exceptions, so a missed hook site shows up as missing capture plus a telemetry warning; the worktree hook tests cover each hook.

`tests/test_contract_worktree_roots.py` forbids `--show-toplevel` outside `repo_roots.py` and the `ec-inject.sh` script, and runs common CLI commands from a linked worktree to check that no `<worktree>/.entirecontext/db` appears.

### Legacy per-worktree databases

Databases created inside linked worktrees before v21 are detected and reported read-only (`mode=ro`) by `ec status`, `ec init` and `ec doctor`. They are never opened read-write, copied in place or symlinked. `ec decision verify-docs --promote-from <path>` copies only the decisions referenced in `docs/adr`, `docs/specs`, `docs/plans` and `ROADMAP.md`; it accepts a v20 source without migrating it, because v21 changed none of the promoted tables.

`ec project merge-worktree <path>` merges the whole database. It opens the source read-only, accepts v20 and v21, and is a dry run unless `--apply` is given. The dry run executes the row merge in a rolled-back transaction, so its report matches the apply. `--apply` writes SQLite backup-API snapshots of both databases to `.entirecontext/backups/`, copies content files with an md5 check, and inserts rows in one transaction. Inserts omit `rowid`, so the FTS triggers index each row under a new canonical rowid. Same-id rows with different values are reported as divergent and keep the canonical values. The stale global `repo_index` row is removed only after the commit. The source file stays in place for the user to delete.

### Prevention checklist

- [ ] New DB or config access resolves `project_root`, never a raw `--show-toplevel`.
- [ ] New git subprocesses run in `workspace_root` (or the session's recorded workspace).
- [ ] New query and `PostToolUse` paths do not add git calls; read workspace fields from the session row.
- [ ] Add a linked-worktree test using the `ec_worktree` fixture for any new hook or command.
