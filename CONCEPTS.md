# Concepts

## Lookup pipelines

**Cost domain** — An independently scaling resource dimension within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves candidates, filters them, resolves external identities, and assembles results. Each transition can introduce a separate multiplicative cost.

**Cache identity** — The canonical representation used to decide whether two lookups can reuse one result. It must match the lookup's equivalence rules.

## Git worktrees

**Logical project** — The one EntireContext project that all linked worktrees of a repository share. The Git common dir identifies it. Its canonical project root is the main worktree. The database, config and content files of the project are at this root. The `repo_index` entry of the project points to this root. *Avoid: repo, checkout.*

**Workspace** — The checkout in which an agent works. A workspace has a toplevel, a branch and a per-worktree git dir. Git operations run in the workspace. Each session records the workspace in which it started (`sessions.workspace_root`, `git_branch`, `worktree_git_dir`).

**Legacy worktree DB** — A `<worktree>/.entirecontext/db/local.db` file from before v21. An earlier version made it when each worktree was a separate project. EntireContext finds it and shows it read-only. EntireContext does not write, merge, copy or symlink it.

## Cross-repo queries

**Repo warning** — A per-repo failure recorded and returned alongside the results instead of aborting the whole query. One unreachable or corrupt repository degrades the answer rather than failing it.

**Partial cross-repo result** — A result set that is complete for the repositories that answered and silently missing the ones that did not. It is indistinguishable from a complete result unless the accompanying repo warnings are surfaced, which is why surfacing them is a caller's explicit choice.

## Tool provenance

**Install provenance** — The link from an installed artifact back to the source revision it was built from. Absent provenance, an installation cannot be shown to contain any particular change. *Avoid: build lineage.*

**Same-version drift** — Two installations reporting an identical version string while carrying different code, because the version advanced only at release while the source advanced at every commit. Version comparison cannot detect it.

**Executing copy** — The artifact that actually runs when a command is invoked, as distinct from the source that was edited and reviewed. Tests, review, and CI observe the source; hooks and installed commands observe the executing copy.

## Verification contracts

**Fail-closed verification** — A property of a verification command whose overall result fails whenever any required check fails, including failures inside a compound command. A later successful step must not mask an earlier error.
