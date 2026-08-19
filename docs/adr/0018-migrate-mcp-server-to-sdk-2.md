# 0018. Migrate MCP Server to SDK 2.0

**Status:** accepted  
**Date:** 2026-08-19  
**Supersedes:** 0017

## Context

ADR 0017 pinned `mcp>=1.0.0,<2` because MCP SDK 2.0.0 removed
`mcp.server.fastmcp.FastMCP`. The pin was a deliberate stopgap; a
migration to the 2.0 API was deferred to a separate release loop.

Dependabot PR #222 attempted to relax the pin to `<3` but failed CI
because `mcp.server.fastmcp` no longer exists in 2.0.

## Decision

1. Replace `from mcp.server.fastmcp import FastMCP` with
   `from mcp.server import MCPServer` in `server.py`.
2. Rename the fallback variable from `_FASTMCP_IMPORT_ERROR` to
   `_MCP_IMPORT_ERROR` (class-name-agnostic).
3. Pin `mcp>=2.0.0,<3` in `pyproject.toml`, dropping 1.x support.
   The `mcp` extra is optional and installed in isolation via
   `uv tool install`, so backwards compatibility is unnecessary.
4. Update coordinated test references in `test_mcp_cmds.py` and
   `test_contract_sync.py`.
5. Update the architecture diagram in `docs/spec.md`.

## Dependency Changes

MCP 2.0.0 changes the transitive dependency tree:

| Added | Removed |
|-------|---------|
| `httpx2` (+ `httpcore2`, `httpx2-jsfetch`) | `httpx-sse` |
| `mcp-types` | `pydantic-settings` |
| `opentelemetry-api` | `python-dotenv` |
| `truststore` | |

The `httpx` → `httpx2` transition follows the broader Python ecosystem
shift. Conflict risk is mitigated by `uv tool install` isolation.

## Consequences

- The MCP server works with `mcp>=2.0.0`.
- `ec mcp serve` stdio transport behavior is unchanged (`mcp.run()`
  defaults to stdio).
- Rollback: revert the pin to `>=1.0.0,<2` and the import to
  `mcp.server.fastmcp.FastMCP`.
- All 28 MCP tool functions use `async def` with the `mcp.tool()(fn)`
  decorator pattern, which is unchanged in SDK 2.0. No tool
  registration code requires modification.
- Future MCP 2.x point releases are accepted by the `<3` upper bound.
  CI (mypy + pytest) guards against regressions.
