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

The Model Context Protocol (MCP) software development kit (SDK) 2.0 removed `mcp.server.fastmcp.FastMCP`. It replaced that class with `mcp.server.MCPServer`. Dependabot pull request (PR) #222 relaxed the pin from `<2` to `<3` but changed only `pyproject.toml`. The import path in `server.py` still referenced the old module. As a result, mypy failed with `import-not-found`.

The project had already pinned `mcp>=1.0.0,<2` (Architecture Decision Record (ADR) 0017) as a deliberate stopgap after an unrelated investigation found the break.

## Guidance

1. **Pin first, migrate second.** When a major version breaks imports, pin the current version immediately. Defer the migration to a separate branch. The pin prevents accidental upgrades. The separate branch prevents the migration from blocking unrelated work.

2. **Grep the full blast radius before writing code.** The class name appeared in 8 code files, 2 active documents, and 5 historical documents. A reviewer caught a stale continuous integration (CI) comment that the implementer missed. Run `grep -rn <old-name> src/ tests/ docs/ .github/` before you start. Mark each hit as change or skip.

3. **Rename fallback variables to be class-name-agnostic.** The migration renamed `_FASTMCP_IMPORT_ERROR` to `_MCP_IMPORT_ERROR`. The new name is shorter and remains valid after the next rename. Test patches that reference the old variable name raise `AttributeError` by default. By default, `monkeypatch.setattr` uses `raising=True`, and `mock.patch.object` uses `create=False`. Only `raising=False` or `create=True` silently patches a nonexistent attribute.

4. **Document transitive dependency changes in the ADR.** MCP 2.0 brought `httpx` → `httpx2`, added `opentelemetry-api` and `mcp-types`, and dropped `httpx-sse` and `pydantic-settings`. The diff shows only `uv.lock` changes, but these dependencies affect users whose virtual environments (venvs) overlap.

5. **Scope out historical documents explicitly.** Retrospectives, plans, and superseded ADRs are point-in-time records. Name them in the "do not change" list. This prevents an executor from updating them.

6. **For optional extras, drop the old version.** When users install the dependency with `uv tool install` in isolation, dual-version support (`>=1.0,<3`) adds complexity and gives users no benefit. Pin only to the new major version (`>=2.0.0,<3`).

## Why this matters

A dependabot PR that passes resolution but fails type-check signals that the package moved an import path. An import-path change is the most common breaking change in Python SDK major versions. Treating it as a "just fix the import" task underestimates the blast radius. Variable names, test patches, error messages, CI comments, and documentation all reference the old name.

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
