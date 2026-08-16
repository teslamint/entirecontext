# 0011. Stamp Distribution Builds with a Hatchling Hook

**Status:** accepted
**Date:** 2026-08-16
**EC Decision:** `edfd67be-253f-46a9-93ce-3b41f37e222e`

## Context

EntireContext's agent hooks execute the separately installed `ec` command. In the incident recorded by the 2026-08-12 hook-installation retrospective, that installed copy predated a shipped fix and regenerated `LESSONS.md` with stale code. Both the checkout and installed copy reported version `0.14.0`, so version comparison could not detect the drift.

The current `uv_build` backend deliberately does not support build scripts. Adding a Git-derived artifact requires either a more extensible backend, a custom PEP 517 wrapper that mutates source files or rewrites archives, or an external pre-build step that can be skipped.

A package build SHA is meaningful only against the EntireContext source checkout. Comparing it with the HEAD of an unrelated consumer repository would always produce a false mismatch.

## Decision

Use Hatchling with a custom build hook. Immediately before wheel or source-distribution assembly, the hook accepts Git provenance only when the build root is the repository top level, resolves the full Git SHA and tracked-worktree dirty state, writes a temporary Python module outside the project tree, and injects it through `build_data["force_include"]`. It does not rewrite tracked source files or duplicate the stamped sdist member when the output directory is inside the project.

Source distributions carry the generated module. When a wheel is built from an unpacked source distribution without its own `.git`—including below an unrelated Git working tree—the hook preserves only validated, unambiguous SHA and dirty-state literals already in that module. A build root that is itself a Git repository but has no resolvable `HEAD` remains unavailable rather than reusing an old stamp. A tracked fallback module exposes unavailable provenance for editable/source execution.

`ec doctor` compares the stamp with `git rev-parse HEAD` only when its target is the EntireContext source checkout and the running module is not that checkout's own source. It warns when provenance is unavailable, dirty, or mismatched. Consumer repositories skip this comparison.

Rejected alternatives:

- Keep `uv_build` behind a custom PEP 517 wrapper: this either mutates the source tree during builds or requires bespoke wheel/sdist and `RECORD` rewriting.
- Compare `__version__`: the motivating drift had identical versions.
- Make repository hooks invoke `uv run ec`: this adds startup cost and changes behavior for every user to solve a developer-install problem.
- Require an external pre-build generation command: callers can bypass it, so the artifact contract would not be enforced by the build itself.

## Consequences

- Wheel and source-distribution artifacts have commit-level provenance without dynamic package versioning.
- Dirty local builds remain possible but are explicitly unverifiable in `ec doctor`.
- Downstream builds from official source distributions retain the original provenance.
- The build backend changes from `uv_build` to Hatchling and adds one build-time dependency plus a repository-local hook.
- Diagnostics avoid false positives in repositories that merely consume EntireContext.
- Future build-backend changes must preserve the generated module contract or explicitly supersede this ADR.

## References

- Spec: [`docs/specs/2026-08-16-build-sha-provenance-design.md`](../specs/2026-08-16-build-sha-provenance-design.md)
- Plan: [`docs/superpowers/plans/2026-08-16-003-build-sha-provenance-plan.md`](../superpowers/plans/2026-08-16-003-build-sha-provenance-plan.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- Incident solution: [`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md`](../solutions/developer-experience/installed-tool-drifts-from-checkout.md)
