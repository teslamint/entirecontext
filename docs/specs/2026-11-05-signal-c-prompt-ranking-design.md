---
title: Signal C Prompt-Time Ranking
status: approved
date: 2026-11-05
schema: spec/v1
mode: auto
---

# Signal C Prompt-Time Ranking Design

_Created 2026-11-05._

## Overview

Decision embeddings are written for every decision, but no ranking path reads them. This spec does two things in order. First, it builds an offline benchmark that measures prompt-to-decision retrieval with and without semantic similarity. Second, it connects semantic similarity to prompt-time decision injection as an opt-in, default-off, two-pass signal. Default behavior does not change.

Governing records: ROADMAP rows "Signal C: semantic similarity" (v0.8.0, `[~]`) and "Signal C prompt-time ranking" (Later). EC decision `d3430f87` ("Implement semantic retrieval as an asynchronous two-pass system"). Brainstorm `docs/brainstorms/proactive-decision-injection.md`, which excludes embedding computation at inject time.

## User Scenarios

### S1: Maintainer measures whether semantic ranking helps

A maintainer wants evidence before enabling the signal. The maintainer runs the benchmark against the project database in read-only mode.

```bash
uv run python scripts/experiments/semantic_ranking_benchmark.py --repo . --k 5 --output /tmp/signal-c.json
```

The report shows hit@5 and mean reciprocal rank (MRR) for the current ranker and for the ranker plus semantic similarity. It shows the same metrics for the subset of prompts that contain Hangul, and for the subset whose prompt names none of its labeled files.

### S2: Maintainer compares a different embedding model offline

The maintainer passes `--model <name>`. The benchmark embeds decisions with that model in memory. It does not write to the database.

### S3: User opts in

The user adds this to `.entirecontext/config.toml`:

```toml
[decisions.semantic]
enabled = true
```

After the first prompt of a session, a background worker computes semantic scores for that prompt. From the second prompt on, the synchronous injection reads the latest fresh scores and can surface a decision that no file, commit, or full-text signal found.

### S4: User without the `semantic` extra opts in

`sentence-transformers` is not installed. Injection behaves exactly as with the signal off. The worker records one hook warning and exits.

### S5: Default user

The user changes nothing. No worker starts, no state file is written, and ranking output is identical to the current output.

## Scope

### In

- R1: Offline benchmark script with an E2E test on a synthetic fixture.
- R2: Opt-in `[decisions.semantic]` configuration, default off.
- R3: Exclusive background worker that embeds the latest redacted prompt and writes per-session scores.
- R4: Synchronous injection reads fresh scores and passes them to the ranker as an additional signal that can add candidates.
- R5: Fail-closed behavior for every semantic failure.
- R6: Benchmark results on the project database committed as a report. ROADMAP rows updated.
- R7: ADR for the new configuration and state-file contract.

### Out

