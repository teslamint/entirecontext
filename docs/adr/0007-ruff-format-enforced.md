# 0007. Enforce ruff format in CI, excluding Markdown

**Status:** accepted
**Date:** 2026-08-12
**EC Decision:** `22452eb2-160d-45a7-bb24-4f87eaacd234`

## Context

CI ran `uv run ruff check .` but never `ruff format --check`. Formatting was therefore advisory: 44 Python files had drifted from `ruff format` output without anyone noticing, because nothing measured it.

This is the same failure shape as ADR 0006. There, the enforced lint rule set was implicit in the ruff version; here, formatting was enforced nowhere at all. In both cases the gap only surfaced when something external forced a look.

Ruff 0.16 introduced a second consideration: it formats Python code blocks inside Markdown. With Markdown in scope, the drift is 58 files rather than 44. The extra 14 are all under `docs/superpowers/` — plans and specifications that record what was proposed at a point in time. Reformatting a snippet inside a historical plan changes the record of what was written, for no benefit to shipped code.

## Decision

Enforce formatting in CI, and exclude Markdown from formatting only:

```toml
[tool.ruff.format]
exclude = ["docs/**/*.md"]
```

```yaml
- name: Format
  run: uv run ruff format --check .
```

The exclusion is scoped to `[tool.ruff.format]`, so lint coverage is unchanged. Reformatting the 44 Python files is a separate mechanical commit in the same PR.

## Consequences

**Easier**

- Format drift cannot accumulate silently. The next drift is one file in one PR, not 44 across an unknown span.
- Review diffs stop carrying incidental reformatting noise from editors with different settings.

**Harder**

- The reformat commit touches 44 files and will conflict with any long-running branch that edits the same lines. At the time of this decision, the two live worktrees (`feat/roadmap-completion`, `docs/blame-sha-lookup-retro`) had zero overlap with the reformatted set, but future large branches will need a rebase.
- Markdown code blocks are now unformatted by policy. If a future document wants formatted snippets, it must be written that way by hand or moved outside `docs/`.

**Unchanged**

- `[tool.ruff.lint] select` from ADR 0006, `target-version`, and `line-length`.
- Lint scope. The exclusion applies to the formatter only.

## Related

- [0006](0006-ruff-explicit-lint-select.md) — the lint-side counterpart. Together these make both halves of the ruff configuration explicit rather than inherited.
