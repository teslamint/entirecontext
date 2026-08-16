# Retro: Spec Directory Policy

- Date: 2026-08-16
- Source: PR #224 and follow-up PR #225
- Spec: `docs/specs/2026-08-16-spec-directory-policy-design.md`
- Plan: `docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 427 (413 added + 14 removed) across 6 files |
| Commits | 6 branch commits across PR #224 and PR #225; squash merges `7e07ccb` and `72e0aa5` |
| Review rounds | 11 automated review submissions: 1 on PR #224 and 10 on PR #225 |
| Comments (fixed / deferred) | 20 fixed / 1 deferred; deferred comment `3791652634` requested root-level non-Spec Markdown-link validation outside the approved contract |
| CI failures | 0; both PRs completed their required GitHub Actions checks successfully |
| Duration (first spec commit → follow-up merge) | 3 h 45 m (`69eadd1` at 08:27:01Z → PR #225 merge at 12:12:09Z) |
| Units planned / completed | 1 / 1 |

The initial policy PR merged before its published validator had been proved fail-closed. PR #225 repaired the verification contract before this release loop was archived.

## Success criteria

All measurements below were run fresh against the tested PR #225 tree or merged `main`, which were shown identical with `git diff --quiet 29902ee FETCH_HEAD` after the squash merge.

| # | Declared criterion | Measurement | Measured result | Verdict |
|---|---|---|---|---|
| 1 | `AGENTS.md` names `docs/specs/` as the sole governing active Specification path. | `grep -n 'docs/specs/' AGENTS.md`; competing-path grep | verified: governing line resolves at `AGENTS.md:20`; competing path has no match | Met |
| 2 | Every active Specification traceability pointer resolves to an existing file. | Exact Plan Step 4 block, `docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md:71-225` | verified: exit 0; `68 checked; Markdown destinations: 5; bold references: 8; labels: 25` | Met |
| 3 | Existing Specification files are not moved or renamed. | `git diff --name-status 71a1383 HEAD -- docs/specs docs/superpowers/specs` | verified: only the new policy Spec is `A`; no `M`, `D`, or `R` entries | Met |
| 4 | The roadmap drift item records the selected policy and is closed. | `ROADMAP.md:355` | verified: checked entry names `docs/specs/` as official and preserves historical paths | Met |
| 5 | Historical release evidence remains readable without path rewriting. | `git diff --quiet 71a1383 HEAD -- .release-loop/archive`; archive reference resolver | verified: archive diff exits 0; 8 historical Specification references found, 0 missing | Met |

The PR #225 implementation satisfied the five Success Criteria (`docs/specs/2026-08-16-spec-directory-policy-design.md:93-104`) and the independent Scope/Out constraints (`docs/specs/2026-08-16-spec-directory-policy-design.md:44-50`). During Retro handoff, `main` could not resolve the feature-worktree EC decision published by ADR 0010. The closure repair preserved that original row and stable ID in the main repository database, linked the ADR, Spec, Plan, and roadmap, and recorded an accepted outcome. `ec decision show 0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b` now succeeds from `main`; active artifact IDs and approved Specification content remain unchanged. A temporary duplicate created during diagnosis was superseded by the original decision to retain its audit trail without making it canonical.

The exact Plan Step 4 block was rerun pre-commit after preserving the original decision ID: exit 0, `74 checked; Markdown destinations: 5; bold references: 9; labels: 27`, and no Specification `M`, `D`, or `R` entry.

## Carry-forward from previous retro

Previous retro: `docs/retros/2026-08-12-cross-repo-overload-retro.md`, three items registered. All three are accounted for.
- Previous doc shape: conformant

| Previous item | Trigger class | Status | Evidence |
|---|---|---|---|
| Pre-execute plan verification commands at authoring time | event-based | In progress | T4; trigger fired when Plan `2bc31fb` was amended in `3440adb`; reviewed head `8f5baac` contained a validator whose inner assertion failed while the compound shell exited 0; remains open at `ROADMAP.md:362` |
| Decide whether to ship `py.typed` | edit-based | Not started | T4; trigger did not fire because PRs #224/#225 changed documentation only and did not modify `pyproject.toml` or the package's typed surface; remains open at `ROADMAP.md:363` |
| Maturity 75; measure intervene events before asserting a cause | drift-based | In progress | T4; fresh `ec dashboard` reports maturity 71, `capture=17`, `distill=17`, `retrieve=25`, `intervene=12`, applied-context 1%, lesson reuse 20%; `ROADMAP.md:383` was refreshed and no cause is inferred without raw intervene-event measurement |

## Interview Transcript

- Independence level: same-model fresh-context
- Rounds used: 3 (max 5)
- Facilitator: read-only reviewer lane with the Spec, Plan, release ledger, PR evidence, fresh success measurements, release data, and previous carry-forwards supplied up front
- Round 1: five evidence-demanding probes
- Round 2: T1-T3 and T5 accepted; T4 rejected pending fresh component/rate evidence; the worktree-decision finding was held because locality alone did not prove unintended loss
- Round 3: T4 accepted after fresh telemetry and tracker reconciliation
- Handoff re-probe: the active ADR reference then failed from `main`; the original decision row and ID were preserved in the main database, active references remained unchanged, and the systemic promotion gap was registered.

| Probe | Evidence response | Facilitator verdict |
|---|---|---|
| T1: How did PR #224 record a passing validator? | Plan `2bc31fb` was self-reviewed, then `3440adb` amended Step 4. At reviewed head `8f5baac`, verbatim execution emitted `AssertionError`, continued to a later successful `git diff`, and returned shell status 0. Progress line 42 called it passed; PR #224 comments `3791367898` and `3791367902` proved the status mismatch and vacuous regex. | accepted (P2 process). The answer ties the false green to `2bc31fb`/`8f5baac`, the 08:33 ledger claim, a verbatim assertion traceback followed by shell exit 0, and both PR #224 comments; no evidence gap remains. |
| T2: Why was rejecting the `M`-status review request wrong? | Spec line 49 prohibits changing Specification content independently of SC3. `dc2cc1a` and `199554f` each produced `M` against the approved Spec; `29902ee` restored it and made Step 4 reject `^[DMR]`. | accepted (P2 process). Spec §Scope/Out line 49 and the `M` statuses at `dc2cc1a`/`199554f`, followed by the clean `29902ee` restoration and `^[DMR]` guard, prove that SC3 was improperly used to narrow an independent exclusion; the conjunctive-contract rule is supported. |
| T3: Why were release counters stale? | Progress frontmatter counted only the pre-merge round, while lines 48-54 recorded the post-merge PR #224 review and PR #225 follow-ups. GitHub records give 11 review submissions, 20 fixed comments, and deferred comment `3791652634`. | accepted (P3 process bookkeeping). PR #224 contributes 1 submission/2 fixed comments and PR #225 contributes 10 submissions/18 fixed/1 deferred, yielding 11, 20, and 1; the ledger's frontmatter is stale despite its follow-up log. Cite the deferred root-level Roadmap-link comment explicitly in the transcript so the 20/1 split is auditable. |
| T4: Are the three previous carry-forwards correctly tracked? | The plan-verification trigger fired and failed; the `py.typed` trigger did not fire; maturity is 71/100 with the measured component/rate breakdown. The maturity row required a wording refresh but remains open, and no cause is inferred. | rejected: the first two carry-forwards are evidenced, but the maturity reconciliation proves only that 71 < 75. The prior carry-forward specifically requires fresh intervene-event inputs before asserting cause, while ROADMAP's open row still embeds stale `64`, `1%`, and `5%`; re-probe with the fresh component/rate measurements and state whether the row's text must be refreshed even though its open status is correct. Accepted after re-probe (P3 process/measurement). The fresh 71/100 breakdown and 1%/20% rates support only the measured drift and the open status; explicitly withholding causal inference correctly respects the prior carry-forward, and refreshing ROADMAP's stale 64/1%/5% text closes the evidence gap. |
| T5: Does a failure warrant compounding? | The reviewed command could emit an assertion failure yet exit 0, and its regex exercised zero target-validation branches. PR #225 added strict shell propagation and mutation probes. Existing `docs/solutions/` had low overlap and no fail-closed guidance. | accepted for compounding (P2 process): the reusable lesson is narrower than `ROADMAP.md:362`—execute the exact compound command fail-closed, inspect stderr and exit status, and mutation-prove the guard—so the `8f5baac` false green plus PR #225's `set -euo pipefail`/mutation probes and the negative `docs/solutions/` search justify a new solution. |

## Findings

### What worked well

- **What happened**: the repository now has one active Specification directory without moving historical files.
  **Why**: the approved design separated current policy from historical evidence, and ADR 0010 rejected both mass movement and dual active paths (`docs/adr/0010-spec-directory-policy.md:9-23`).
  **How to apply**: when policy and practice diverge, change the governing pointer and preserve artifacts that accurately record their original path.
  **Cites**: Spec SC1/SC3/SC5; fresh measurements T1-T5; merge `72e0aa5`.

- **What happened**: the follow-up did not stop at fixing the first two regex defects; it expanded the validator until its acceptance and rejection behavior were observable.
  **Why**: each review finding was reproduced against the exact Step 4 block, then mutation-tested before the next review round.
  **How to apply**: treat policy validators as programs with coverage, boundary, and failure-propagation contracts rather than as illustrative snippets.
  **Cites**: final Plan `:71-225`; PR #224 comments `3791367898`, `3791367902`; PR #225 merge `72e0aa5`.

- **What happened**: a mistaken review rejection was reversed before archive.
  **Why**: re-reading the approved Spec exposed that Scope/Out and Success Criteria are conjunctive, not alternatives.
  **How to apply**: verify every governing section before rejecting a technically plausible review comment.
  **Cites**: Spec `:44-50`; progress lines 50-52; heads `dc2cc1a`, `199554f`, `29902ee`.

### What to improve

- **What happened**: PR #224 merged after self-review had labeled a failing validator as passed.
  **Why**: the plan was amended after its original self-review; the compound shell block was not fail-closed; final status was accepted without inspecting the inner traceback; no failing mutation proved the guard.
  **How to apply**: pre-execute the exact published block, inspect output and status together, and mutation-prove each prohibited state before treating it as release evidence.
  **Cites**: Plan `2bc31fb`; amendment `3440adb`; reviewed head `8f5baac`; progress line 42; PR #224 comments `3791367898` and `3791367902`.

- **What happened**: SC3's narrow no-move/no-rename measurement was used twice to reject a valid content-change finding.
  **Why**: the measurement was treated as if it narrowed the independent Scope/Out exclusion.
  **How to apply**: satisfy the whole approved contract; a Success Criterion measurement cannot authorize behavior prohibited elsewhere in the Spec.
  **Cites**: Spec `:44-50,93-104`; progress lines 50-52.

- **What happened**: the release ledger's summary counters remained at one review, zero fixes, and two deferrals while its own log recorded the follow-up PR.
  **Why**: follow-up review events were appended to the narrative log but not projected back into frontmatter.
  **How to apply**: reconcile summary counters from PR API records before writing release metrics or archiving a loop.
  **Cites**: pre-closure progress frontmatter lines 18-21; log lines 48-54; PR #224/#225 review records.

- **What happened**: the ongoing maturity row still reported 64/1%/5% after telemetry moved to 71/1%/20%.
  **Why**: the row's open status was preserved, but its embedded measurements were not refreshed during intervening cycles.
  **How to apply**: distinguish tracker status from tracker evidence; an item can remain open while its measured text still requires correction.
  **Cites**: fresh `ec dashboard`; updated `ROADMAP.md:383`.

- **What happened**: ADR 0010 published a decision ID that `main` could not resolve even though the feature worktree could.
  **Why**: the decision was created in the feature worktree's repository-local database, and the release loop had no base-checkout promotion or resolution gate.
  **How to apply**: before archive or worktree removal, resolve every active EC decision ID from the base checkout; promote missing records while preserving their stable IDs so active references need no rewrite.
  **Cites**: pre-repair `ec decision show 0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b` failure from `main`; success from the feature worktree and after preservation in `main`; `ROADMAP.md:364`.

### Process observations

- The unavailable pre-merge independent reviewer explains the self-review mode but does not explain or excuse the false green. An exact failing mutation would have exposed both the masked assertion and the vacuous target match without model-dependent review.
- PR #225's ten review submissions were expensive but convergent: the validator moved from one success string with zero target proof to 68 file targets plus explicit Markdown, label, file-type, checkout-boundary, Git-status, and failure-status checks.
- Review comment `3791652634` is an explicit won't-fix for this validator: root-level non-Spec labeled Markdown links are outside the approved active-Specification-pointer contract. A general Markdown link checker would require a separate demonstrated need and contract.

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Pre-execute exact plan verification blocks and prove failure propagation with mutations | process | P3 | `ROADMAP.md:362` |
| Decide whether to ship `py.typed` when its revisit condition fires | architecture | P4 | `ROADMAP.md:363` |
| Reach maturity 75 without inferring causes from component scores alone | process/measurement | P3 | `ROADMAP.md:383` |
| Persist feature-worktree decisions before loop archival | decision traceability | P2 | `ROADMAP.md:364` |
| Root-level non-Spec labeled Markdown validation | explicit won't-fix for this validator | — | PR #225 comment `3791652634`; outside approved Spec scope, no separate need established |

## Lessons

- A compound verification command is not passing evidence unless every inner failure makes the overall command fail.
- A clean success run proves only acceptance. Mutation probes are required to demonstrate rejection paths.
- Scope/Out constraints and Success Criteria are conjunctive; a narrow measurement never cancels an independent prohibition.
- Release-loop frontmatter is a derived summary and must be reconciled against PR records before archive.
- An open metric target can retain the right status while carrying stale measured values.
- Every EC decision ID published by an active artifact must resolve from the base checkout before its feature worktree is removed.

## Knowledge compounding

Created `docs/solutions/workflow-issues/make-verification-commands-fail-closed.md`. Overlap with the three existing solution documents was low. Added **Fail-closed verification** to `CONCEPTS.md`; `AGENTS.md:5` already makes both knowledge locations discoverable, so no policy edit was needed.

Documentation complete - docs/solutions/workflow-issues/make-verification-commands-fail-closed.md

Retrospective complete - docs/retros/2026-08-16-spec-directory-policy-retro.md
