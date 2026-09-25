# Concepts

## Lookup pipelines

**Cost domain** — An independently scaling resource dimension within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves candidates, filters them, resolves external identities, and assembles results. Each transition can introduce a separate multiplicative cost.

**Cache identity** — The canonical representation used to decide whether two lookups can reuse one result. It must match the lookup's equivalence rules.

## Git worktrees

**Logical project** — The one EntireContext project shared by every linked worktree of a repository. It is keyed by the Git common dir and lives at the canonical project root (the main worktree), which owns the database, config, content files and the `repo_index` entry. *Avoid: repo, checkout.*

**Workspace** — The checkout an agent is working in: its toplevel, branch and per-worktree git dir. Git operations run in the workspace; each session records the workspace it started in (`sessions.workspace_root`, `git_branch`, `worktree_git_dir`).

**Legacy worktree DB** — A pre-v21 `<worktree>/.entirecontext/db/local.db` created when each worktree was its own project. It is detected and reported read-only, never written, merged, copied or symlinked.

## Cross-repo queries

**Repo warning** — A per-repo failure recorded and returned alongside the results instead of aborting the whole query. One unreachable or corrupt repository degrades the answer rather than failing it.

**Partial cross-repo result** — A result set that is complete for the repositories that answered and silently missing the ones that did not. It is indistinguishable from a complete result unless the accompanying repo warnings are surfaced, which is why surfacing them is a caller's explicit choice.

## Tool provenance

**Install provenance** — The link from an installed artifact back to the source revision it was built from. Absent provenance, an installation cannot be shown to contain any particular change. *Avoid: build lineage.*

**Same-version drift** — Two installations reporting an identical version string while carrying different code, because the version advanced only at release while the source advanced at every commit. Version comparison cannot detect it.

**Executing copy** — The artifact that actually runs when a command is invoked, as distinct from the source that was edited and reviewed. Tests, review, and CI observe the source; hooks and installed commands observe the executing copy.

## Verification contracts

**Fail-closed verification** — A property of a verification command whose overall result fails whenever any required check fails, including failures inside a compound command. A later successful step must not mask an earlier error.
