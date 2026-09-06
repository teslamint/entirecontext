# EntireContext repository audit

## Scope and evidence

Reviewed the local checkout for github.com/teslamint/entirecontext at HEAD 46fca9d027.
Independent reviews covered search and database paths, sync exports, and CLI and hook lifecycle paths.
This review does not certify every repository path or the production installation.

The implementation follows the [specification](../specs/2026-09-06-repository-audit.md) and [validated plan](../plans/2026-09-06-repository-audit.md).

## Corrected findings

| Severity | Location | Reproduced defect and correction |
| --- | --- | --- |
| Important | `core/embedding.py:94` | Filters ran after candidate truncation. Search now limits accepted results. |
| Important | `cli/search_cmds.py:100`, `core/cross_repo.py:235`, `mcp/tools/search.py:104` | Semantic searches ignored the requested source type. Callers now pass their existing target. |
| Critical | `sync/exporter.py:113` | Mixed timestamp formats omitted later checkpoints. Export now compares UTC instants with microsecond precision. |
| Critical | `sync/exporter.py:75`, `sync/exporter.py:128`, `sync/export_flow.py:30` | Metadata bypassed configured secret filters. Export now filters descriptive values without changing JSON structure or identifiers. |
| Important | `cli/project_cmds.py:497` | Mixed hook groups retained the removed EC command. Cleanup now detects nested changes. |
| Important | `hooks/session_lifecycle.py:96` | Resumed sessions remained ended. Resume now clears the end timestamp. |
| Important | `hooks/session_lifecycle.py:189` | Early summary lookup failures raised an uninitialized-variable error. Optional summary generation now contains those errors. |

All source locations above are relative to `src/entirecontext/`.
New regression cases failed before the corresponding corrections.

## Refactoring

Moved diff and recent-commit collectors into the existing `core/git_utils.py` module.
Each collector now has one implementation instead of two.
The two callers retain their existing private names through import aliases.
Six characterization tests protect real Git results, truncation, ordering, limits, and subprocess failure behavior.
The Git and decision-hook suites passed 137 tests after extraction.

## Validation

- The full baseline passed 2,254 tests. Cache permissions caused four failures and five errors; missing MCP dependencies caused most skips.
- Installed the existing declared MCP extra in the local environment. The dependency manifest and lockfile did not change.
- Corrected cache and isolated-build setup. The build-provenance suite passed all 12 tests.
- Ruff lint and format checks passed. Mypy passed for 127 source files. The diff whitespace check passed.
- Built the wheel and source distribution. Both contain the current 126 runtime Python files and the expected CLI entry point.
- The plan validator verified all test dispositions and recorded check evidence.
- Final full suite on Python 3.13.11: **2,394 passed, 1 skipped, 1 warning**, in 126.67 seconds.
- Command: `UV_CACHE_DIR=/tmp/ec-audit-uv-cache .venv/bin/pytest -q`.
- The skip requires explicit performance-file output. The warning concerns an existing deprecated pytest fixture declaration.

## Limits and follow-up

Historical shadow-branch files and commits were not rewritten. Filtering applies when records are exported.
The coordinator still records a completion-time sync boundary at `sync/coordinator.py:259`.
A record created after export selection but before that boundary can be missed by the next incremental export.
Follow-up: [ADR 0020](../adr/0020-full-sync-export.md) resolves this issue with full enumeration and four real-Git regressions.
The paragraph above describes the original finding, before that correction.

The optional performance-recording test remains opt-in. No model downloads or production semantic-quality measurements were performed.
Deterministic stored vectors tested the changed search contracts.

## Decisions and preservation

Applied decision 30f75661 to preserve unrelated global hooks during explicit cleanup; recorded an accepted outcome.
Considered decision 3cbd031b; repository fault isolation remains unchanged.
Reviewed decision 6467b736; no storage-size code changed.
Applied lesson e2be8687 to remove duplicate signal collectors and recorded agreement.
Created decision 5a967bfd for the shared collectors and recorded an accepted outcome.
Recorded assessment 55e70f0c with agreement after checking the current diff against the roadmap.
The automatic checkpoint verdict was bookkeeping, not verification of the implementation.

Preserved the existing experiment output and earlier LESSONS content.
The feedback command regenerated one LESSONS line; that incidental change was reverted.
The audit handoff preceded implementation commits. It made no pushes, GitHub comments, or production installation changes.
