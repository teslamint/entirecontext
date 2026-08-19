# 0017. Pin MCP Extra Below 2.0 and Raise on Missing SDK

**Status:** superseded-by-0018  
**Date:** 2026-08-19  
**EC Decision:** `4676448c-f2b8-4f2c-b2f5-9d75862b26e8`

## Context

`ec mcp serve` was failing silently across all registered repositories. The
installed `entirecontext` uv tool venv had drifted from `pyproject.toml`: the
`mcp` extra was declared, but the venv contained no MCP SDK. Reinstalling from
the local checkout resolved the immediate symptom.

Two code-level defects made the next environmental drift just as hard to
diagnose:

1. `src/entirecontext/cli/mcp_cmds.py` wrapped both the import of
   `run_server` **and** the call to `run_server()` inside the same
   `try/except ImportError`. Any `ImportError` raised inside `run_server()`
   was reported as "install the extra", hiding the real cause.
2. `src/entirecontext/mcp/server.py` printed the same message to **stdout**
   and returned, so the process exited 0 and polluted the stdio JSON-RPC
   stream.

While investigating, `mcp==2.0.0` was installed. That release removed
`mcp.server.fastmcp.FastMCP` in favor of `mcp.server.MCPServer`, so the
existing server code would not import even after reinstalling with the extra.

## Decision

1. Pin the `mcp` extra in `pyproject.toml` to `mcp>=1.0.0,<2` so the current
   `FastMCP`-based server keeps working.
2. In `src/entirecontext/mcp/server.py`, capture the original `ImportError`
   in `_FASTMCP_IMPORT_ERROR` and replace `print(...)` + `return` with
   `raise RuntimeError(...) from _FASTMCP_IMPORT_ERROR`. This produces a
   non-zero exit code, keeps stdout clean, and preserves the original error
   for diagnosis.
3. In `src/entirecontext/cli/mcp_cmds.py`, narrow the `try/except ImportError`
   to the import statement only, call `run_server()` outside it, and route
   diagnostics to stderr via `Console(stderr=True)`.
4. Add regression tests covering the SDK-missing raise, `ImportError`
   propagation, no duplicate message, and stdout purity.

A full migration to the MCP 2.0 `MCPServer` API is explicitly deferred to a
separate loop.

## Consequences

- `ec mcp serve` now fails loudly and informatively when the SDK is missing,
  instead of silently exiting 0.
- Internal `ImportError`s inside `run_server()` propagate with their original
  traceback, rather than being mislabeled as missing-extra failures.
- stdout stays JSON-RPC-clean on every failure path.
- Future MCP SDK major-version upgrades require an intentional migration loop;
  they will not break existing installs unexpectedly.
