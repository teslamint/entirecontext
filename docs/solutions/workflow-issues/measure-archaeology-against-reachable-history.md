---
module: release-lifecycle
date: 2026-07-20
last_updated: 2026-07-21
problem_type: workflow_issue
component: archaeology-retrospective
severity: medium
applies_when:
  - "A release validates full git history before a squash merge"
  - "Operational state stores processed commit SHAs across rewritten reachability"
  - "A retrospective compares committed phase evidence with a later fresh verification run"
  - "Review fixes change the test inventory after an implementation checkpoint"
tags:
  - git-archaeology
  - squash-merge
  - success-criteria
  - release-retro
  - measurement-provenance
  - verification-evidence
---

# Measure archaeology against reachable history

## Context

Pull request (PR) #197 archaeologized all 334 eligible non-merge commits on its feature branch. After GitHub squash-merged the branch, a fresh `ec archaeologize --dry-run --limit 1000` on `main` reported 326 reachable commits, 325 already processed, and one pending extraction. The `archaeology_processed` table still contained 334 rows. It retained Secure Hash Algorithm (SHA) values from the now-unreachable feature-branch history.

## Guidance

Define full-history completion as a set comparison, not equality between two raw counts:

1. Enumerate the currently reachable non-merge commit SHAs with `git rev-list --no-merges HEAD`.
2. Compare that set with `archaeology_processed.commit_sha`.
3. Report reachable processed, reachable pending, and stored-but-unreachable rows separately.
4. Run the convergence measurement again after the merge if the workflow squash-merges. The squash commit is new history and may need extraction, even when the feature branch was complete.

Do not send the new commit to an external extraction backend only to make the metric green. Send it only when repository-content export is authorized. Record the pending reachable SHA honestly when authorization is absent.

### Preserve lifecycle provenance

Reachability drift is one instance of a broader release-evidence rule. Every verification result describes a particular repository state, command, and lifecycle stage. When a retrospective compares committed phase evidence with a fresh run:

1. Label the lifecycle stage, such as `U5 pre-review`, `post-review`, or `fresh post-merge`.
2. Cite the source artifact or Git ref. Include the command or measurement method.
3. Preserve the result observed at that stage instead of rewriting historical evidence to match the latest number.
4. Explain material deltas caused by added tests, changed selection filters, rewritten history, migrations, or backfills.
5. Keep the declared success criterion separate from the evidence used to judge it.
6. If the snapshots cannot be reconciled, record the discrepancy as unresolved instead of selecting the more favorable result.

## Why this matters

Raw count equality is not stable under history rewriting. A squash merge adds one new reachable commit and makes multiple processed branch commits unreachable at the same time. Both sides of the old comparison can change in opposite directions, even when no archaeology data is lost.

Test totals need the same provenance. A passing count is not timeless proof. It measures one repository state with one command. Unlabeled snapshots can make expected suite growth look like stale or inaccurate reporting. Both runs can still be correct for the states they measured.

## When to apply

- Release success criteria that claim all commits were processed.
- Operational bootstrap jobs whose idempotency table persists longer than branch reachability.
- Retrospectives that remeasure a pre-merge criterion after squash merge.
- Release evidence collected across implementation, review, and post-merge stages.
- PR reviews where committed evidence and a fresh verification run report different totals.

## Example

For PR #197, the correct post-merge statement is: `ec archaeologize` had processed 325 of 326 reachable non-merge commits. One new squash commit was pending. The table retained nine additional rows from superseded branch history. The pre-merge 334-of-334 result remains valid evidence for the implementation phase. It is not a fresh post-merge measurement.

For follow-up retrospective PR #198, the committed pre-review U5 snapshot recorded 164 targeted tests and 2,082 full-suite passes. A fresh post-merge run recorded 175 targeted tests and 2,093 full-suite passes. The retrospective preserved both snapshots and labeled their lifecycle stages. It explained that the later totals contained 11 additional tests after review fixes. The U5 evidence remained unchanged because it accurately described the state it measured.
