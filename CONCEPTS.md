# Concepts

## Lookup pipelines

**Cost domain** — A resource dimension that scales independently within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves and filters candidates, resolves external identities, and assembles results. Each transition can add a separate multiplicative cost.

**Cache identity** — The canonical representation that determines whether two lookups can reuse one result. It must match the lookup's equivalence rules.

## Git worktrees

**Logical project** — The one EntireContext project that all linked worktrees of a repository share. The Git common dir identifies it. Its canonical project root is the main worktree. The database, config and content files of the project are at this root. The `repo_index` entry of the project points to this root. *Avoid: repo, checkout.*

**Workspace** — The checkout in which an agent works. A workspace has a toplevel, a branch and a per-worktree git dir. Git operations run in the workspace. Each session records the workspace in which it started (`sessions.workspace_root`, `git_branch`, `worktree_git_dir`).

**Legacy worktree DB** — A `<worktree>/.entirecontext/db/local.db` file from before v21. An earlier version made it when each worktree was a separate project. EntireContext finds it and shows it read-only. EntireContext does not write, merge, copy or symlink it.

## Cross-repo queries

**Repo warning** — A per-repo failure that the query records and returns with the results instead of aborting the whole query. One unreachable or corrupt repository degrades the answer instead of causing the query to fail.

**Partial cross-repo result** — A result set that contains complete results for repositories that answered. It silently omits repositories that did not answer. A caller cannot distinguish it from a complete result unless the caller surfaces the accompanying repo warnings. The caller chooses whether to surface those warnings.

## Tool provenance

**Install provenance** — The link from an installed artifact to the source revision used to build it. Without provenance, no one can show that an installation contains a particular change. *Avoid: build lineage.*

**Same-version drift** — Two installations can report the same version string but contain different code. This happens because the version changes only at release, while the source changes at every commit. Version comparison cannot detect this difference.

**Executing copy** — The artifact that runs when someone invokes a command, distinct from the source that someone edited and reviewed. Tests, review, and CI observe the source. Hooks and installed commands observe the executing copy.

## Verification contracts

**Fail-closed verification** — A verification command fails overall whenever any required check fails, including a failure inside a compound command. A later successful step must not mask an earlier error.
