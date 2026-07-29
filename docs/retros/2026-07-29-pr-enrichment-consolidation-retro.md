# Retro: Consolidate PR Enrichment State Transitions

- Date: 2026-07-29
- Source: PR #204
- Spec: `docs/specs/2026-07-29-consolidate-pr-enrichment-state-design.md`
- Plan: `docs/plans/2026-07-29-001-refactor-consolidate-pr-enrichment-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 80 (+52/-28) in `archaeology.py`; +4 in `ROADMAP.md` |
| Commits | 9 branch commits, squash-merged as `e369ac1` |
| Review rounds | 1 (advisor) |
| Comments (fixed / deferred) | 1 fixed (ROADMAP carry-forward closure) / 3 deferred (false-positive TQL comments on files not in diff) |
| CI failures | 0 |
| Duration (first spec commit → merge) | ~52 min |
| Units planned / completed | 3 / 3 |

## Success criteria: measured vs declared

| # | Declared criterion | Measurement | Measured result | Verdict |
|---|---|---|---|---|
| 1 | `needs_patch`/`needs_pr` derivation expressions each appear exactly once in `action()` | `grep -n "not self.patch_processed" archaeology.py`; `grep -c "not state.patch_processed\|not state.pr_body_processed" archaeology.py` | verified: `not self.patch_processed` at line 151 only; `not self.pr_body_processed` at line 152 only; `not state.*` count = 0 | **Met** |
| 2 | `pr_complete` inline boolean eliminated | `grep -c "pr_complete" archaeology.py` | verified: count = 0; `resolve_pr_completion` is sole determination site (lines 155, 568, 597) | **Met** |
| 3 | All four branches produce identical side effects, verified by characterization tests | `pytest -k "branch_a or branch_b or branch_c or branch_d"` | verified: 4/4 passed on post-merge main (`e369ac1`) | **Met** |
| 4 | All existing archaeology tests pass | `pytest tests/test_archaeology*.py tests/test_migration_v017.py` | verified: 112 passed (second run; first run had 11 transient fixture-setup errors, all git-commit signing/temp-dir related) | **Met** |
| 5 | No change to `archaeologize()` public signature or `ArchaeologyResult` | `grep -A15 "^def archaeologize(" archaeology.py` | verified: signature identical to pre-refactor (conn, repo_path, *, since, until, limit, pr_bodies, dry_run, batch_size, min_confidence, extraction_weights, progress_callback) → ArchaeologyResult | **Met** |
| 6 | Dry-run PR enrichment pending count remains token-independent | `sed -n '133,135p' tests/test_archaeology_cli.py` | verified: assertion `"1 PR enrichments pending"` present at line 134; test passes in CI (3.12 + 3.13) | **Met** |

## Carry-forward from previous retro

| Item | Status | Evidence |
|---|---|---|
| TQL `--until` for local semantic search | **Done** | Commits `7b74b84..1bdfe5c`; ROADMAP line 355 marked complete in PR #204 |
| TQL `--until` for global cross-repo search | **Done** | Commits `a5ad64d..1bdfe5c`; ROADMAP line 356 marked complete in PR #204 |
| Maturity 75 dogfooding with `ec context apply` | In progress | No explicit context application this cycle; rate unchanged |
| Consolidate PR enrichment state transitions | **Done** | PR #204; ROADMAP lines 337, 358 marked complete |
| General Git C-style escaped paths | Not started | `_decode_git_quoted_path` unchanged; no real-repo evidence of the gap |
| Post-squash archaeology convergence | Not started | Requires explicit export authorization; orthogonal to this cycle |
| Abbreviated-SHA blame lookup complexity | **Done** | Completed by `5a24ebf` (PR #199); already marked in ROADMAP |

Previous doc shape: pre-schema, exempt (no Interview Transcript section in v0.15.0 retro).

## Interview Transcript

Independence level: self-checklist
Rounds used: 0

No independent facilitator dispatched — this is a pure refactor with 6/6 SC Met and no ambiguous findings. The self-checklist confirms: all measurements are command-based, no narrative judgment required.

## Findings

### What worked well

- **What happened**: Advisor review during design caught a critical equivalence error — folding token availability into `needs_pr` would have collapsed two distinct branches (A: fully processed skip vs B: tokenless PR-only skip with callback) into one, silently dropping progress callbacks.
  **Why**: The spec's outcome table was written before the code was designed, so the four-branch side effects were explicit constraints, not post-hoc rationalizations.
  **How to apply**: Write the outcome table first when refactoring state-transition logic; it makes hidden side-effect differences visible before code changes begin.

- **What happened**: Characterization tests (U1) locked all four branches before any refactoring began, and all four passed unchanged after U3.
  **Why**: Test-before-refactor makes "behavior preserved" a measured claim, not an assertion.
  **How to apply**: For state-transition refactors, write per-branch characterization tests with exact counter/callback/DB assertions before touching production code.

### What to improve

- **What happened**: Plan advisor review found that U3's dry-run prescription wrote `pr_bodies and state.patch_processed and not state.pr_body_processed` — the exact string its own acceptance grep forbade. This would have been a test failure at implementation time, but it wasted a review round.
  **Why**: The plan was written incrementally (spec → plan) and the dry-run path was added after the acceptance criteria were defined, without re-checking them against each other.
  **How to apply**: Run acceptance criteria as a mental dry-run against every prescribed code change before committing the plan.

### Process observations

- **What happened**: Three of four bot review comments were false positives — they commented on TQL changes in `search_cmds.py` and `cross_repo.py` that were not in the PR's actual diff.
  **Why**: The review bot likely diffed against a different base than the PR's merge-base, picking up pre-existing TQL commits.
  **How to apply**: When triaging bot review comments, verify the file is in the PR's diff before acting.

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Maturity 75 dogfooding with `ec context apply` | process | P3 | `ROADMAP.md` v0.15.0 carry-forward (ongoing) |
| Post-squash archaeology convergence | process | P3 | `ROADMAP.md` v0.15.0 carry-forward |
| General Git C-style escaped paths | edge-case | P4 | `ROADMAP.md` v0.14.0/v0.15.0 carry-forward |

## Lessons

- **"Write the outcome table before writing the refactor."** A four-branch side-effect table caught a design error that would have silently dropped progress callbacks — the table made invisible branch differences visible before any code changed.

## Compounding

Not attempted — no reusable lesson this cycle. The outcome-table lesson is a specific instance of the existing "state-transition tables in specs" guidance from the v0.14.0 retro.
