# Retrospective: `ec mcp serve` Silent Failure Fix

**Date:** 2026-08-19  
**Feature:** fix-mcp-serve-silent-failure  
**Loop:** release-loop  
**PRs:** #228 (fix), #229 (ADR), #230 (ROADMAP carry-forward)

## Success Criteria (from plan)

1. No MCP SDK env: `ec mcp serve` → nonzero exit, stderr contains real `ImportError`/`RuntimeError` message, stdout clean. ✅ Verified by code path and regression tests.
2. With MCP SDK: `ec mcp serve` → stderr `[ec-mcp] starting v<version>`, `tools/list` returns 29 `ec_*` tools. ✅ Empirically verified with mcp 1.29.0; 25,846-byte tools/list payload.
3. `run_server()` internal `ImportError` propagates unmodified. ✅ Regression test `test_run_server_import_error_propagates` passes.
4. "MCP not available" phrase appears only once in codebase. ✅ Grep shows zero occurrences; the message was replaced by a `RuntimeError` with install guidance.

## What happened

- The installed `entirecontext` uv tool venv had drifted: `pyproject.toml` declared the `mcp` extra, but the venv contained no MCP SDK. Reinstalling from the local checkout resolved that environmental symptom.
- `src/entirecontext/cli/mcp_cmds.py` wrapped the `run_server()` call inside the same `try/except ImportError` that guarded the import, so any internal `ImportError` was misreported as "install the extra".
- `src/entirecontext/mcp/server.py` printed the same message to stdout and returned, causing exit code 0 and polluting the stdio JSON-RPC stream.
- During investigation, `mcp==2.0.0` was installed. That release removed `mcp.server.fastmcp.FastMCP`, so the server could not import even with the extra. We pinned `mcp>=1.0.0,<2`.

## Changes made

- `src/entirecontext/cli/mcp_cmds.py`: narrowed try/except to import only, moved `run_server()` outside, switched diagnostics to `stderr`, added install hint.
- `src/entirecontext/mcp/server.py`: captured original `ImportError` in `_FASTMCP_IMPORT_ERROR`, replaced `print()`+`return` with `raise RuntimeError(...) from _FASTMCP_IMPORT_ERROR`.
- `pyproject.toml`: pinned `mcp` extra to `>=1.0.0,<2`.
- `tests/test_mcp_cmds.py`: added/updated regression tests for import error, success, `ImportError` propagation, SDK-missing raise, and no duplicate message.
- `docs/adr/0017-pin-mcp-extra-below-2.md`: recorded the decision.
- `ROADMAP.md`: registered MCP SDK 2.0 migration as a carry-forward item.

## Verification

- `uv run ruff check .` — pass
- `uv run ruff format --check .` — pass
- `uv run mypy src` — pass
- `uv run pytest tests/test_mcp_cmds.py tests/test_mcp.py -q` — 127 passed
- `uv run pytest -q` — 2297 passed, 1 skipped
- CI on PR #228: all required checks passed, CodeRabbit approved.
- Empirical stdio test: 29 `ec_*` tools, 25,846-byte `tools/list` payload, exit 0, stdout 0 bytes, stderr showed `[ec-mcp] starting v0.14.0`.

## Decisions recorded

- EC decision `4676448c-f2b8-4f2c-b2f5-9d75862b26e8`: pin `mcp<2` and raise on missing SDK.
- ADR 0017: same decision with context/consequences.

## Carry-forward

- **MCP SDK 2.0 migration** added to `ROADMAP.md` Hardening Backlog as a P3 item. A separate release-loop should migrate the server from `mcp.server.fastmcp.FastMCP` to `mcp.server.MCPServer` (or the new high-level API) before relaxing the pin.

## Lessons / observations

1. **Environmental drift is a real failure mode.** The venv contents drifted from the declared extra. The code fix prevents misdiagnosis next time, but a future `ec doctor` self-check that verifies the MCP SDK import is worth considering (the original plan listed this as step 4 to review, not implement; it remains unimplemented and is now tied to the carry-forward migration rather than this bug-fix loop).
2. **stdout purity matters for stdio transports.** The original `print()` to stdout would have corrupted any JSON-RPC client reading the stream. The fix routes all failure diagnostics to stderr.
3. **Version pins should react to breaking major releases immediately.** Waiting for an unbounded `mcp>=1.0.0` allowed a silent major-version breakage. The pin and the migration carry-forward make the dependency state explicit.

## Outcome

All success criteria met. Loop complete.
