# Retro: v0.17.0 release

- Date: 2026-11-05
- Source: PR #280 (`5c1cd36`), PR #281 (`819684d`), PR #282 (`dc52c2a`), PR #283 (`14a2c71`), PR #284 (release `d1af057`), tag `v0.17.0`, release workflow run 41852581427
- Spec: none. This cycle fixed issues #262 and #263, cleaned up the roadmap and changelog, and released the work merged on `main` since v0.16.1.

## Release data

| Metric | Value |
|---|---|
| Changed `src/` lines (v0.16.1 → v0.17.0) | 2,595 insertions, 690 deletions across 63 files |
| Changed `tests/` lines | 3,899 insertions, 3,918 deletions across 100 files |
| Non-merge commits | 45 (28 excluding dependency bumps) |
| PRs in this cycle's session | 5 (#280–#284) |
| Review findings acted on | #280: 3 local-reviewer suggestions. #281: 5 local fact-check findings, then 2 Codex findings. #282: 1 Codex finding; 1 advisory finding after merge, fixed by #283. #284: 1 Codex P2. |
| CI failures on required checks | 0 |
| Duration (v0.16.1 tag → v0.17.0 tag) | 2026-08-20 → 2026-11-04 |
| Maturity at release | 71 (`applied_context_rate` 0.5%, 8/1,728; `lesson_reuse_rate` 21%) |

## Success criteria: measured vs declared

No spec exists for this cycle, and no success criteria were declared before the work. This section is skipped per protocol. The release checklist in `docs/RELEASE.md` was the only gate, and every item in it was run (see PR #284).

## Carry-forward from previous retro

Previous retro: `docs/retros/2026-08-21-v0161-verify-docs-hardening-retro.md`.

| Item (registered 2026-08-21) | Status | Evidence |
|---|---|---|
| Update `docs/RELEASE.md` with branch-protection-aware release flow | **Done** | PR #284: release PR merges first; tag from `main` (`docs/RELEASE.md` §4) |
| `_FakeMCP` test helper rename | **Done** | PR #284: `_FakeMCPServer` in `tests/test_contract_sync.py` |
| Reach maturity 75 | In progress | Maturity 71; tracked under ROADMAP v0.13.0 **applied_context_rate ≥ 10%** |
| Decide whether to ship `py.typed` | Deferred | ADR 0019 defers until stable status; ROADMAP v0.16.0 row |

- Reconciliation: registered 4, accounted for 4.

## Interview Transcript

- Independence level: external model (Codex, gpt-5.5) for each fact check; the author is Claude.
- Rounds used: 1 retro probe (see below), plus review rounds already recorded on each PR.

| ID | Probe | Answer | Evidence | Verdict |
|---|---|---|---|---|
| T1 | Did the commit gate run green before commits? | No for #280. The first full run had 2 failures; both commits were made, then a `--basetemp=/tmp/ecg` run gave 2,177 passed before the push. | Session record; #280 commit `3069085` `Tested:` line | accepted — see "What to improve" |
| T2 | Did review catch a wrong claim before merge? | Partly. Codex caught one `ec disable` claim on #282, but missed the "only" in the filtering entry; an advisory caught it after merge, and #283 corrected it. | PRs #282, #283; `src/entirecontext/sync/exporter.py:99-102,139-143` | accepted |
| T3 | Did the new release flow tag the right commit? | Yes. Tag `v0.17.0` points to `d1af057` on `main`; the release workflow passed all 6 jobs. | `git ls-remote --tags origin v0.17.0`; run 41852581427 | accepted |

## Findings

### What worked well

- **What happened**: Codex review of the release branch found that the new `docs/RELEASE.md` step could tag the release-branch commit, because `git pull` does not switch branches.
  **Why**: an independent model read the procedure as an operator would.
  **How to apply**: review procedure text with the same rigor as code before a release.
  **Cites**: T3; PR #284 commit `7030673`.

- **What happened**: Merges pinned `--match-head-commit` and checked the merge commit parent against the CI base.
  **Why**: this proves no other commit landed on `main` between CI and merge.
  **How to apply**: keep this step for every squash merge.
  **Cites**: PRs #280–#284.

### What to improve

- **What happened**: Two tests fail on macOS with the default temporary directory: `test_init_from_linked_joins_main_project` and `test_worktree_merge::test_absolute_content_path_outside_entirecontext_is_not_linked`. Rich wraps or truncates the long `/private/var/folders/...` path in the output, so substring assertions fail. They pass with `--basetemp=/tmp/ecg` and in Linux CI.
  **Why**: the assertions compare raw console output, which depends on terminal width and path length.
  **How to apply**: make these assertions independent of wrapping, then the plain `uv run pytest -q` gate can be green on macOS. Registered in ROADMAP.
  **Cites**: T1.

- **What happened**: A changelog entry said secret filtering applies "only" to descriptive metadata. The code filters turn messages, checkpoint summaries, and JSON values too.
  **Why**: the claim came from a diff hunk, not from the whole function, and the fact-check prompt did not ask about scope words.
  **How to apply**: check words such as "only", "every", and "no longer" against the full current function and the previous tag.
  **Cites**: T2.

### Process observations

- The PyPI JSON endpoint showed 0.16.1 for about a minute after publish, while `pip install entirecontext==0.17.0` already worked. Check the version-specific endpoint before treating publish as failed.
- The local `ec` tool rebuilt from the checkout reports a dirty build when tracked user files are modified (`.serena/project.yml`, `LESSONS.md`). `ec doctor` then warns. This is expected behavior, not a defect.

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Make two Rich-output path assertions independent of wrapping on macOS | test reliability | P3 | ROADMAP v0.17.0 carry-forward |
| Reach maturity 75 | measurement | P3 | ROADMAP v0.13.0 **applied_context_rate ≥ 10%** |
| Decide whether to ship `py.typed` | architecture | P4 | ROADMAP v0.16.0 row; ADR 0019 |
| Signal C prompt-time ranking | feature | P3 | ROADMAP Later |

## Lessons

- Verify scope words in release notes against the whole current function, not the PR diff.
- A release procedure is code an operator runs; review it before the release that first uses it.
