---
module: mcp-server
date: 2026-08-19
problem_type: tooling_decision
component: mcp-server
severity: medium
applies_when:
  - "An optional SDK dependency ships a major version with breaking import paths"
  - "Dependabot opens a PR that passes lock-file resolution but fails type-check or import"
  - "The project uses a try/except ImportError pattern for an optional dependency"
tags:
  - mcp
  - sdk-migration
  - optional-dependency
  - breaking-change
  - dependabot
---

# Migrating an optional SDK across a major version break

## Context

MCP SDK 2.0 removed `mcp.server.fastmcp.FastMCP` and replaced it with
`mcp.server.MCPServer`. Dependabot PR #222 relaxed the pin from `<2` to `<3`
but only touched `pyproject.toml` — the import path in `server.py` still
referenced the old module, so mypy failed with `import-not-found`.

The project had already pinned `mcp>=1.0.0,<2` (ADR 0017) as a deliberate
stopgap after discovering the break during an unrelated investigation.

## Guidance

1. **Pin first, migrate second.** When a major version breaks imports, pin
   the current version immediately and defer the migration to a separate
   branch. The pin prevents accidental upgrades; the separate branch
   prevents the migration from blocking unrelated work.

2. **Grep the full blast radius before writing code.** The class name
   appeared in 8 code files, 2 active docs, and 5 historical docs. A
   reviewer caught a stale CI comment that the implementer missed. Run
   `grep -rn <old-name> src/ tests/ docs/ .github/` and classify every hit
   as change/skip before starting.

3. **Rename fallback variables to be class-name-agnostic.**
   `_FASTMCP_IMPORT_ERROR` was renamed to `_MCP_IMPORT_ERROR` — shorter and
   survives the next rename. Test patches that reference the old variable
   name break silently (they patch a nonexistent attribute and the original
   fallback stays `None`).

4. **Document transitive dependency changes in the ADR.** MCP 2.0 brought
   `httpx` → `httpx2`, added `opentelemetry-api` and `mcp-types`, dropped
   `httpx-sse` and `pydantic-settings`. These are invisible in the diff
   (only `uv.lock` changes) but affect users whose venvs overlap.

5. **Scope out historical documents explicitly.** Retros, plans, and
   superseded ADRs are point-in-time records. Name them in the "do not
   change" list so an executor does not update them.

6. **For optional extras, drop the old version.** When the dependency is
   installed via `uv tool install` in isolation, dual-version support
   (`>=1.0,<3`) adds complexity for no user benefit. Pin to the new major
   only (`>=2.0.0,<3`).

## Why this matters

A dependabot PR that passes resolution but fails type-check is a signal
that the package moved an import path — the most common breaking change in
Python SDK major versions. Treating it as a "just fix the import" task
underestimates the blast radius: variable names, test patches, error
messages, CI comments, and documentation all reference the old name.

## When to apply

- A dependabot or renovate PR bumps a major version and fails CI.
- A `try/except ImportError` pattern guards an optional dependency.
- An ADR records a version pin that is now ready to be lifted.

## Examples

```python
# Before (SDK 1.x)
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("entirecontext")

# After (SDK 2.0)
from mcp.server import MCPServer
mcp = MCPServer("entirecontext")

# Decorator API unchanged
mcp.tool()(fn)
mcp.run()  # stdio default preserved
```
