# Retro: Signal C prompt-time ranking

- Date: 2026-11-05
- Source: PR #293
- Spec: docs/specs/2026-11-05-signal-c-prompt-ranking-design.md
- Plan: docs/plans/2026-11-05-001-feat-signal-c-prompt-ranking-plan.md

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 1238 (1214 added + 24 removed, 18 files incl. docs; `git diff --shortstat 784875d 924c946 -- . ':!tests'`) |
| Commits | 18 non-merge commits on the feature branch, squashed into 924c946 |
| Review rounds (unit / final / standalone) | 5 (1 / 1 / 3); design-phase reviews outside this count: spec 3, plan 3 (Codex) |
| Fix rounds | 5 |
| Internal findings (fixed / deferred) | 13 / 0 |
| Pull request comments (fixed / deferred) | 5 / 0 (CodeRabbit 4, SonarCloud 1) |
| Count completeness | partial — lower bound since 2026-11-05T05:50:38Z |
| CI failures | 1 (SonarCloud quality gate, not a required check) |
| Duration (first spec commit → merge) | 0 days (2026-11-05T06:06:59Z → 08:32:29Z) |
| Units planned / completed | 6 / 6 |

## Success criteria: measured vs declared

Measured fresh on 2026-11-05 between 08:33:13Z and 08:36:33Z against merged `main` (924c946) and this branch.

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | Benchmark gain on the fixture, equal result on its control | `uv run pytest -q tests/test_semantic_ranking_benchmark.py` | verified: 8 passed (file), 42 passed with the ranking tests | Met |
| 2 | Default configuration changes nothing | `uv run pytest -q -k test_default_config_never_launches_semantic_worker` | verified: 1 passed | Met |
| 3 | Semantic-only decision surfaces on the next prompt | `uv run pytest -q -k test_two_pass_semantic_candidate_surfaces_on_next_prompt` | unverified on 924c946: 0 tests selected, the test was missing; verified on this branch: 1 passed, and the mutant that drops the scores fails it | Partially met — the merged PR shipped without its criterion-3 test; this PR restores it |
| 4 | Every failure falls back to baseline | `uv run pytest -q -k test_semantic_fail_closed` | verified: 9 passed | Met |
| 5 | Budget holds with the signal active | `uv run pytest -q -k test_user_prompt_hook_surfaces_semantic_decision_within_budget` | verified: 1 passed | Met |
| 6 | Benchmark numbers committed and reproducible | rubric: rerun the recorded command on the same database and compare | verified: rerun 08:36:33Z gives identical item counts and hit@5; MRR differs by at most 0.003 (live database, documented in the report) | Met |
| 7 | Full repository gate | `uv run pytest -q`, `ruff check`, `ruff format --check`, `mypy src/entirecontext/` | verified: 2240 passed, 3 skipped; ruff, format, mypy clean (this branch, with the restored test) | Met |

## Carry-forward from previous retro

| Item | Status | Evidence |
|---|---|---|
| Make two Rich-output path assertions independent of wrapping on macOS | Done | PR #290 (8a82dbd) |
| Reach maturity 75 | Not started | still 8/1,893 sessions; PR #292 records why it stays open |
| Decide whether to ship `py.typed` | Not started | ADR 0019 defers it until stable status |
| Signal C prompt-time ranking | Done | PR #293 (924c946) |

- Reconciliation: registered 4, accounted for 4
- Previous doc shape: conformant

## Interview Transcript

- Independence level: heterogeneous
- Rounds used: 2 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---|---|---|---|---|---|
| T1 | 1 | 5 | Why did the merge rely on a full-suite pass without checking that each spec test exists? | No step compared spec test names with test functions after the last test edit; `validate_plan.py` checks the disposition table only. The test was removed by a range replacement applied after the unit review. | `git log -S "def test_two_pass_semantic_candidate_surfaces_on_next_prompt"` returns nothing | accepted |
| T2 | 1 | 4 | What evidence closed U5, and who owned the integration check? | 29 targeted passes, 20 mutants, full gate 2223, all taken after the replacement; the orchestrator owned the check. | ledger line "U3-U5 DONE (229c209)" | accepted |
| T3 | 1 | 4 | How was scenario S3 judged satisfied? | Only by the real-model smoke; no permanent test guarded the hook-to-ranker handoff on merged main. | ledger smoke line; restored test fails under the "no scores passed" mutant | accepted |
| T4 | 2 | 5 | Which record drove ship decisions, and were log and structured fields reconciled? | Live `gh pr checks 293` and `gh pr view 293 --json mergeStateStatus` (CLEAN); structured fields stayed at `review_rounds: 0`, `review_events: []`, `merged: false`; no reconciliation step. | `rg -n "^review_rounds\|^review_events\|^merged" .release-loop/runs/signal-c-prompt-ranking/progress.md` | accepted |
| T5 | 1 | 5 | How was preservation of approved history checked before a sync command? | It was not; a rebase rewrote the approved spec commits, was reverted to the ledger head, and later syncs used merge. | ledger incident line; `git merge-base --is-ancestor 353ba174 HEAD` | accepted |

## Findings

1. **A spec test can disappear without any gate noticing.** The plan's disposition table named the test, the reviewer saw it, and a later range edit removed it before the first commit. The full-suite count cannot show a missing test. A check that every retained or merged disposition names an existing test function would have blocked the merge.
2. **Real-model benchmark results contradicted the spec's main risk.** The spec expected no Korean benefit (cross-lingual cosine −0.033). The benchmark measured hit@5 0.067 → 0.381 on Hangul prompts that do not name their labeled files. A likely cause is English identifiers inside Korean prompts; this is an inference.
3. **The benchmark needed four correctness fixes after review** (absolute-path labels, labeled-file mention scope, `top_n` parity, later successors). Each one changed or could have changed the headline number. Review of measurement code found more defects than review of the product code.
4. **The release-loop ledger's structured fields were not maintained** (T4). The Log lines carried the evidence.

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Check that each retained Spec test exists as a test function | process | P2 | ROADMAP Hardening Backlog |
| Successor-chain resolution ignores `until` | edge-case | P3 | ROADMAP Hardening Backlog |

## Lessons

- After a range edit to a test file, list the spec's test names against the file before committing.
- Treat a measurement script as production code for review: its defects change the decision it informs.

## Compounding

Not attempted — the reusable lesson is captured as the first carry-forward item, which turns it into a check.
