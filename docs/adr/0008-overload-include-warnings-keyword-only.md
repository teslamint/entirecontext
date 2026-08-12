# 0008. Keyword-Only `Literal[True]` Overloads for `include_warnings`

**Status:** accepted
**Date:** 2026-08-12

## Context

The eleven public `cross_repo_*` functions return
`X | tuple[X, list[WarningEntry]]` depending on the `include_warnings`
argument. mypy cannot resolve that union from a literal argument, so every
typed caller needed a `cast` workaround. Four such casts existed in the MCP
tools, and every future caller would have needed one.

Declaring `@overload` pairs keyed on `Literal[False]` / `Literal[True]` fixes
this, but the two stubs can be written in more than one legal form. A scratch
measurement (spec, Architecture section) showed that a `Literal[True]` stub
with a `= ...` default makes a no-argument call match both stubs, so overload
resolution then depends on stub order across eleven near-identical pairs.

## Decision

Each function declares exactly two stubs. The `Literal[False]` stub keeps
`include_warnings` positional with a `...` default, preserving all existing
call forms. The `Literal[True]` stub places a bare `*` before
`include_warnings` and gives it no default, making the warnings-requesting
form keyword-only.

Consequence accepted deliberately: mypy now rejects positional
`include_warnings=True` calls (for example `cross_repo_rewind("x", None, True)`)
that the previous `bool` signature admitted. This is a typing-contract
narrowing only -- the implementations still accept any boolean at runtime. A
repository-wide search found zero positional or non-literal call sites before
the change, and the distributed package ships no `py.typed` marker, so no
external typed caller consumes these stubs.

Rejected alternatives:

- `Literal[True]` stub with a `= ...` default -- type-checks, but makes
  resolution stub-order-dependent (measured, not assumed).
- A third `bool` fallback stub returning the union -- supports computed-flag
  callers, but no such caller exists in the package, and it would reintroduce
  the union those callers would again need to `cast` away. Revisit if
  `py.typed` is ever added.
- Overloading `_return_with_warnings` itself -- internal-only cleanup with no
  caller-visible effect (spec Open Decision D1); the seven forwarding call
  sites pass `include_warnings` positionally and would need conversion first.

## Consequences

- Typed callers get precise return types from a literal `include_warnings`;
  the four MCP `cast` workarounds are deleted and the package-wide `cast(`
  count is zero.
- The keyword-only `True` arm keeps overload resolution independent of stub
  order across all eleven pairs.
- Anyone adding a computed-flag caller must either branch on the flag or add
  the `bool` fallback stub described above.
- Spec: `docs/specs/2026-08-12-cross-repo-overload-design.md`;
  plan: `docs/plans/2026-08-12-001-refactor-cross-repo-overload-plan.md`
  (PR #217).
