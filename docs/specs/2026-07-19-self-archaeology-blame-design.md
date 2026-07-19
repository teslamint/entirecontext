---
title: Self-Archaeology + Decision-Annotated Blame
status: draft
date: 2026-07-19
schema: spec/v1
---

# Self-Archaeology + Decision-Annotated Blame Design

_Created 2026-07-19._

## Overview

Run `ec archaeologize` on EntireContext's own full git history (354 commits) to bootstrap the commit-linked decision corpus, add a minimal batch-confirm path so archaeology candidates can actually be promoted at scale, and ship `ec blame --decisions` — the decision-annotated blame view whose only blocker was the empty `decision_commits` table. Closes the gap where the flagship v0.13/v0.14 archaeology feature has never been applied to its own repository (`archaeology_processed` = 0, commit-link coverage 0%).

## User Scenarios

### S1: Bootstrap the decision corpus from full history

The maintainer runs `ec archaeologize --pr-bodies` in batches (default `--limit 100`, repeated until exhausted) over all 354 commits. `archaeology_processed` provides resumability; interrupted or tokenless runs can be re-run without replaying completed work (v0.14.0 retryable-enrichment behavior).

### S2: Triage candidates with a dry-run distribution report

Before confirming anything, the maintainer runs
`ec decision candidates confirm-batch --source archaeology --min-confidence 0.7 --dry-run`
and sees how many pending archaeology candidates fall above/below the threshold (count per confidence bucket), without mutating state. The threshold is chosen from this observed distribution, not fixed in advance.

### S3: Batch-confirm archaeology candidates

`ec decision candidates confirm-batch --source archaeology --min-confidence <N>` promotes every pending archaeology candidate at or above the threshold by looping the existing single-candidate `confirm_candidate()` path — inheriting its atomicity (`WHERE review_status='pending'` guard) and its `decision_commits` linkage (source_id commit SHA → `decision_commits` on promotion). Below-threshold candidates remain `pending`; the batch never auto-rejects.

### S4: Ask "why does this code exist?"

A developer runs `ec blame --decisions src/entirecontext/core/tql.py` and sees, alongside the existing attribution output, a decision annotation per commit block: decision title, rationale excerpt (first 200 chars), rejected-alternatives count. Lines whose SHA has no `decision_commits` entry render unannotated with wording that distinguishes "no recorded decision" from "no decision was made"; uncommitted working-tree lines (all-zeros blame SHA) render as a third, distinct "uncommitted" state.

### S5: Spot stale reasoning in blame output

When an annotated decision has `staleness_status` of `superseded` or `contradicted`, the annotation carries a `[STALE:<status>]` marker and a hint to run `ec decision get <id>` for the current state of the reasoning.

## Scope

### In

