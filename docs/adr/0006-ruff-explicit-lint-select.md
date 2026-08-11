# 0006. Pin ruff lint select explicitly

**Status:** accepted
**Date:** 2026-08-11
**EC Decision:** `55b72138-555e-474c-8764-853999001544`

## Context

`pyproject.toml` configured `[tool.ruff]` with `target-version` and `line-length` only. It set no `select`, so the enforced rule set was whatever ruff shipped as its default in the installed version.

Dependabot PR #202 bumped ruff from 0.15.21 to 0.16.0 and the `lint` job failed. Measured on identical code:

| ruff version | errors |
|---|---|
| 0.15.20 | 0 |
| 0.16.0 | 589 |

No source file changed between those two runs. Ruff 0.16.0 widened its default rule set, so the bump proposed a lint-policy change while presenting as a version bump. The 589 findings break down as 275 autofixable and 314 requiring a human decision.

Three of the largest new rules conflict with product contracts rather than style:

- **BLE001** (110) — broad `except` clauses. Hook handlers must never crash the host session; the hook protocol is a 0/2 return code, not an exception.
- **PLW1510** (77) — `subprocess.run` without `check=`. Several test fixtures and git helpers deliberately omit it and inspect the result instead.
- **S110** (36) — `try`/`except`/`pass`, used for the same defensive reason as BLE001.

Silencing these would mean either weakening the defensive behaviour or adding 223 `noqa` comments.

## Decision

Pin the rule set explicitly:

```toml
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]
```

This reproduces the previously enforced set. Both 0.15.20 and 0.16.0 report zero errors against it, so the ruff bump becomes a plain dependency update.

Adding rules is now a separate, deliberate change with its own review, not a side effect of a dependabot bump.

## Consequences

**Easier**

- Ruff version bumps stop carrying hidden policy changes. CI failures after a bump indicate a real regression.
- The enforced rule set is readable in `pyproject.toml` rather than implied by a version number.
- Rule adoption can be staged one family at a time, each with its own diff and review.

**Harder**

- New ruff rules no longer arrive automatically. Adopting them requires an explicit config change, so useful rules can be missed if nobody revisits the list.
- The pinned list needs periodic review. Treat a ruff major release as a prompt to compare `select` against the new defaults and decide deliberately.

**Unchanged**

- `uv run ruff check .` remains the CI command. `target-version` and `line-length` are untouched.
