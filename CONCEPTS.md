# Concepts

## Lookup pipelines

**Cost domain** — An independently scaling resource dimension within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves candidates, filters them, resolves external identities, and assembles results. Each transition can introduce a separate multiplicative cost.

**Cache identity** — The canonical representation used to decide whether two lookups can reuse one result. It must match the lookup's equivalence rules.

## Tool provenance

**Install provenance** — The link from an installed artifact back to the source revision it was built from. Absent provenance, an installation cannot be shown to contain any particular change. *Avoid: build lineage.*

**Same-version drift** — Two installations reporting an identical version string while carrying different code, because the version advanced only at release while the source advanced at every commit. Version comparison cannot detect it.

**Executing copy** — The artifact that actually runs when a command is invoked, as distinct from the source that was edited and reviewed. Tests, review, and CI observe the source; hooks and installed commands observe the executing copy.
