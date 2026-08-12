---
title: "Plan: _strip_ec_hooks empty hook group fix"
spec: .release-loop/briefs/spec-strip-ec-hooks-empty-group.md
---

## Units

### U1. Regression test (TDD red)

Add to `TestStripEcHooks` in `tests/test_project_cmds.py`:

```python
def test_preserves_entry_with_already_empty_hooks(self):
    entry = {"matcher": "", "hooks": []}
    assert _strip_ec_hooks([entry]) == [entry]
```

Run and verify failure on current code.

### U2. Fix

`src/entirecontext/cli/project_cmds.py:350`: change `if not remaining:` to `if inner and not remaining:`.

Run U1 test again — verify pass.

### U3. Disable-path integration test

Add to `tests/test_project_cmds.py` (new class or existing fixture):

Test that `ec disable` with a settings file containing only a `"hooks": []` entry under `"Stop"` preserves the key and prints "No EntireContext hooks found".

### U4. Full test suite

Run `tests/test_project_cmds.py` — all existing 6 `TestStripEcHooks` tests + new tests pass.

## Verification

- `uv run pytest tests/test_project_cmds.py -v`
- Zero failures, zero skips on the `TestStripEcHooks` class
