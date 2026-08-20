# 0019. Defer `py.typed` Marker Until Stable

**Status:** accepted
**Date:** 2026-08-20
**EC Decision:** `deb37aa7-2f76-417e-8164-ca83448d1391`

## Context

The package ships `@overload` stubs for the eleven `cross_repo_*`
`include_warnings` functions (ADR 0008) and enforces `mypy --strict` in CI.
However, no `py.typed` marker is included in the distribution, so `mypy`
skips the installed package entirely (`import-untyped`) and no external
typed caller consumes the public signatures.

The question is whether to add `py.typed` now or defer it.

## Decision

Defer shipping `py.typed` until the package reaches stable status
(`Development Status :: 5 - Production/Stable`).

## Rationale

1. **No external typed consumers exist.** The package is alpha
   (`Development Status :: 3 - Alpha`). All typed call sites are internal
   (four MCP modules, CLI commands). Adding the marker exposes a typing
   contract with zero current consumers.

2. **The typing surface is still evolving.** ADR 0008 deliberately
   rejected a `bool` fallback stub for `include_warnings` because no
   computed-flag caller exists. Shipping `py.typed` would commit that
   rejection externally — if a future release adds the fallback, external
   callers that relied on the two-stub contract would break.

3. **Alpha semver permits breaking changes.** While the package is alpha,
   internal typing decisions can change freely. Adding `py.typed` creates
   an external compatibility contract that conflicts with alpha-stage
   flexibility.

4. **Cost of deferral is near zero.** Internal callers already get full
   type checking via `MYPYPATH=src` and CI enforcement. No user has
   requested typed imports.

## Rejected alternatives

- **Ship `py.typed` now** — creates an external contract with zero
  consumers and constrains alpha-stage typing evolution for no benefit.
- **Ship `py.typed` with a "typing is provisional" notice** — PEP 561
  has no provisional concept; the marker is binary. A README disclaimer
  does not prevent downstream breakage.

## Consequences

- `mypy` skips the installed distribution; typed callers must use
  source-path configuration (`MYPYPATH` or editable install).
- The `bool` fallback stub question (ADR 0008) remains internal-only
  and can be revisited without external breakage.
- When the package reaches stable, adding `py.typed` becomes a
  deliberate feature with its own ADR evaluating the typing surface.

## Revisit conditions

- The package status changes to `Development Status :: 5 - Production/Stable`.
- An external consumer requests typed imports.
- A downstream package depends on `entirecontext` with `mypy` enforcement.

## References

- ADR 0008: keyword-only `Literal[True]` overloads for `include_warnings`
- ROADMAP v0.16.0: "Decide whether to ship `py.typed`"
