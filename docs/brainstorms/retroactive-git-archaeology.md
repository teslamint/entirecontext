# Retroactive Git Archaeology (`ec archaeologize`)

_Draft brainstorm. Created 2026-04-27. Milestone: v0.8.x+. Confidence: 80%._

## Intent

`ec archaeologize [--since <ref>] [--until <ref>] [--limit N]` streams `git log --patch` output (and optionally merged PR bodies from GitHub) through the existing decision extraction pipeline to produce a bootstrapped decision corpus tagged `source: inferred`. All generated candidates require human confirmation via `ec review` before promotion.

The largest barrier to EntireContext adoption is the cold-start problem: new users have zero decisions, so retrieval surfaces nothing useful for weeks. A single `ec archaeologize --since v1.0.0` run on a mature repo eliminates that barrier by seeding the corpus from commit history that already encodes years of engineering judgment.

User-visible outcomes:

- A newly onboarded repo can generate an initial decision corpus from git history without manual entry.
- All inferred candidates are gated behind human review — no decisions auto-promote.
- Progress is streamed so operators can interrupt long runs safely without losing partial results.
- Duplicate-safe: re-running on the same range does not produce duplicate candidates.

## Scope

### In

- CLI command `ec archaeologize` with flags: `--since <ref>`, `--until <ref>`, `--limit N` (default 100 commits), `--pr-bodies` (fetch merged PR descriptions from GitHub), `--dry-run` (show what would be processed, no DB writes).
- Streams `git log --patch --reverse` in batches; each commit fed to `core/decisions.py:run_extraction` with `source="inferred"`.
- All generated records land in `decision_candidates` with `source = "inferred"` (or equivalent tag distinguishing from session-based candidates).
- Duplicate check via `decision_commits` table: skip commits already linked to an existing decision or candidate.
- Streaming progress output: `N commits processed / M candidates generated / K skipped (duplicate)`.
- Config section `[decisions.archaeology]`: `enabled = true`, `github_token = ""`, `pr_body_fetch = false`, `batch_size = 10`.
- Graceful interrupt: `Ctrl+C` commits partial results; next run resumes from last processed commit.

### Out

- Auto-promotion of inferred candidates without human confirmation.
- Non-GitHub PR body sources (GitLab, Bitbucket — deferred).
- Reprocessing commits already linked to an existing confirmed decision.
- Any change to the existing `run_extraction` pipeline internals.

## Architecture

```
ec archaeologize
  → git log --patch --reverse [--since <ref>] [--until <ref>]  (subprocess)
  → batch N commits
  → for each commit:
      if commit_sha in decision_commits: skip (duplicate)
      else: run_extraction(commit_patch, source="inferred")
           → decision_candidates rows with source="inferred"
           → decision_commits link (candidate_id → commit_sha)
  → progress output every batch
  → on interrupt: flush batch, exit cleanly
```

`run_extraction` is called per-commit, not per-batch, to preserve commit-level attribution in `decision_commits`.

## Deduplication Contract

| Case | Behavior |
|---|---|
| Commit SHA already in `decision_commits` (linked to confirmed decision) | Skip; count as duplicate |
| Commit SHA already in `decision_commits` (linked to unconfirmed candidate) | Skip; do not re-extract |
| Commit SHA not in `decision_commits` | Extract; insert candidate + commit link |
| Re-run on same `--since..--until` range | All previously processed SHAs are in `decision_commits`; entire range skipped cleanly |

## Proposed Action Items

### v0.8.x+ Core

[ ] Define the `source = "inferred"` tag behavior in `decision_candidates`: verify it does not conflict with existing `source` values (`session`, `manual`, etc.); add if missing.

[ ] Implement `git log --patch --reverse` subprocess wrapper with `--since`, `--until`, `--limit` support. Handle repos with no matching commits gracefully.

[ ] Implement commit-level deduplication check against `decision_commits` before calling `run_extraction`.

