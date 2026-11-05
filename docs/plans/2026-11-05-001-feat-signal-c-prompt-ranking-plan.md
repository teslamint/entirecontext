---
schema: plan/v1
title: Signal C Prompt-Time Ranking
type: feat
status: draft
date: 2026-11-05
execution: code
origin: docs/specs/2026-11-05-signal-c-prompt-ranking-design.md
mode: auto
---

# Signal C Prompt-Time Ranking Plan

## Goal

Build the offline semantic-ranking benchmark first, then connect decision embeddings to prompt-time injection as an opt-in, default-off, two-pass signal. Default behavior stays byte-identical.

## Assumptions and Preconditions

no-live-assumptions: this plan adds no live assumption beyond the approved spec. The Assumption Recheck section reruns every spec assumption with fresh results.

## Trade-offs

| Option | Metric it improves | Metric it degrades | Measured cost |
|---|---|---|---|
| Selected: inject a fake embedder in every test | Tests run without the optional extra and stay deterministic | Real-model behavior is not exercised by the suite | 0 new test dependencies; real-model numbers come only from the U6 report |
| Rejected: install the `semantic` extra in CI | Real-model coverage | CI time and download size; a network dependency in tests | 5.04 s warm model load per process plus the model download |
| Selected: launch the semantic worker from a `finally` block after the injection decision | The 250 ms ranking budget is untouched | Hook wall time grows by one `Popen` when enabled | 1 extra process start per enabled prompt |
| Rejected: launch before the ranking thread starts | Simpler control flow | The launch shares wall time with ranking and runs even when injection then returns early | 7 early-return paths in `_handle_user_prompt` would each need the same gate |
| Selected: one exclusive project worker that drains all sessions | 1 model load per burst | A prompt from another session waits behind the current embed | 0.199 s per embedded prompt (spec measurement) |
| No rejected alternative: per-session workers were excluded by the spec | Not applicable: excluded upstream | Not applicable: excluded upstream | 0 extra options evaluated |

## Non-goals

- Default enablement, model changes, MCP or CLI ranking changes, dashboard metrics, schema changes, SessionStart pre-warm (spec "Out").
- CHANGELOG and version edits belong to shipping, not to a unit.

## Residual Risks

- The current model gives no cross-lingual signal (cosine −0.033). Korean prompts against English decisions may gain nothing; the U6 report measures it.
- Tests use a fake embedder, so a real-model integration fault would surface only in the U6 run and in manual opt-in use.

## Success Criteria

The spec's Success Criteria 1-7 are this plan's acceptance criteria. Each proving command is in the fence after its criterion.

1. Benchmark gain on the fixture, equal result on its negative control (U1).

```bash implementation-only reason=success-criterion-proof
UV_NO_BUILD_ISOLATION=1 uv run pytest -q tests/test_semantic_ranking_benchmark.py
```

2. Default configuration changes nothing; negative control: `enabled = true` launches once (U5).

```bash implementation-only reason=success-criterion-proof
UV_NO_BUILD_ISOLATION=1 uv run pytest -q -k test_default_config_never_launches_semantic_worker
```

3. Semantic-only decision surfaces on the next prompt; negative control: absent with `semantic_scores=None` (U2-U5).

```bash implementation-only reason=success-criterion-proof
UV_NO_BUILD_ISOLATION=1 uv run pytest -q -k test_two_pass_semantic_candidate_surfaces_on_next_prompt
```

4. Every failure falls back to baseline; negative control: the valid-scores case differs (U3-U5).

```bash implementation-only reason=success-criterion-proof
UV_NO_BUILD_ISOLATION=1 uv run pytest -q -k test_semantic_fail_closed
```

5. Budget holds with the signal active; negative control: removing the scores read or the ranker signal empties the expected output (U5).

```bash implementation-only reason=success-criterion-proof
UV_NO_BUILD_ISOLATION=1 uv run pytest -q -k test_user_prompt_hook_surfaces_semantic_decision_within_budget
```

6. Benchmark report committed with all four subsets (U6). Rubric: a fresh rerun of the recorded command reproduces the numbers on the same database state.
7. Full repository gate passes (Verification procedure fence).

## Assumption Recheck

All commands ran against the main checkout database and the worktree at `353ba17`, observed 2026-11-05T06:12:04Z to 06:12:11Z.

