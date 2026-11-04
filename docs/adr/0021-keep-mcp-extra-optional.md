# 0021. Keep the MCP Extra Optional

**Status:** accepted  
**Date:** 2026-11-04  
**Issue:** #263

## Context

`pyproject.toml` declares the MCP SDK as the optional `mcp` extra.
The default `ec init` command registers the MCP server (`ec mcp serve`).
So the default setup needs `entirecontext[mcp]`.

Issue #263 asked whether the default install must work without this extra.
It listed three options:

1. Move `mcp` into the base dependencies.
2. Keep `mcp` optional, and make `ec init` register the MCP server only when the SDK imports.
3. Keep the current behavior, and document `[mcp]` as required for the default setup.

We measured the install cost on 2026-11-04 with fresh Python 3.13 virtual environments built from the checkout:

| Install | Packages | site-packages |
|---|---|---|
| `entirecontext` | 16 | 16 MB |
| `entirecontext[mcp]` | 42 | 43 MB |

Option 1 adds 26 packages and 27 MB to every install.
This includes `uv add entirecontext` into a user's own project, where no tool isolation exists.
ADR 0018 accepted the `httpx2` migration of MCP SDK 2.x because `uv tool install` isolates the extra.
Option 1 removes that isolation.

Option 2 changes `ec init` behavior.
It also needs a CLI guide for agents without MCP, because two of the four templates in `docs/templates/` name MCP tools.

Hooks run through `ec hook handle` and do not use MCP.
Session capture and prompt-time decision injection work without the extra.

## Decision

Keep the `mcp` extra optional (option 3).

- `README.md` names `[mcp]` in every install command and states that the default `ec init` needs it.
- Every install and reinstall hint that the CLI prints names the extra: `'entirecontext[mcp]'` for a package install, `'.[mcp]'` for a source checkout (#262).
- `ec init --no-hooks` stays the documented path for a setup without MCP registration.

## Consequences

- The base install stays at 16 packages, and MCP SDK transitive dependencies stay out of user projects that do not need them.
- A user who skips `[mcp]` and runs the default `ec init` still gets an MCP registration that fails at server start.
  The failure message of `ec mcp serve` names the install command for both install forms.
- Option 2 stays open.
  A later ADR can supersede this one if users report that broken registration as a real problem.