[ ] Add `--pr-bodies` flag: for each commit SHA, fetch associated PR body from GitHub API (`github_token` required); prepend to patch text before extraction.

[ ] Add `--dry-run` flag: count commits to process and candidates that would be generated; no DB writes.

[ ] Add streaming progress output: update on each batch completion.

[ ] Implement graceful interrupt: catch `KeyboardInterrupt`, flush current batch to DB, print resume instruction.

[ ] Define resume behavior: on restart with same `--since..--until`, deduplication naturally skips processed commits. Document that resume is implicit, not state-tracked.

[ ] Add config section `[decisions.archaeology]` with `enabled`, `github_token`, `pr_body_fetch`, `batch_size`.

[ ] Add token cost estimate to `--dry-run` output based on patch size and batch count.

[ ] Unit tests: deduplication logic, `--dry-run` no-write assertion, interrupt flush behavior, empty commit range.

[ ] Integration test: run `ec archaeologize` against a test repo fixture with 20 commits; verify candidate count, deduplication on re-run, and `source = "inferred"` tag on all candidates.

[ ] Update README cold-start section, CHANGELOG, and ROADMAP.

## Open Questions

Three unresolved questions that must be answered before implementation starts:

1. **Batching strategy and token cost estimate.** `run_extraction` calls an LLM per commit (or per batch?). For a repo with 2000 commits, the total token cost must be estimated before the feature ships. Is extraction called per-commit or per-batch? What is the expected cost in tokens for a typical 500-commit run?

2. **`archaeology_commits` tracking table vs reusing `decision_commits`.** Should processed-but-no-candidate commits (commits that produced zero candidates after extraction) be tracked separately in an `archaeology_commits` table, or should they be silently skipped on every re-run (accepted cost: re-extracting zero-candidate commits)? If not tracked, a re-run over the same range will re-call `run_extraction` on all zero-candidate commits.

3. **Synchronous vs `launch_worker` execution.** A 500-commit run may take 5–30 minutes. Should `ec archaeologize` be a synchronous blocking command (with progress output) or a `launch_worker` background job (with a status check command)? The synchronous approach is simpler but holds the terminal for the full duration. The background approach requires a status polling command.

## Risks

- Token cost: extraction over large commit ranges can be expensive. Without a `--dry-run` cost estimate and a `--limit` default, users may trigger unexpectedly large LLM calls.
- Extraction quality on commit patches: commit patches include noise (test changes, dependency bumps, formatting) that does not contain decision-relevant content. Low signal-to-noise may produce many low-confidence candidates that flood the review queue.
- PR body fetch rate limits: GitHub API has rate limits. Without `github_token`, authenticated limits apply. Without rate-limit handling, `--pr-bodies` on a large repo will fail mid-run.
- Re-run cost: if zero-candidate commits are not tracked (pending resolution of Open Question 2), re-runs waste LLM tokens re-processing commits that were already found to be empty.
- Interrupt safety: if `Ctrl+C` fires mid-`run_extraction` (inside the LLM call), the partial extraction result may be lost. The interrupt handler must not corrupt partially written `decision_candidates` rows.

## Review Questions

- What is the expected token cost per commit for `run_extraction`? The answer determines whether `--limit 100` is a safe default or dangerously expensive for some repos.
- Should processed zero-candidate commits be tracked in an `archaeology_commits` table to avoid re-extraction on re-run, or is re-running on zero-candidate commits an acceptable cost?
- Should `ec archaeologize` block the terminal (synchronous with progress) or run as a detached background job with `ec archaeologize status`?
- Should `--pr-bodies` fetch be automatic when `github_token` is set, or always require the explicit `--pr-bodies` flag to prevent unexpected API calls?
- How should the `ec review` queue display `source: inferred` candidates differently from `source: session` candidates so reviewers know these are bootstrapped from history rather than observed agent behavior?
