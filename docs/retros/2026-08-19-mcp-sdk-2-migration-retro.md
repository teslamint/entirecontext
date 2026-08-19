# Retrospective: MCP SDK 2.0 Migration

**Date:** 2026-08-19
**PR:** #233
**Merge commit:** `2ce9805c`
**ADR:** 0018 (supersedes 0017)

## What shipped

Migrated the EntireContext MCP server from `mcp.server.fastmcp.FastMCP`
(SDK 1.x) to `mcp.server.MCPServer` (SDK 2.0). Pin changed from
`mcp>=1.0.0,<2` to `mcp>=2.0.0,<3`.

## What went well

1. **Narrow blast radius.** The migration touched only import paths and
   variable names — the `mcp.tool()(fn)` decorator API is unchanged in
   SDK 2.0, so all 28 tool registrations required zero modification.

2. **Independent design review caught 3 scope gaps.** The critic found
   incomplete `server.py` enumeration, missing verification protocol,
   and unassessed dependency landscape — all addressed before
   implementation started.

3. **Independent code review caught CI comment.** A stale FastMCP
   comment in `.github/workflows/ci.yml` was doubly outdated (class
   rename + mypy override removal). Would have been a documentation
   inconsistency if shipped.

4. **Full test suite passed on first run.** 2297 tests, mypy 125 files
   clean, CI 12/12 — no regressions from the dependency tree change.

## What could improve

1. **Dependabot PR handling.** PR #222 sat open with a failing
   type-check while the migration was done separately. A process for
   "close dependabot PR, open migration PR" would reduce noise. The
   dependabot PR should now be closed since the migration is complete.

2. **MCP 2.0 is a .0 release.** Only one version exists (`2.0.0`). CI
   guards against regressions from future 2.x point releases, but
   there is no history to gauge stability. Worth noting for future
   dependency bumps.

## Carry-forward items

1. **Close PR #222** — dependabot bump is now superseded by PR #233.
2. **`_FakeMCP` test helper rename** — LOW priority, class name in
   `test_contract_sync.py` still says `_FakeMCP` while docstrings say
   `MCPServer`. No functional impact.

## Lessons

- **ADR chain works.** 0017 (pin) → 0018 (migrate) maintained decision
  traceability from stopgap to resolution. The supersedes relationship
  makes it clear why the pin existed and when it was lifted.
- **Transitive dependency changes matter.** `httpx` → `httpx2` is a
  significant ecosystem shift. Documenting it in the ADR prevents
  surprise when users see unfamiliar packages in their venv.
