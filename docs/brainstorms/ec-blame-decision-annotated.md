# `ec blame` — Decision-Annotated Git Blame

_Draft brainstorm. Created 2026-04-27. Milestone: v0.7.1. Confidence: 85%._

## Intent

`ec blame <file> [line]` traverses `decision_commits → decision_checkpoints → decisions` to answer "why does this code exist?" — surfacing the decision title, rationale, and rejected alternatives for lines with known decision history.

The existing `ec blame` command in `cli/blame_cmds.py` implements **human/agent attribution** (who wrote each line). This feature adds **decision annotation** (why each line was written). These are related but distinct: attribution is about authorship, decision annotation is about intent. The interface collision must be resolved before implementation starts.

User-visible outcomes:

- Developers can run `ec blame <file>` and see decision context alongside or instead of authorship attribution.
- Lines with associated decisions display title, rationale, and rejected alternatives without requiring a separate query.
- Stale decisions (superseded, contradicted) are visually flagged so developers know to re-verify the reasoning.

## Scope

### In

- Traversal logic: `git blame --porcelain <file>` → SHA per line → JOIN `decision_commits` → JOIN `decision_checkpoints` → JOIN `decisions`.
- Return fields per annotated line: decision title, rationale excerpt (first 200 chars), rejected alternatives count, staleness indicator.
- `--decisions` flag on existing `ec blame` command (preferred interface — see Interface Decision section below).
- Display: Rich table or inline annotation alongside existing attribution output.
- Staleness indicator derived from existing `is_stale` flag in `decisions` table.
- Unit tests for `decision_commits` JOIN path and empty-result cases (lines with no associated decision).

### Out

- Creating new decisions from `ec blame` results (read-only output only).
- Semantic embedding or re-ranking within blame output.
- Real-time rewrite of `blame_cmds.py` internals (add `--decisions` flag only; do not refactor existing attribution logic).
- Line-range filtering for decision traversal (decision annotation is per-commit-SHA, not per-line-number).

## Interface Decision

`blame_cmds.py` already exposes `ec blame <file>` for human/agent attribution. Three options for the decision annotation surface:

| Option | Interface | Pros | Cons |
|---|---|---|---|
| A | `--decisions` flag on existing `ec blame` | Single command, unified mental model | Existing attribution and decision annotation are different enough that mixing them may confuse output |
| B | `ec decision blame <file>` new subcommand | Clean separation; decisions namespace is consistent | Duplicates `ec blame` entry point; users must learn two `blame` surfaces |
| C | Replace `ec blame` with combined output; move attribution to `ec attribution` | Unified output without flag proliferation | Breaking change; attribution users must update scripts |

**Recommended: Option A** — add `--decisions` flag. `ec blame --decisions <file>` shows decision annotation alongside attribution. This avoids a breaking change and keeps the entry point discoverable. If output becomes too cluttered, Option B can be introduced in a follow-up without breaking anything.

This choice must be confirmed before implementation starts.

## Traversal Logic Contract

```
git blame --porcelain <file>
  → per-line SHA set (deduplicated)
  → SELECT * FROM decision_commits WHERE commit_sha IN (<sha_set>)
  → SELECT * FROM decision_checkpoints WHERE checkpoint_id IN (<checkpoint_ids>)
  → SELECT id, title, rationale, rejected_alternatives, is_stale
       FROM decisions WHERE id IN (<decision_ids>)
```

Lines with no entry in `decision_commits` render as unannotated (blank decision column). The traversal is a read-only JOIN chain — no writes, no candidate creation.

## Proposed Action Items

### v0.7.1 Core

[ ] Confirm interface option (A, B, or C) with maintainer before writing any code.

[ ] Add `--decisions` flag to `blame_cmd` function in `cli/blame_cmds.py`.

[ ] Implement `git blame --porcelain` subprocess call and SHA extraction in `core/attributions.py` or a new `core/blame_decisions.py` helper.

[ ] Implement `decision_commits → decision_checkpoints → decisions` JOIN traversal. Return list of `(line_range, decision_title, rationale_excerpt, rejected_alternatives_count, is_stale)`.

[ ] Add Rich display for annotated output: per-line or per-commit-block annotation block beneath existing attribution rows.

[ ] Stale decision indicator: use `[STALE]` prefix or color highlight if `is_stale = true`.

[ ] Unit tests: SHA-to-decision JOIN with multiple SHAs, lines with no decision entry (blank annotation), stale flag rendering, and empty-file edge case.

[ ] Update CLI help text for `ec blame` to document the `--decisions` flag.

[ ] Update README `ec blame` section and CHANGELOG.

## Risks

- Interface collision: proceeding without resolving Option A/B/C will produce a command that conflicts with existing attribution UX or breaks existing callers.
- `git blame --porcelain` availability: assumes `git` is in PATH and the file is tracked. Must handle untracked files and binary files gracefully.
- SHA→decision gap: most lines in most files will have no entry in `decision_commits`. The empty case must not produce misleading output ("no decisions" ≠ "no decisions were made").
- Large files: `git blame --porcelain` on a 5000-line file with many commits may be slow. Output should stream, not buffer.
- Staleness display: flagging a stale decision as `[STALE]` without guidance on what to do is unhelpful. The display should suggest `ec decision get <id>` for context.

## Review Questions

- Which interface option (A, B, or C) is preferred? Option A (`--decisions` flag) is recommended, but Option B (`ec decision blame`) avoids output mixing concerns.
- Should `ec blame --decisions` show attribution AND decisions in a combined view, or should `--decisions` suppress attribution and show only decision annotation?
- What is the right staleness display: inline `[STALE]` tag, color-only, or a separate stale-decisions summary block at the end of output?
- Should the traversal follow the successor chain so that a SHA linked to a superseded decision shows the replacement decision instead?
- How should the command behave when `decision_commits` has no rows for the file (expected for most files in most repos at launch)?
