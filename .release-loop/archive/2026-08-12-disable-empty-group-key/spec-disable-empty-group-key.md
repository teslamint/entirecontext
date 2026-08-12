---
title: "fix: disable deletes empty group keys when sibling group triggers rewrite"
status: reviewed
origin: PR #218 code review, registered in ROADMAP.md v0.16.0
priority: P2
category: data-loss
created: 2026-08-12
---

## Problem

`disable()` in `project_cmds.py:607-610` deletes hook type keys whose value is an empty list `[]`, even when no EntireContext commands were removed from them. When a sibling group in the same file triggers `path_changed = True`, the file is rewritten without the empty group key.

### Root cause

```python
if filtered:           # line 607
    hooks[hook_name] = filtered
else:                  # line 609
    del hooks[hook_name]  # line 610 — deletes even if original was already []
```

When `original = []` and `filtered = []`: `filtered != original` is False (no EC change), but `if filtered:` is False (empty list is falsy), so `del hooks[hook_name]` runs. The deletion doesn't trigger a file write by itself (`path_changed` stays False), but if another group in the same file does trigger `path_changed = True`, the file is rewritten without the empty group key.

### Concrete scenario

```json
{"hooks": {"PreToolUse": [], "Stop": [{"matcher":"","hooks":[{"command":"ec hook handle --type Stop"}]}]}}
```

After `ec disable`:
1. `"PreToolUse"`: `filtered = []`, `filtered != original` → False, but `del hooks["PreToolUse"]` runs
2. `"Stop"`: EC entry removed, `path_changed = True`
3. File rewritten as `{"hooks": {}}` — `"PreToolUse"` silently lost

## Fix

Change lines 607-610 from:

```python
if filtered:
    hooks[hook_name] = filtered
else:
    del hooks[hook_name]
```

to:

```python
if filtered:
    hooks[hook_name] = filtered
elif original:
    del hooks[hook_name]
```

`elif original:` only deletes when the original list was non-empty (meaning we actually removed EC commands that emptied it). When `original = []` (pre-existing empty), `original` is falsy → no deletion → key preserved.

## Success criteria

1. Regression test: disable with `{"PreToolUse": [], "Stop": [ec_entry]}` — assert `"PreToolUse"` key survives and `"Stop"` is correctly removed
2. Existing disable tests pass
3. Full `test_project_cmds.py` passes

## Dependency

This fix assumes PR #218 (`_strip_ec_hooks` empty-group fix) is merged first or in the same release. Without #218, entries with `hooks: []` inside a matcher entry are still dropped by `_strip_ec_hooks`, so `filtered` returns `[]` while `original` is a non-empty list — and `elif original:` would still delete the key. The two fixes are independent layers (entry-level vs hook-type-level), both required.

## Out of scope

- `_strip_ec_hooks` fix (PR #218, prerequisite)
- Other v0.16.0 items
