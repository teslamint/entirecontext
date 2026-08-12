---
title: "Retro: _strip_ec_hooks empty hook group fix"
feature: strip-ec-hooks-empty-group
pr: 218
date: 2026-08-12
---

## What shipped

1-line fix in `_strip_ec_hooks()`: `if not remaining` → `if inner and not remaining`
- Unit test + disable-path integration test (76/76 pass)
- ROADMAP v0.16.0 item marked done

## What went well

- **TDD confirmed the bug**: test failed on current code, passed after fix
- **Critic review caught spec errors**: falsely claimed no existing tests existed; corrected before execution
- **Code reviewer found sibling bug**: pre-existing `disable` line 609 group deletion registered in ROADMAP

## What to improve

- **T1: Read existing tests before claiming they don't exist** — the spec said "no existing tests found" but `TestStripEcHooks` had 6 tests. Wasted a review round correcting this.
- **T2: Scope-adjacent bugs found during review should be registered immediately** — the disable sibling bug was registered in ROADMAP during this loop (done correctly).

## Carry-forward

- `disable` deletes empty group keys when sibling triggers rewrite (registered in ROADMAP v0.16.0, P2)

## Metrics

- Time: ~30 min design-to-ship
- Code: +1 line changed, +29 lines tests
- Review rounds: 1 critic (spec) + 1 code-reviewer (diff), both clean
