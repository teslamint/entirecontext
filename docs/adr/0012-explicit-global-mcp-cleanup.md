# 0012. Require Explicit Global MCP Cleanup During Disable

**Status:** accepted
**Date:** 2026-08-17
**EC Decision:** `30f75661-044d-49e3-a434-b3ca93989be1`

## Context

`ec enable` and `ec init` install agent-specific integrations, repository-local Git hooks shared across agent modes, and a user-level MCP registration shared across repositories. The old `ec disable` removed Claude hooks and repository Git hooks only for Claude-oriented modes, removed Codex notify only for Codex-oriented modes, and never removed MCP.

Moving Git hook removal to the shared path is safe because those files belong to the current repository and the ownership guard requires the complete generated hook shape and exact EC command before deletion. MCP differs: `~/.claude/settings.json` is global. A standard entry may serve another repository or a still-active agent integration. It may also have been configured manually using the exact form documented in README, which is indistinguishable from an entry written by EC.

## Decision

Every `ec disable` agent mode removes EntireContext-owned repository Git hooks. Claude hooks and Codex notify remain selected by `--agent`.

Default disable preserves MCP. A new `--remove-mcp` flag is the explicit global cleanup action. Under that flag, EC removes only an exact standard `mcpServers.entirecontext` stdio form: `ec[.exe] mcp serve`, or a Python executable running `-m entirecontext.cli mcp serve`. Sibling servers, unrelated settings, empty containers, and nonstandard `entirecontext` entries remain unchanged.

## Consequences

- Codex-only disable now cleans up the agent-neutral repository Git hooks it installed.
- Users can complete MCP cleanup without editing JSON manually.
- Default disable cannot silently break another repository, another active agent integration, or a standard manual MCP entry.
- A user who requests `--remove-mcp` accepts global removal of a standard entry regardless of whether EC or the user originally wrote it.
- Re-enabling any repository restores the standard MCP entry idempotently.

## Rejected Alternatives

### Remove MCP automatically for every agent mode

Rejected. Generated-shape matching proves syntax, not ownership or whether another consumer remains active.

### Track repository and agent consumers, then remove the last reference

Rejected for this correction. No complete ledger exists for historical installations, so a new ledger cannot safely reconstruct current consumers and would create false last-owner decisions.

### Keep MCP removal manual only

Rejected. An explicit CLI flag can provide deterministic cleanup while preserving the safe default.

## References

- Specification: [`docs/specs/2026-08-16-symmetric-disable-lifecycle-design.md`](../specs/2026-08-16-symmetric-disable-lifecycle-design.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- Preceding Git-hook decision: `f3dde400-139f-485b-ba39-9c4f5ff11fd3`
- Refined unsafe default-removal decision: `3b185ad5-d2de-4425-99c1-b1f016dc5042`
