# Repository audit implementation plan

Governing specification: [Repository audit corrections](../specs/2026-09-06-repository-audit.md).
Governing decision: EC 30f75661 (explicit global cleanup). Existing architecture remains unchanged.

## Execution

1. Record baseline checks and reproduce each defect using existing test infrastructure.
2. Add regression tests before correcting search, export, and guidance removal in independent file scopes.
3. Lock Git signal behavior with characterization tests, then move duplicate collectors into the existing Git utility module.
4. Review all changes and run affected suites, full tests, static checks, and package builds.
5. Record decision outcomes and report proven results, preserved changes, and validation gaps.

## Cleanup boundaries

Keep existing private import names as aliases. Do not introduce new configuration, dependencies, schemas, or module boundaries.
Limit changes to the reproduced search, export, guidance-removal, Git-signal deduplication, session-resume, and summary error paths.
Do not change ranking formulas or global installation settings.

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
| --- | --- | --- | --- |
| `test_semantic_filter_limit` | retained | `test_semantic_filter_limit` | Protect filtered recall. |
| `test_semantic_target` | retained | `test_semantic_target` | Protect requested result types. |
| `test_checkpoint_timestamp` | retained | `test_checkpoint_timestamp` | Protect incremental export. |
| `test_export_redaction` | retained | `test_export_redaction` | Protect configured filtering. |
| `test_disable_remove_guidance_preserves_sibling_in_same_group` | retained | `test_disable_remove_guidance_preserves_sibling_in_same_group` | Protect explicit cleanup and sibling hooks. |
| `TestSharedDecisionSignals` | retained | `TestSharedDecisionSignals` | Protect behavior during deduplication. |
| `test_resume_reopens_ended_session` | retained | `test_resume_reopens_ended_session` | Protect resumed session lookup. |
| `test_intent_summary_tolerates_lookup_failure` | retained | `test_intent_summary_tolerates_lookup_failure` | Keep optional summary failures contained. |

## Baseline infrastructure check

```bash plan-check id=git-baseline expected-status=0 evidence=docs/plans/evidence/2026-09-06-repository-audit-60e42358d50b/git-baseline.json
set -euo pipefail
.venv/bin/pytest tests/test_git_utils.py -q
```