- Making semantic ranking the default. That needs a later decision based on R6 results.
- Changing the default embedding model or re-embedding stored decisions.
- Semantic ranking in MCP or CLI decision-ranking commands (`ec decision related`, `ec_decision_related`). The new keyword argument defaults to no semantic scores.
- A dashboard metric for semantic hits.
- Database schema changes.
- A SessionStart pre-warm worker.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| Every decision already has a stored embedding, all from one model | `sqlite3 "file:.entirecontext/db/local.db?mode=ro" "select count(*) from decisions; select count(distinct source_id) from embeddings where source_type='decision'; select model_name, count(*) from embeddings group by model_name;"` | 2026-11-05T05:51:44Z | 304 decisions; 304 embedded; one model `all-MiniLM-L6-v2` (304 rows) | Project database, main checkout |
| A large share of prompts are Korean | `sqlite3 "file:.entirecontext/db/local.db?mode=ro" "select count(*) from turns; select count(*) from turns where user_message glob '*[가-힣]*';"` | 2026-11-05T05:51:44Z | 1792 of 4190 turns contain Hangul | Project database |
| Benchmark items with file labels exist | `sqlite3 "file:.entirecontext/db/local.db?mode=ro" "select count(*) from turns where files_touched is not null and files_touched not in ('','[]'); select count(*) from turns where user_message glob '*[가-힣]*' and files_touched is not null and files_touched not in ('','[]'); select count(distinct decision_id) from decision_files;"` | 2026-11-05T05:57:32Z | 618 turns with touched files (388 with Hangul); 160 decisions linked to files | Project database |
| Decisions are mostly English | `sqlite3 "file:.entirecontext/db/local.db?mode=ro" "select count(*) from decisions where title glob '*[가-힣]*' or rationale glob '*[가-힣]*';"` | 2026-11-05T05:57:32Z | 87 of 304 decisions contain Hangul | Project database |
| The full-text signal produces no query for a Korean-only prompt | `uv run python -c "from entirecontext.core.decisions import _tokenize_diff_for_fts as t; print(repr(t('랭킹에 의미 유사도를 연결하는 방법을 정리해줘')))"` | 2026-11-05T05:56:51Z | `None` (an English prompt yields a 5-token OR query) | `src/entirecontext/core/decisions.py:1195-1241` |
| The current model gives no cross-lingual signal | `~/.local/share/uv/tools/entirecontext/bin/python -c "from sentence_transformers import SentenceTransformer, util; m=SentenceTransformer('all-MiniLM-L6-v2'); e=m.encode(['랭킹에 의미 유사도를 연결하는 방법','connect semantic similarity to ranking','bump the mypy version in the lock file','lock 파일의 mypy 버전 올리기']); print(float(util.cos_sim(e[0],e[1])), float(util.cos_sim(e[1],e[2])), float(util.cos_sim(e[0],e[3])))"` | 2026-11-05T05:57:25Z | cosine Korean↔English translation −0.033; English↔unrelated 0.004; Korean↔Korean (different topic) 0.271 | Installed uv-tool environment, `sentence-transformers` 6.2.0 |
| Model load cannot fit the synchronous budget | `~/.local/share/uv/tools/entirecontext/bin/python -c "import time; t=time.time(); from sentence_transformers import SentenceTransformer; m=SentenceTransformer('all-MiniLM-L6-v2'); t1=time.time(); m.encode('test prompt'); print(t1-t, time.time()-t1)"` | 2026-11-05T05:52:17Z | cold load 24.66 s; one encode 0.199 s (timestamp from the torch log line of that run) | Installed uv-tool environment |
| Synchronous injection budget is 250 ms, and ranking alone uses most of it at scale | `rg -n inject_timeout_ms src/entirecontext/core/config.py && sed -n 8,12p docs/perf/v0-7-0-pdi-baseline.md` | 2026-11-05T05:56:42Z | default 250 ms; ranking p95 61.8 ms at 1000 decisions | `core/config.py:147`; `docs/perf/v0-7-0-pdi-baseline.md` |
| A candidate with zero relevance is dropped, so a semantic score must be able to add candidates | `rg -n "relevance_base <= 0" src/entirecontext/core/decisions.py` | 2026-11-05T05:56:51Z | line 1644 | `core/decisions.py` |
| The development environment does not have `sentence-transformers` | `.venv/bin/python -c "import sentence_transformers"` | 2026-11-05T05:51:18Z | `ModuleNotFoundError` | Worktree virtual environment |

## Trade-offs

| Option | Metric it improves | Metric it degrades | Measured cost |
|---|---|---|---|
| Selected: two-pass (worker writes per-session scores; next synchronous injection reads them) | Semantic candidates reach the default-on injection path with no model cost in the hook | Freshness: scores describe the previous prompt of the session | One model load per worker start (24.66 s cold) plus 0.199 s per prompt, off the hook path; one small file read in the hook |
| Rejected: worker-only signal written to the fallback Markdown file | Simplicity; zero change to the synchronous path | Reach: the default-on injection never sees the signal | 0 consumers of the fallback file by default (`surface_on_user_prompt` default false, `core/config.py:86`) |
| Rejected: embed the prompt inside the synchronous hook | Freshness: scores match the current prompt | Hook latency | 24.66 s cold load against a 250 ms budget (about 98 times over) |
| Selected: benchmark over past turn prompts labeled by touched files | Sample size; labels do not come from the prompt ranker's own output | Fidelity: measures prompt-only recall, not full production ranking; a prompt can name its labeled files | 618 items (388 Hangul) available before the time and mention filters |
| Rejected: replay stored ranking snapshots | Fidelity to production inputs | Separability: prompt and diff are concatenated; labels come from file overlap, which the file signal already uses | 1744 snapshots, prompt text not separable from diff |
| Selected: restrict each benchmark item to decisions created before its prompt | Validity: no hit on a decision that did not exist yet | Sample size: early prompts have few or no eligible decisions | An item with 0 eligible relevant decisions is dropped; the dropped count is reported |
| Rejected: switch the default model to a multilingual model now | Korean recall (unmeasured) | Stability: all 304 stored embeddings must be rebuilt; result unmeasured | 304 decisions to re-embed; benchmark `--model` measures it first |

## Architecture

### Data flow

```
UserPromptSubmit (sync, 250 ms budget for ranking)
  ranking thread: read .entirecontext/state/semantic-scores-<session>.json if fresh ──► rank_related_decisions(semantic_scores=…)
  after injection output is decided (also after a ranking timeout):
    if every launch condition holds (below):
        write pending prompt .entirecontext/state/semantic-prompt-<session>.txt (0600)
        launch_worker_exclusive(pid_name="worker-semantic")

worker-semantic (background, one per project)
  load model once
  loop:
    claim the pending prompt of each session (os.replace to a worker-owned .processing name)
    → embed → cosine vs decision embeddings of the same model
    → write semantic-scores-<session>.json → delete the claimed file only
    exit protocol: under file_lock(worker-semantic.lock), re-list pending prompts;
                   if any remain, release and continue the loop;
                   else delete worker-semantic.pid, release, exit
```

