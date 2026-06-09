# 0002. Gradual mypy Strict Adoption

**Status:** accepted
**Date:** 2026-06-09

## Context

The codebase has 111 Python source files. 79 of them (71%) fail mypy `--strict` due to
missing type annotations and `Any` usage accumulated over organic development. Adding
type annotations to all 79 modules in one pass would be a large, risky change.

## Decision

Enable mypy strict mode globally. Grandfather the 79 failing modules via
`[[tool.mypy.overrides]]` with `ignore_errors = true`. New files are strict from day one.

The override list in `pyproject.toml` is the single source of truth for legacy debt.
To annotate a module: remove it from the list, run mypy, fix errors, commit.

## Consequences

- New code is strictly typed from the start — no regression.
- Legacy modules can be annotated incrementally without blocking other work.
- The override list is visible, countable, and shrinks monotonically.
- `ignore_errors = true` silences ALL mypy diagnostics in grandfathered modules, including potential real bugs. Accepted trade-off: fixing those modules is the remedy.
