# Deviation: Signal C benchmark prints JSON instead of writing a file

**Date:** 2026-11-05
**Author:** orchestrating session for PR #293
**Authorized by:** the goal-mode task scope (fix review findings before merge); recorded here because the spec is approved

## Original contract

The approved spec `docs/specs/2026-11-05-signal-c-prompt-ranking-design.md` shows the benchmark in scenario S1 with `--output /tmp/signal-c.json`. The approved plan `docs/plans/2026-11-05-001-feat-signal-c-prompt-ranking-plan.md` U1 step 7 says "Output JSON", and its U6 fence uses `--output`.

## Observable behavior that deviates

The script has no `--output` option. `--json` prints the full report to standard output, and the user redirects it to save it. Without `--json`, the script prints the summary table, as before. The report content is unchanged.

## Why

SonarCloud rule `pythonsecurity:S8707` flagged the `--output` file write on PR #293 as path traversal through a command-line argument, and the quality gate failed (new security rating C). The script is a local developer tool, so the practical risk is low. Removing the write removes the finding at no functional cost, because shell redirection gives the same result.

## Evidence

| Claim | Command | Observed |
|---|---|---|
| Sonar flagged the file write | `curl -s "https://sonarcloud.io/api/issues/search?componentKeys=teslamint_entirecontext&pullRequest=293&types=VULNERABILITY&resolved=false"` | one issue, `pythonsecurity:S8707`, `semantic_ranking_benchmark.py` line 177 |
| Tests still cover the report | `uv run pytest -q tests/test_semantic_ranking_benchmark.py` | `6 passed` |

## Scope

Only the benchmark script's output mechanism changes. Ranking, the worker, the hook, configuration, and the recorded benchmark numbers do not change.
