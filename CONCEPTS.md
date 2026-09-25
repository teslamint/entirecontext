# Concepts

## Lookup pipelines

**Cost domain** — A resource dimension that scales independently within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves and filters candidates, resolves external identities, and assembles results. Each transition can add a separate multiplicative cost.

**Cache identity** — The canonical representation that determines whether two lookups can reuse one result. It must match the lookup's equivalence rules.

## Cross-repo queries

**Repo warning** — A per-repo failure that the query records and returns with the results instead of aborting the whole query. One unreachable or corrupt repository degrades the answer instead of causing the query to fail.

**Partial cross-repo result** — A result set that contains complete results for repositories that answered. It silently omits repositories that did not answer. A caller cannot distinguish it from a complete result unless the caller surfaces the accompanying repo warnings. The caller chooses whether to surface those warnings.

## Tool provenance

**Install provenance** — The link from an installed artifact to the source revision used to build it. Without provenance, no one can show that an installation contains a particular change. *Avoid: build lineage.*

**Same-version drift** — Two installations can report the same version string but contain different code. This happens because the version changes only at release, while the source changes at every commit. Version comparison cannot detect this difference.

**Executing copy** — The artifact that runs when someone invokes a command, distinct from the source that someone edited and reviewed. Tests, review, and CI observe the source. Hooks and installed commands observe the executing copy.

## Verification contracts

**Fail-closed verification** — A verification command fails overall whenever any required check fails, including a failure inside a compound command. A later successful step must not mask an earlier error.
