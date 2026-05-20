# PR-D0: UserPromptSubmit Hook Contract Spike

Blocking gate for PDI (Proactive Decision Injection, PR-E).
Verifies that `UserPromptSubmit` hook stdout is captured as `additionalContext` by Claude Code.

## Status

- [x] **CONFIRMED** (2026-05-20) — proceed to PR-D / PR-E
- [ ] PENDING (not yet tested)
- [ ] REJECTED — scope PDI to v0.7.1; v0.7.0 = PR-A/B/C only

---

## Probe Script

`scripts/spike_probe.py` — reads stdin (hook protocol), writes probe JSON to stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<SPIKE_PROBE: ...>"
  }
}
```

---

## Registration

Add as a **second** hook entry under `UserPromptSubmit` in `.claude/settings.local.json`.
The existing `ec hook handle` entry stays — add the probe alongside it:

```json
"UserPromptSubmit": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "/Users/teslamint/.local/share/uv/tools/entirecontext/bin/ec hook handle --type UserPromptSubmit",
        "timeout": 5
      },
      {
        "type": "command",
        "command": "uv run --project /Users/teslamint/workspace/entirecontext python scripts/spike_probe.py",
        "timeout": 5
      }
    ]
  }
]
```

---

## Verification Procedure

1. Add probe entry to `settings.local.json` (see Registration above).
2. **Restart Claude Code** (MCP server reload required).
3. Submit any user prompt (e.g., "hello").
4. Check if the string `<SPIKE_PROBE` appears in a `<system-reminder>` or similar injected context in the **same or next turn**.
5. Record result below.

---

## Results

### If CONFIRMED ✓

- Exact JSON key path: `hookSpecificOutput.additionalContext`
- How injected: appears as `<system-reminder>` tag prefixed with `UserPromptSubmit hook additional context:`
- Full string verbatim — no truncation observed
- Verified 2026-05-20: spike probe text appeared in Claude Code system context on next prompt

### If REJECTED

- Did hook stdout emit correctly (check with `echo '{}' | uv run python scripts/spike_probe.py`)?
- Alternatives tested:
  - [ ] Raw markdown stdout (no JSON wrapper)
  - [ ] `output` key instead of `hookSpecificOutput`
  - [ ] `decision` key
- Conclusion: PDI must wait for a confirmed contract or use fallback path only

---

## Decision Gate

| Spike Result | PR-D / PR-E Action |
|---|---|
| CONFIRMED | Proceed: extract `rank_decisions_for_prompt`, implement sync stdout path |
| REJECTED | Defer PDI to v0.7.1; v0.7.0 ships PR-A/B/C only (B1+B2+B3 debt cleanup) |

If rejected but raw markdown stdout works, PR-E can be redesigned to use markdown fallback as the **primary** path — document exact working format here.

---

## Notes

- The `additionalContext` design assumption originates in `docs/superpowers/specs/2026-04-04-decision-hooks-design.md:60`.
- F4 (async worker writing `.entirecontext/decisions-context-prompt-*.md`) was adopted precisely because this contract was unverified at v0.4.0.
- This spike resolves that open assumption before committing 5+ days of PDI work.