| Approved claim | Exact command | Fresh evidence | Outcome |
|---|---|---|---|
| 304 decisions, all embedded, one model | spec row 1 command | 304 / 304 / `all-MiniLM-L6-v2` 304 | match |
| Large Korean share of prompts | spec row 2 command | 1792 of 4200 turns (4190 at spec time; capture continues) | match |
| 618 file-labeled turns, 388 Hangul, 160 linked decisions | spec row 3 command | 618 / 388 / 160 | match |
| 87 of 304 decisions contain Hangul | spec row 4 command | 87 | match |
| Korean-only prompt yields no FTS query | spec row 5 command | `None` | match |
| No cross-lingual signal | spec row 6 command | −0.0326 / 0.0035 / 0.2712 | match |
| Model load cannot fit 250 ms | spec row 7 command | 5.04 s warm, encode of 4 texts 0.299 s | match (warm cache is faster than the cold 24.66 s; both exceed 250 ms) |
| Budget 250 ms; ranking p95 61.8 ms | spec row 8 command | `inject_timeout_ms: 250` at `core/config.py:147` | match |
| Zero-relevance candidates are dropped | spec row 9 command | `core/decisions.py:1644` | match |
| No `sentence-transformers` in the dev environment | spec row 10 command | `ModuleNotFoundError` | match |

Contradictions require a separate committed deviation addendum before finalization; the approved specification stays unchanged. Unavailable evidence would stay a planning-time unknown.

## Architecture notes

