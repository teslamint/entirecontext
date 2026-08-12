---
title: "fix: _strip_ec_hooks drops pre-existing empty hook groups"
status: reviewed
origin: ROADMAP.md v0.16.0 carry-forward
priority: P2
category: data-loss
created: 2026-08-12
---

## Problem

`_strip_ec_hooks()` in `project_cmds.py:337-355` removes EntireContext commands from Claude settings hook entries, preserving sibling commands. However, it also discards **unrelated** matcher entries whose `hooks` list was already empty (`[]`) before filtering.

### Root cause

```python
if isinstance(inner, list):
    remaining = [h for h in inner if not _is_ec_command(h.get("command", ""))]
    if not remaining:       # ← True for both "became empty" AND "was already empty"
        continue            # ← drops the entry either way
```

When `inner = []` (pre-existing empty), `remaining = []`, `not remaining` is `True`, and the entry is discarded. The code cannot distinguish "we emptied it" from "it was already empty."

### Impact

`_strip_ec_hooks` is called from:
- `project_cmds.py:529` — `ec init` / `ec enable`
- `project_cmds.py:603` — `ec disable`

Any user-owned matcher entry with an empty `hooks` list is silently deleted on every `ec init`, `ec enable`, or `ec disable` invocation.

## Fix

Change line 350 from:

```python
if not remaining:
    continue
```

to:

```python
if inner and not remaining:
    continue
```

This preserves entries where `hooks` was already `[]` (both `inner` and `remaining` are empty, so `inner` is falsy and the condition is `False` → entry kept). Entries where we removed all EC commands still get dropped (inner was non-empty, remaining is empty → condition is `True` → entry skipped).

## Success criteria

1. A regression test in existing `TestStripEcHooks` class (`tests/test_project_cmds.py:160-194`) asserting `"hooks": []` matcher entry survives `_strip_ec_hooks`
2. A disable-path integration test: settings with a single `"hooks": []` entry under `"Stop"` — assert key survives and output says "No EntireContext hooks found"
3. Existing 6 tests in `TestStripEcHooks` continue to pass (no duplication — sibling/all-EC cases already covered)
4. TDD: write tests first, verify failure on current code, then apply fix

Note: two code paths (install via `:529`, disable via `:603`), not three commands.

## Out of scope

- Other v0.16.0 items
- Changes to `_is_ec_hook` or `_is_ec_command`