### Launch conditions

The hook writes the pending prompt and launches the worker only when all of these hold. Otherwise it does neither.

1. `session_id` and a Git workspace root are present.
2. `[capture] auto_capture` is true.
3. The decisions experiment block is not active (`is_experiment_off` is false).
4. `[decisions.injection] inject_on_user_prompt` is true.
5. `[decisions.semantic] enabled` is true.
6. The session metadata does not set `capture_disabled`.
7. `should_skip_turn(prompt, config)` is false.

### Exit race

`launch_worker_exclusive` takes the same `worker-semantic.lock` and skips the launch while the PID file names a live worker. The hook writes the pending file before it calls the launcher. So either the running worker still holds its PID file and will see the file in its exit check, or the worker has already deleted its PID file under the lock and the hook starts a new worker. No pending prompt is left without a worker.

### Units

- **Benchmark (R1).** `scripts/experiments/semantic_ranking_benchmark.py`. Opens the database with `mode=ro`.
  - Items are turns with touched files. The relevant set of an item is the decisions linked to those files through `decision_files` and created at or before the turn timestamp.
  - Both rankers see only decisions created at or before the turn timestamp (`until=` on `rank_related_decisions`, and the same filter on semantic scores).
  - Ranker input is the prompt after the same redaction stages as the hook, with no file paths and no commits.
  - A prompt can still name a labeled file, and full text can match it. The report therefore gives a "no file mention" subset: items whose prompt contains no basename of any labeled file. That subset is the headline number.
  - The embedder is injectable so tests run without `sentence-transformers`.
- **Scores store (R3, R4).** A small module with `write_pending_prompt`, `take_pending_prompts`, `write_scores`, and `read_fresh_scores`. Files older than `max_age_seconds` or with a different model name are ignored.
- **Worker (R3).** CLI entry `ec decision semantic-worker` (hidden from help) launched only through `launch_worker_exclusive`.
- **Ranker signal (R4).** `rank_related_decisions(..., semantic_scores: dict[str, float] | None = None)`. A score at or above `min_similarity` adds the decision as a candidate and adds `weight * similarity` to its relevance base. The breakdown gains a `semantic` entry. `None` keeps current behavior exactly.

### Prompt file privacy

The pending prompt follows the existing prompt-surfacing tmp-file contract (`hooks/turn_capture.py:63-132`):

- The text passes `redact_content`, then `filter_secrets`, then `redact_for_query`, before any write.
- The file is created under a unique temporary name in `.entirecontext/state/` with `O_CREAT | O_EXCL` and mode 0600, then moved over the per-session path with `os.replace`. A newer prompt replaces an older pending one.
- The worker claims a pending file by renaming it to a worker-owned name before it reads it, and deletes only that claimed file. A prompt written after the claim lands in a new pending file and is processed in the next loop or by the exit check.
- The worker deletes the claimed file after it writes the scores, and also when processing fails. The scores file holds decision IDs, similarities, model name, and a timestamp only, never prompt text.

### Interface

```toml
[decisions.semantic]
enabled = false          # opt-in
weight = 3.0             # relevance points at similarity 1.0
min_similarity = 0.3     # below this, no candidate and no score
top_n = 20               # decisions kept per scores file
max_age_seconds = 900    # older scores are ignored
model = "all-MiniLM-L6-v2"  # must match stored embeddings
```

## Testing

