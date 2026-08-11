# Concepts

## Lookup pipelines

**Cost domain** — An independently scaling resource dimension within a pipeline. Bounding one cost domain does not establish a bound on another.

**Lookup pipeline** — A sequence that retrieves candidates, filters them, resolves external identities, and assembles results. Each transition can introduce a separate multiplicative cost.

**Cache identity** — The canonical representation used to decide whether two lookups can reuse one result. It must match the lookup's equivalence rules.
