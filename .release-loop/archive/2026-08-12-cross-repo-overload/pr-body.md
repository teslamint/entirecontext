## Purpose

Close ROADMAP v0.16.0's `@overload` row: the eleven `cross_repo_*` functions in
`src/entirecontext/core/cross_repo.py` return `X | tuple[X, list[WarningEntry]]`
depending on `include_warnings`, a shape mypy cannot resolve from a literal
argument. This PR declares `@overload` variants keyed on `Literal[False]` /
`Literal[True]` and deletes the four MCP `cast` workarounds that shape forced.
No runtime behavior changes.

## Key changes

- `core/cross_repo.py`: 22 `@overload` stubs across the eleven functions
  (7 `list[dict]`, 3 `dict | None`, 1 bare `dict`). The `Literal[True]` stubs
  are keyword-only (bare `*`) with no default, so a no-argument call resolves
  unambiguously to the `Literal[False]` arm.
- `mcp/tools/search.py`, `mcp/tools/session.py` (x2), `mcp/tools/checkpoint.py`:
  the four `cast(...)` workarounds and their comments deleted; `cast` dropped
  from each `typing` import. Package-wide `cast(` count is now zero.
- `ROADMAP.md:360` marked complete; `CONCEPTS.md` gains the Cross-repo queries
  vocabulary cluster (repo warning, partial cross-repo result).

Spec: `docs/specs/2026-08-12-cross-repo-overload-design.md` (approved)
Plan: `docs/plans/2026-08-12-001-refactor-cross-repo-overload-plan.md` (approved, seal intact)

## Test evidence

- `uv run mypy src/entirecontext/` -> Success: no issues found in 120 source files
- `uv run pytest -q` -> 2183 passed, 1 skipped (identical to the `94291a4` baseline)
- `uv run ruff check .` -> All checks passed
- Non-vacuity: deleting only `cross_repo_rewind`'s two stubs makes mypy fail at
  `mcp/tools/checkpoint.py:107` (`"None" object is not iterable`); restoring
  them returns Success -- the overloads are load-bearing, not inert.
- Positional rejection: `cross_repo_rewind("x", None, True)` in a scratch module
  -> `No overload variant ... matches argument types "str", "None", "bool"`.
- Review: four-lane review (correctness/tests/architecture/standards) plus an
  independent codex pass -- zero findings.

Note: `entirecontext.core.cross_repo` itself remains in the pre-existing
grandfathered `ignore_errors` override (pyproject.toml, 2026-06-09); nothing was
reintroduced by this change, and enforcement happens at the strict-checked
callers, as the non-vacuity check demonstrates.
