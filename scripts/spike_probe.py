#!/usr/bin/env python3
"""PR-D0 spike: verify UserPromptSubmit hook stdout → additionalContext contract.

Temporary script. Delete once spike is resolved (see docs/research/v0-7-0-hook-contract-spike.md).

Registration (add as second hook in .claude/settings.local.json):
  {
    "type": "command",
    "command": "uv run --project /path/to/entirecontext python scripts/spike_probe.py",
    "timeout": 5
  }
"""

from __future__ import annotations

import json
import sys

sys.stdin.read()

json.dump(
    {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "<SPIKE_PROBE: If you can read this text in the conversation context, "
                "the UserPromptSubmit→additionalContext contract is CONFIRMED. "
                "EntireContext PR-D0 spike result: PASS.>"
            ),
        }
    },
    sys.stdout,
)