- `confirm-batch` subcommand under `ec decision candidates` with `--source`, `--min-confidence`, `--dry-run` filters, implemented as a loop over the existing `confirm_candidate()` (no new promotion logic).
- Operational run: full-history archaeology on this repo (`--pr-bodies`, batched, resumable), then threshold selection and batch confirm. Recorded as reproducible commands in the release notes, not as code.
- `--decisions` flag on the existing `ec blame` command (brainstorm Option A, confirmed 2026-07-19).
- New `core/blame_decisions.py`: `git blame --porcelain` → deduplicated per-line SHA set → `decision_commits JOIN decisions` (direct two-way join) → annotation records `(commit_sha, line_ranges, decision_id, title, rationale_excerpt, rejected_alternatives_count, staleness_status)`.
- Staleness display from `staleness_status` (the actual schema column; the 2026-04-27 brainstorm's `is_stale` never existed in schema v16+).
- Graceful handling: untracked file, binary file, file with zero annotated lines.
- Unit tests: batch confirm (threshold filter, source filter, dry-run no-mutation, pending-only guard), blame traversal (multi-SHA join, no-decision lines, staleness rendering, untracked/empty file).

### Out

- MCP `ec_blame` tool — deferred until the CLI surface is validated by dogfooding.
- Interactive HITL review queue (`ec review`) — the roadmap exploration item stays deferred; batch confirm is the minimal subset.
- Auto-rejecting below-threshold candidates.
- Per-line decision granularity (annotation is per-commit-SHA; `-L` restricts which lines' SHAs are collected, but decisions never map to sub-commit line spans).
- Refactoring existing attribution logic in `blame_cmds.py`.
- Semantic re-ranking or embedding work in blame output.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| Archaeology has never been run on this repo | `sqlite3 .entirecontext/db/local.db "SELECT COUNT(*) FROM archaeology_processed"` | 2026-07-19T13:35:00+09:00 | 0 rows | Working tree local.db |
| Commit-link coverage is 0% | `SELECT COUNT(DISTINCT decision_id) FROM decision_commits` | 2026-07-19T13:35:00+09:00 | 0 of 127 decisions | Working tree local.db |
| File-link coverage is 9% | `SELECT COUNT(DISTINCT decision_id) FROM decision_files` | 2026-07-19T13:35:00+09:00 | 11 of 127 decisions | Working tree local.db |
| Full history is 354 commits; 100 commits ≈ 250-300k tokens | `git rev-list --count HEAD` + `uv run ec archaeologize --dry-run` | 2026-07-19T13:37:00+09:00 | 354 commits; dry-run reports 100 pending ≈ 250,000-300,000 tokens | Working tree |
| `confirm_candidate()` already links archaeology source_id → `decision_commits` | `grep -n "archaeology" src/entirecontext/core/decision_candidates.py` | 2026-07-19T13:40:00+09:00 | Promotion branch at decision_candidates.py:202 inserts commit link | Working tree source |
| `decisions` uses `staleness_status`, not `is_stale`; `decision_commits` is a direct `(decision_id, commit_sha)` table | `PRAGMA table_info(decisions)` / `PRAGMA table_info(decision_commits)` | 2026-07-19T13:35:00+09:00 | Columns confirmed; no `is_stale`, no checkpoint hop needed | Working tree local.db |
| `list_candidates()` already filters by `review_status` and `source_type` | `grep -n "source_type" src/entirecontext/core/decision_candidates.py` | 2026-07-19T13:40:00+09:00 | Filter clauses at decision_candidates.py:58-71 | Working tree source |

## Architecture

- `core/decision_candidates.py` — add `confirm_candidates_batch(conn, source_type, min_confidence, dry_run)`: paginate `list_candidates(status="pending", source_type=...)` until exhausted — the existing default `limit=50` (decision_candidates.py:59) must NOT silently truncate the batch; a full-history run plausibly yields more than 50 candidates. The dry-run distribution buckets all pending candidates; the confirm path reuses `list_candidates`'s existing `min_confidence` parameter (decision_candidates.py:57,72-74). Per-candidate delegate to `confirm_candidate()` with `repo_path=None` so the per-candidate embedding pass (decision_candidates.py:245-255, `decisions.auto_embed` default true) is skipped, then run `generate_embeddings(decisions_only=True)` once after the loop. Returns a summary (confirmed / skipped-below-threshold / failed counts; in dry-run, the confidence distribution instead).
- `core/blame_decisions.py` (new) — subprocess `git blame --porcelain <file>`, extract per-line SHAs, dedupe, single parameterized query `SELECT ... FROM decision_commits dc JOIN decisions d ON d.id = dc.decision_id WHERE dc.commit_sha IN (...)`, group line numbers into ranges per (sha, decision). The all-zeros SHA (uncommitted working-tree lines) is excluded from the query and rendered as a distinct "uncommitted" state.
- `cli/decisions_cmds.py` — wire `confirm-batch` into `candidates_app` (defined at decisions_cmds.py:725, mounted at :855) beside the existing `confirm` (:809).
- `cli/blame_cmds.py` — `--decisions` flag; when set, render annotation blocks beneath the existing attribution table. No changes to attribution internals.
- Streaming: blame output is processed line-by-line; the decision query runs once on the deduplicated SHA set (bounded by distinct commits in the file, not file length).

## Interface

```
ec decision candidates confirm-batch [--source archaeology] [--min-confidence 0.7] [--dry-run]
ec blame --decisions <file> [-L 10,20]
```

- `confirm-batch` with no matches prints the empty-state distribution and exits 0.
- `--summary` and `--decisions` are mutually exclusive: combining them exits 1 with a clear message (the summary path returns early at blame_cmds.py:41-66 and has no annotation surface).
- `-L` continues to bound the attribution display; decision annotation covers the SHAs of the displayed lines only.
- `ec blame --decisions` shows attribution AND decisions in a combined view (brainstorm review question resolved: combined, not suppressed — a follow-up flag can split them if output proves cluttered).

## Testing

- Batch confirm: threshold boundary (equal-to passes), source filter excludes non-archaeology pending candidates (live DB currently holds 2 `assessment` + 7 `checkpoint` pending rows), pagination past `limit=50` covers the full pending set, dry-run leaves `review_status` untouched, already-confirmed candidates are not re-processed, per-candidate failure does not abort the batch, embeddings are generated once per batch (not per candidate).
- Blame traversal: fixture repo with commits linked via `decision_commits`; multi-SHA files; lines with no decision; uncommitted (all-zeros SHA) lines; staleness marker rendering; untracked file exits with a clear message; `--summary --decisions` rejected; `-L` range restricts annotation scope.
- Existing suites for `decision_candidates`, `blame`, and `archaeology` modules must pass unchanged (test scope matches change scope, per CLAUDE.md).

## Risks

- **Extraction quality on old commits is unknown.** Mitigation: S2's dry-run distribution gates the threshold choice; below-threshold candidates stay pending; nothing is auto-rejected. If quality is poor, the batch confirms few decisions and Success Criterion 2 honestly fails — that is a measurement, not a blocker to hide.
- **Token cost ~900k-1.1M for full history.** Mitigation: batched `--limit` runs with `archaeology_processed` resumability; cost is one-time bootstrap.
- **False `accepted` corpus quality from over-eager batch confirm.** Mitigation: source-filtered, threshold-gated, dry-run-first; single-candidate atomicity guard reused.
- **Blame empty output misleads** ("no decisions" ≠ "no decisions were made"). Mitigation: explicit empty-state wording (S4).
- **`git blame --porcelain` on large files.** Mitigation: SHA dedupe keeps the DB query small; porcelain parse is linear and streamed.

## Success Criteria

1. **Full history archaeologized.** `SELECT COUNT(*) FROM archaeology_processed` equals the eligible (non-merge) commit count reported by the final `--dry-run` (0 pending remaining). Proving command: the sqlite count plus `uv run ec archaeologize --dry-run` showing 0 pending.
2. **Commit-linked corpus exists.** After batch confirm: ≥ 20 decisions have `decision_commits` rows (from 0), and file-link coverage reaches ≥ 40% of all decisions (from 9%). Proving command: the two sqlite coverage queries recorded in Assumptions, re-run and reported before/after.
3. **Blame answers "why".** `uv run ec blame --decisions <file>` on at least one file with known decision history prints ≥ 1 decision annotation with title and rationale excerpt. Proving command: the command itself, output pasted in the retro.
4. **Tests prove the new paths.** New unit tests for batch confirm and blame traversal pass, and the full existing test suites for the touched modules pass. Proving command: `uv run pytest tests/ -k "candidate or blame or archaeology"` plus the full suite run before merge.
5. **Dogfooding continuity** (carry-forward, soft): when archaeology-sourced decisions influence later work, record `ec context apply`. Judged in the next retro via `applied_context_rate` trend.

## Open Decisions

- Exact `--min-confidence` value — chosen at run time from the S2 dry-run distribution, recorded in release notes.
- Whether `ec blame --decisions` output warrants a future decisions-only mode or an `ec decision blame` alias — revisit after dogfooding.
- MCP `ec_blame` exposure — deferred; revisit once CLI proves useful.
