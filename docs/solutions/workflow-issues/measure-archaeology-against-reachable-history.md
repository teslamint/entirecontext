---
module: release-lifecycle
date: 2026-07-20
problem_type: workflow_issue
component: archaeology-retrospective
severity: medium
applies_when:
  - "A release validates full git history before a squash merge"
  - "Operational state stores processed commit SHAs across rewritten reachability"
tags:
  - git-archaeology
  - squash-merge
  - success-criteria
  - release-retro
---

# Measure archaeology against reachable history

## Context

PR #197 archaeologized all 334 eligible non-merge commits on its feature branch. After GitHub squash-merged the branch, a fresh `ec archaeologize --dry-run --limit 1000` on `main` reported 326 reachable commits, 325 already processed, and one pending extraction. The `archaeology_processed` table still contained 334 rows because it retained SHAs from the now-unreachable feature-branch history.

## Guidance

Define full-history completion as a set comparison, not equality between two raw counts:

1. Enumerate the currently reachable non-merge commit SHAs with `git rev-list --no-merges HEAD`.
2. Compare that set with `archaeology_processed.commit_sha`.
3. Report reachable processed, reachable pending, and stored-but-unreachable rows separately.
4. If the workflow squash-merges, run the convergence measurement again after merge. The squash commit is new history and may need extraction even when the feature branch was complete.

Do not send the new commit to an external extraction backend merely to make the metric green unless repository-content export is authorized. Record the pending reachable SHA honestly when authorization is absent.

## Why this matters

Raw count equality is not stable under history rewriting. A squash merge simultaneously adds one new reachable commit and makes multiple processed branch commits unreachable, so both sides of the old comparison can change in opposite directions without any archaeology data loss.

## When to apply

- Release success criteria that claim all commits were processed.
- Operational bootstrap jobs whose idempotency table persists longer than branch reachability.
- Retrospectives that remeasure a pre-merge criterion after squash merge.

## Example

For PR #197, the correct post-merge statement is: 325 of 326 reachable non-merge commits were processed, one new squash commit was pending, and the table retained nine additional rows from superseded branch history. The pre-merge 334-of-334 result remains valid evidence for the implementation phase, but it is not a fresh post-merge measurement.