- Governing records: spec `docs/specs/2026-11-05-signal-c-prompt-ranking-design.md`, EC decision `d3430f87` (two-pass semantic retrieval), decision `dedaf5ed` (redact before any prompt write).
- Known Pattern: `hooks/turn_capture.py:63-132` (`_maybe_launch_prompt_surfacing_worker`) is the prompt tmp-file contract: `redact_content` upstream, then `filter_secrets`, then `redact_for_query`, `O_CREAT | O_EXCL`, mode 0600. Reuse its sanitizer `_sanitize_id_for_path` for session IDs in file names.
- Known Pattern: `core/async_worker.py` `launch_worker_exclusive` and `file_lock` (PR #289) are the only allowed launch and lock primitives. The worker uses the same lock file (`.entirecontext/worker-semantic.lock`) for its exit check.
- Known Pattern: `core/embedding.py` `cosine_similarity` raises `ValueError` on dimension mismatch; `embed_text` builds a model per call, so the worker must hold one `SentenceTransformer` instance for its lifetime instead of calling `embed_text`.
- `rank_related_decisions` (`core/decisions.py:1349`) is called from MCP and CLI paths. The new keyword `semantic_scores: dict[str, float] | None = None` must keep every existing call unchanged.
- Hook-path invariant: with `[decisions.semantic].enabled = false`, `_handle_user_prompt` must not read or write any semantic state file and must not call the launcher.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/experiments/semantic_ranking_benchmark.py` | Create | Read-only offline benchmark (R1). |
| `tests/test_semantic_ranking_benchmark.py` | Create | Benchmark E2E and unit tests. |
| `src/entirecontext/core/config.py` | Modify | `[decisions.semantic]` defaults (R2). |
| `src/entirecontext/core/decisions.py` | Modify | `semantic_scores` signal in `rank_related_decisions` (R4). |
| `src/entirecontext/core/decision_prompt_surfacing.py` | Modify | Pass scores through `rank_decisions_for_prompt`. |
| `src/entirecontext/core/semantic_scores.py` | Create | Pending-prompt and scores-file store (R3, R4). |
| `src/entirecontext/core/semantic_worker.py` | Create | Worker loop and exit protocol (R3). |
| `src/entirecontext/cli/decisions_cmds.py` | Modify | Hidden `semantic-worker` command. |
| `src/entirecontext/hooks/handler.py` | Modify | Read scores in the ranking thread; launch from `finally` (R4, R3). |
| `tests/test_semantic_prompt_ranking.py` | Create | Ranker, store, worker, and hook tests. |
| `docs/adr/0022-opt-in-two-pass-semantic-decision-ranking.md` | Create | ADR for config and state-file contract (R7). |
| `docs/spec.md`, `docs/entirecontext-project-manual.md` | Modify | Document `[decisions.semantic]`. |
| `docs/perf/2026-11-05-signal-c-benchmark.md` | Create | Benchmark report on the project database (R6). |
| `ROADMAP.md` | Modify | Close both Signal C rows (R6). |

## Global Constraints

- No schema migration, no new dependency (`sentence-transformers` stays in the existing `semantic` extra).
- Tests never import `sentence_transformers`; they inject an embedder.
- Every semantic failure returns the baseline ranking; no exception leaves the hook or the ranker.
- Prompt text never appears in a scores file, log line, hook warning, or telemetry row.
- The benchmark never writes to the database it reads.

## Scenario coverage map

| Scenario | Unit chain | Observable verification |
|---|---|---|
| S1 | U1 → U6 | `test_benchmark_reports_semantic_gain_on_fixture`; the U6 report on the project database |
| S2 | U1 | `test_benchmark_reports_semantic_gain_on_fixture` with `--model` routed through the injected embedder factory |
| S3 | U2 → U3 → U4 → U5 | `test_two_pass_semantic_candidate_surfaces_on_next_prompt` |
| S4 | U4 → U5 | `test_semantic_fail_closed` (missing package case) |
| S5 | U2 → U5 | `test_default_config_never_launches_semantic_worker` |

## Implementation Units

## U1: Offline benchmark (measurement first)

Files: create `scripts/experiments/semantic_ranking_benchmark.py`, `tests/test_semantic_ranking_benchmark.py`.

Steps:
1. Open the database with `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` and `row_factory = sqlite3.Row`.
2. Items: turns whose `files_touched` is a non-empty JSON list. Relevant set: `decision_files.decision_id` joined on the touched paths, restricted to decisions with `created_at <= turn.timestamp`. Drop items with an empty relevant set; count them.
3. Prompt text: apply `redact_content`, `filter_secrets`, `redact_for_query` with the project config.
4. Baseline ranker: `rank_related_decisions(conn, file_paths=[], diff_text=prompt, commit_shas=[], until=turn.timestamp, limit=k)`.
5. Semantic ranker: same call with `semantic_scores` from the injected embedder, scored against decision vectors created at or before the turn. For `--model` different from the stored model, embed decision texts in memory with `_build_decision_embed_text`; never write.
6. Metrics: hit@k and MRR for four subsets: all, Hangul (`[가-힣]` in prompt), no file mention (no basename of a relevant file appears in the prompt), Hangul and no file mention.
7. Output JSON with counts, metrics, `k`, model name, database path digest, and timestamp; print a short table.
8. The embedder factory is a module-level function parameter so tests pass a fake one.

Tests (written first, must fail before the script exists): `test_benchmark_reports_semantic_gain_on_fixture`, `test_benchmark_excludes_decisions_created_after_prompt`, `test_benchmark_reports_no_file_mention_subset`, `test_benchmark_opens_database_read_only`.

Acceptance: the four tests pass; the negative-control English item reports equal hit@1 for both rankers.

Commit: `feat(experiments): add offline semantic ranking benchmark` (separate commit, Measure-First rule).

## U2: Ranker signal and configuration

Files: `core/config.py`, `core/decisions.py`, `core/decision_prompt_surfacing.py`, `tests/test_semantic_prompt_ranking.py`.

Steps:
1. Add `"semantic": {"enabled": False, "weight": 3.0, "min_similarity": 0.3, "top_n": 20, "max_age_seconds": 900, "model": "all-MiniLM-L6-v2"}` under `decisions` in the defaults.
2. Add keyword `semantic_scores: dict[str, float] | None = None` and `semantic_weight: float = 0.0`, `semantic_min_similarity: float = 1.0` to `rank_related_decisions`. With `None`, no code path changes.
3. With scores: add each ID with similarity ≥ `semantic_min_similarity` to the candidate set; add `semantic_weight * similarity` to `relevance_base`; record `score_breakdown["semantic"]`.
4. `rank_decisions_for_prompt` gains `semantic_scores: dict[str, float] | None = None` and forwards it with the weights read from `[decisions.semantic]`.

Tests: ranker happy path (semantic-only candidate surfaces), threshold edge (similarity below `min_similarity` adds nothing), `None` parity (output equal to a call without the keyword over a fixed fixture).

## U3: Scores store

Files: create `core/semantic_scores.py`; tests.

Steps:
1. Paths under `<project_root>/.entirecontext/state/`: `semantic-prompt-<sid>.txt`, `semantic-scores-<sid>.json`; `<sid>` from `_sanitize_id_for_path`.
2. `write_pending_prompt(repo_path, session_id, prompt, config)`: pass the text through `redact_content`, `filter_secrets`, and `redact_for_query` in that order; write a unique temporary file with `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o600)`; `os.replace` onto the pending path.
3. `take_pending_prompts(repo_path) -> list[tuple[str, Path]]`: for each pending file, `os.replace` it to `semantic-prompt-<sid>.<pid>.processing`; return session ID and claimed path.
4. `write_scores(repo_path, session_id, scores, *, model, top_n)`: JSON `{"model", "computed_at", "scores": {id: similarity}}` keeping the `top_n` highest similarities; temporary file plus `os.replace`.
5. `invalidate_scores(repo_path, session_id)`: delete the session's scores file if present. `write_pending_prompt` calls it after the pending file is in place, so scores from an older prompt never outlive a newer one.
   Per-session ordering: `write_pending_prompt` (pending replace plus `invalidate_scores`) and the worker's publish step (`publish_scores_if_current`: check that no pending file exists for the session, then `write_scores`) each run under `file_lock(.entirecontext/state/semantic-<sid>.lock)`. If the hook wins, the worker sees the newer pending file and discards its result. If the worker wins, the hook's invalidation deletes the older scores.
6. `read_fresh_scores(repo_path, session_id, *, model, max_age_seconds, now=None) -> dict[str, float] | None`: return `None` for a missing, corrupt, other-model, or stale file.

Tests: `test_pending_prompt_file_is_redacted_and_private`, `test_prompt_replaced_during_processing_is_not_deleted` (also asserts that the older prompt's scores are not published after the newer pending file exists), and the stale, corrupt, model-mismatch, and superseded-by-newer-prompt cases of `test_semantic_fail_closed`.

## U4: Worker

Files: create `core/semantic_worker.py`; modify `cli/decisions_cmds.py`; tests.

Steps:
1. `run_semantic_worker(repo_path, *, embedder_factory=None)`: build one embedder (default: `SentenceTransformer(model)`). On `ImportError`, record one hook warning via the existing hook-warning helper, then run the same loop with a discard action: claim each pending prompt, use `invalidate_scores` for its session, and delete the claimed file. The loop ends only through the step 4 exit protocol, so a prompt that arrives after a claim pass is discarded by the next pass or by a newly launched worker.
2. Load decision vectors for the configured model once per loop pass; skip vectors whose length differs from the query vector.
3. Loop: `take_pending_prompts`; for each, embed, score with `cosine_similarity`, and publish through `publish_scores_if_current` with `top_n` from `[decisions.semantic]`. On any failure for that prompt (no vectors, every vector a different length, embed error), use `invalidate_scores` for the session instead of writing. Delete the claimed file in `finally`.
4. Exit protocol: under `file_lock(<project>/.entirecontext/worker-semantic.lock)`, if no pending prompt file exists, delete `worker-semantic.pid` and return; otherwise release and continue.
5. CLI: a hidden Typer subcommand `semantic-worker` under the `decision` group, with a `--repo-path` option and `hidden=True`.

Tests: `test_concurrent_prompts_launch_one_semantic_worker`, `test_prompt_arriving_at_worker_exit_is_processed`, and the missing-package, no-vectors, and dimension-mismatch cases of `test_semantic_fail_closed`.

## U5: Hook wiring

Files: `hooks/handler.py`; tests.

Steps:
1. In `_rank_and_trim_in_thread`, when `[decisions.semantic].enabled`, use `read_fresh_scores` and pass the result to `rank_decisions_for_prompt`. When disabled, do not touch the file system.
2. Wrap the body of `_handle_user_prompt` after `session_id` and `workspace_root` resolve in `try/finally`. In `finally`, use `_maybe_launch_semantic_worker(data, config, repo_path, workspace_root)` only if all seven spec launch conditions hold; it writes the pending prompt and calls `launch_worker_exclusive(repo_path, [sys.executable, "-m", "entirecontext.cli", "decision", "semantic-worker", "--repo-path", repo_path], pid_name="worker-semantic")`. Any exception becomes a hook warning.

Tests: `test_default_config_never_launches_semantic_worker`, `test_launch_conditions_gate_semantic_worker`, `test_two_pass_semantic_candidate_surfaces_on_next_prompt`, `test_user_prompt_hook_surfaces_semantic_decision_within_budget`, and the valid-scores control of `test_semantic_fail_closed`.

## U6: Contract docs, measurement report, roadmap

Files: ADR 0022, `docs/spec.md`, `docs/entirecontext-project-manual.md`, `docs/perf/2026-11-05-signal-c-benchmark.md`, `ROADMAP.md`.

Steps:
1. ADR 0022: context (unused embeddings, two-pass decision `d3430f87`), decision (opt-in config and the two state files), rejected options from the spec Trade-offs, consequences.
2. Document every `[decisions.semantic]` key with its default in `docs/spec.md` and the manual.
3. Run the benchmark on the project database with the real model, using the command in the fence below. Record counts and all four subsets for both rankers, and the exact command. Report counts and metrics only; no prompt text, decision titles, or paths.

```bash implementation-only reason=real-model-benchmark
uv run --extra semantic python scripts/experiments/semantic_ranking_benchmark.py --repo /Users/teslamint/workspace/entirecontext --k 5 --output /tmp/signal-c-benchmark.json
```
4. Mark ROADMAP Signal C rows (v0.8.0 `[~]` and Later) `[x]` with a link to the report.

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
| `test_benchmark_reports_semantic_gain_on_fixture` | retained | `test_benchmark_reports_semantic_gain_on_fixture` | U1 |
| `test_benchmark_excludes_decisions_created_after_prompt` | retained | `test_benchmark_excludes_decisions_created_after_prompt` | U1 |
| `test_benchmark_reports_no_file_mention_subset` | retained | `test_benchmark_reports_no_file_mention_subset` | U1 |
| `test_benchmark_opens_database_read_only` | retained | `test_benchmark_opens_database_read_only` | U1 |
| `test_default_config_never_launches_semantic_worker` | retained | `test_default_config_never_launches_semantic_worker` | U5 |
| `test_launch_conditions_gate_semantic_worker` | retained | `test_launch_conditions_gate_semantic_worker` | U5 |
| `test_two_pass_semantic_candidate_surfaces_on_next_prompt` | retained | `test_two_pass_semantic_candidate_surfaces_on_next_prompt` | U5 |
| `test_semantic_fail_closed` | retained | `test_semantic_fail_closed` | U3, U4, U5 cases |
| `test_concurrent_prompts_launch_one_semantic_worker` | retained | `test_concurrent_prompts_launch_one_semantic_worker` | U4 |
| `test_prompt_arriving_at_worker_exit_is_processed` | retained | `test_prompt_arriving_at_worker_exit_is_processed` | U4 |
| `test_prompt_replaced_during_processing_is_not_deleted` | retained | `test_prompt_replaced_during_processing_is_not_deleted` | U3 |
| `test_pending_prompt_file_is_redacted_and_private` | retained | `test_pending_prompt_file_is_redacted_and_private` | U3 |
| `test_user_prompt_hook_surfaces_semantic_decision_within_budget` | retained | `test_user_prompt_hook_surfaces_semantic_decision_within_budget` | U5 |

## Verification procedure

- Each unit: its tests fail before the change and pass after; mutation-check the guards named in the spec negative controls (disable the scores read, the candidate addition, the launch gate, the exit re-check, the claim rename).
- After U5: run the full repository gate in the fence below.

```bash implementation-only reason=repository-gate
UV_NO_BUILD_ISOLATION=1 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src/entirecontext/
```
- Smoke: isolated temporary repository and `HOME`, synthetic decisions, `enabled = true`, real `UserPromptSubmit` handler invoked twice with a fake-embedder worker, observe the scores file and the second injection.

- Pre-implementation baseline: `semantic_search_decisions` is defined in `core/embedding.py` and has no caller elsewhere in `src/`. The plan-check below records that state; U5 is the first caller path.

```bash plan-check id=semantic-search-unwired expected-status=0 evidence=docs/plans/evidence/2026-11-05-001-feat-signal-c-prompt-ranking-plan-b33a1b58fad6/semantic-search-unwired.json
set -euo pipefail
test "$(git grep -l 'semantic_search_decisions(' -- src/entirecontext | wc -l | tr -d ' ')" = 1
```

## Mutation/failure-state matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Carry-forward trigger audit

Audited `ROADMAP.md` on this branch after merging `8a82dbd` (origin/main after #290): 8 open checkbox rows. The Rich-output path-assertion row (line 408) was closed by #290 before this audit; the full gate below therefore runs without `--basetemp`.

| Open rows | Trigger class | Observation | Disposition |
|---|---|---|---|
| Signal C (v0.8.0 `[~]`), Signal C prompt-time ranking (Later) | event-based | This plan implements them | Folded in: U6 step 4 |
| applied_context_rate ≥ 10% | drift-based | Out of goal scope (measurement item) | Not fired by this plan |
| General Git C-style path escapes | event-based | Open PR #291 | Not fired by this plan |
| Post-squash archaeology convergence | drift-based | Out of goal scope (cost item) | Not fired by this plan |
| Alpha → stable | edit-based (README badge, classifier) | Not edited | Not fired |
| Sharpen product messaging; Team-scoped decisions | unclassifiable; event-based | Not touched | Not fired |

Attestation: every open row above was compared with the File structure table.

## Deferred to Follow-Up Work

- Default enablement or a multilingual model, decided from the U6 report.
- Orphaned scores-file cleanup at SessionEnd (spec Open Decisions; implementation may add it inside U3 if trivial).

## Open unknowns

Planning-time: none.
Implementation-time: exact hook-warning helper reused by the worker; final `weight` and `min_similarity` defaults if the fixtures show 3.0 and 0.3 cannot separate the control case.
