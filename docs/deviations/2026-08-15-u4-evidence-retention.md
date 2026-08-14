# Deviation: U4 evidence retention

**Date:** 2026-08-15
**Author:** implementation session for the verdict-quota review
**Authorized by:** user, during the post-implementation review

## Original contract

The approved, sealed plan is
`docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`.
Its File structure assigns U4 only `LESSONS.md`. The T1 matrix and U4 step 8
assume `.release-loop/evidence/U4/` is gitignored, make the U4 commit body the
durable record of the irreversible install replacement, and treat
`install-provenance.txt` as disposable local evidence.

## Observable behavior that deviates

Commit `edf4f18` retains the text provenance as a tracked repository artifact:

- `.release-loop/evidence/U4/install-provenance.txt` is committed.
- `.release-loop/.gitignore` ignores only
  `evidence/**/pre-install-*.tgz` rollback archives.
- The U4 commit body still carries the plan-required concise provenance, so the
  tracked text supplements rather than replaces that record.

This changes evidence persistence and `git clean -fdx` behavior from the
approved plan: the text record survives repository cleanup, while the local
package archive does not.

## Why

The plan's gitignore assumption did not match the repository. The actual
`.release-loop/.gitignore` ignored only `briefs/`, `reports/`, and `reviews/`,
and prior release loops committed transition evidence under
`.release-loop/archive/`. Silently deleting the 8 KiB provenance record would
have discarded useful diagnostic evidence for a machine-global irreversible
mutation. Committing the 624 KiB package archive would have introduced the
first tracked release-loop binary and duplicated a local rollback aid.

The split keeps the durable, reviewable text record and excludes only the
machine-specific binary archive. No production code, CLI output, database
state, or install behavior changes because of this retention decision.

## Evidence

| Claim | Command | Observed |
|---|---|---|
| U4 evidence was not gitignored | `git check-ignore -v .release-loop/evidence/U4/install-provenance.txt` before `edf4f18` | no matching rule |
| Repository already tracks release-loop evidence | `git ls-files .release-loop/archive | sed -n '1,5p'` | prior transition evidence paths returned |
| Repository tracks no release-loop binaries | `git ls-files .release-loop | grep -cE '\\.(tgz|tar|gz|zip)$'` | `0` |
| Text and archive have different durability value | `du -h .release-loop/evidence/U4/*` | provenance `8.0K`; archive `624K` |
| Final ignore scope is archive-only | `git check-ignore -v .release-loop/evidence/U4/pre-install-bin.tgz` | `.release-loop/.gitignore` archive rule matches |

## Traceability

- Approved plan: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`
- Deviating commit: `edf4f18`
- Review finding: validated P2 requirements-completeness finding against
  `.release-loop/.gitignore:5-7`
- User disposition: fix locally; do not modify the machine-global `ec` install