- `test_benchmark_reports_semantic_gain_on_fixture` (E2E): synthetic database with a Korean prompt whose relevant decision shares no full-text token; fake embedder. Expected: baseline hit@1 = 0, semantic hit@1 = 1, JSON artifact written. Negative control in the same fixture: an English item that full text already finds reports equal hit@1 for both rankers.
- `test_benchmark_excludes_decisions_created_after_prompt`: a decision created after the turn is neither a label nor a candidate.
- `test_benchmark_reports_no_file_mention_subset`: an item whose prompt names its labeled file is excluded from that subset.
- `test_benchmark_opens_database_read_only`: a write attempt through the benchmark connection fails.
- `test_default_config_never_launches_semantic_worker`: default config, two prompts; no PID file, no state file, ranking equal to the pre-change ranking. Negative control: the same flow with `enabled = true` launches once.
- `test_launch_conditions_gate_semantic_worker` (parametrized over launch conditions 2-7): each failing condition writes no file and launches nothing.
- `test_two_pass_semantic_candidate_surfaces_on_next_prompt` (E2E through the `UserPromptSubmit` handler): enabled, fake embedder; prompt 1 produces a scores file; prompt 2 injection output names a decision found only by the semantic signal, with a `semantic` breakdown entry.
- `test_semantic_fail_closed` (parametrized): missing package, no vectors, dimension mismatch, corrupt scores file, stale scores file, model mismatch. Each yields baseline ranking and no exception. Negative control: the valid-scores case differs from baseline.
- `test_concurrent_prompts_launch_one_semantic_worker`.
- `test_prompt_arriving_at_worker_exit_is_processed`: a pending prompt written between the worker's last scan and its exit check is processed by that worker or by a newly launched one.
- `test_prompt_replaced_during_processing_is_not_deleted`: a new pending prompt written while the worker processes a claimed one survives and is processed.
- `test_pending_prompt_file_is_redacted_and_private`: a secret-shaped token does not appear in the file; mode is 0600; a pre-existing symlink at the temporary name is not followed.
- `test_user_prompt_hook_surfaces_semantic_decision_within_budget` (performance): 1000 decisions and a 20-entry scores file; 20 runs of the real `UserPromptSubmit` handler with the default 250 ms timeout. Every run's output names the semantic-only decision. A run that exceeds the budget prints nothing, so it fails.

## Risks

- **No Korean benefit with the current model.** Measured cross-lingual cosine is −0.033. Korean prompts against the 217 English-only decisions will likely gain nothing. Mitigation: R6 reports the Hangul subset separately; S2 measures alternatives offline. Residual: the opt-in signal may not help Korean prompts at all.
- **One-prompt lag.** Scores describe the previous prompt. Topic shifts surface stale candidates for one prompt. Mitigation: `max_age_seconds`, `min_similarity`, and the signal is additive only.
- **Worker cost.** 24.66 s CPU per cold start on this workstation. Mitigation: one exclusive worker drains all pending prompts per load.
- **Privacy.** A prompt file on disk. Mitigation: the three redaction stages, `O_EXCL` creation with mode 0600, and deletion after processing (decision `dedaf5ed`).
- **Retrospective benchmark.** The ranker reads current decision text and file links. A decision edited or relinked after a prompt can change that prompt's result. The time filter removes decisions created later, but it does not restore older decision states. Mitigation: the report states this limit. Residual: past-state effects are not measured.
- **Benchmark label proxy.** Touched files approximate relevance, and a prompt can name its own files. Mitigation: the "no file mention" subset is the headline number; the report states the proxy and all item counts.

## Success Criteria

1. The benchmark reports a semantic gain on a fixture built to have one, and no gain on its control.
   - **Measured by**: `bash -c "UV_NO_BUILD_ISOLATION=1 uv run pytest -q tests/test_semantic_ranking_benchmark.py"`. Negative control: the fixture's English item, where full text already finds the decision, must report equal hit@1 for both rankers; a benchmark that always reports 1 or always 0 fails one of the two assertions.
2. Default configuration changes nothing.
   - **Measured by**: `uv run pytest -q -k test_default_config_never_launches_semantic_worker`. Negative control: the same test with `enabled = true` must observe a launch, so a test that never triggers anything cannot pass both.
3. With the signal enabled, a semantic-only decision surfaces on the next prompt.
   - **Measured by**: `uv run pytest -q -k test_two_pass_semantic_candidate_surfaces_on_next_prompt`. Negative control: with `semantic_scores=None` the same decision is absent.
4. Every listed failure falls back to baseline ranking without an exception.
   - **Measured by**: `uv run pytest -q -k test_semantic_fail_closed`. Negative control: the valid-scores case in the same parametrization must differ from baseline.
5. The synchronous injection budget holds with the signal active.
   - **Measured by**: `uv run pytest -q -k test_user_prompt_hook_surfaces_semantic_decision_within_budget`. Negative control: removing the scores-file read or the ranker signal makes the semantic-only decision disappear from the output, so the test fails; a timeout also empties the output.
6. The benchmark has run on the project database and its numbers are committed.
   - **Measured by**: the report under `docs/perf/` lists item counts (total, dropped for no eligible label, Hangul, no file mention), hit@5 and MRR for both rankers in each subset, and the exact command. Rubric: numbers match a fresh rerun of that command within the same database state.
7. The full repository gate passes.
   - **Measured by**: `UV_NO_BUILD_ISOLATION=1 uv run pytest -q --basetemp=/tmp/ecsc`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/entirecontext/`.

## Open Decisions

- Default `weight` and `min_similarity` values. Owner: planning, from fixture behavior; the R6 report may motivate a later change but not a default flip.
- Deferred to implementation: exact file-name scheme for per-session state, and cleanup of orphaned scores files at SessionEnd.
- Stop condition: R6 numbers do not reopen this spec. Enabling the signal by default or changing the model needs a new decision.
