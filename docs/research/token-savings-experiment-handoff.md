# Token Savings Experiment — Handoff

Everything an agent (or human) needs to pick up the experiment from here.
Protocol and metric definitions live in
[token-savings-experiment.md](token-savings-experiment.md); this document
covers current state, what has already been measured, and the exact next
steps.

## State as of 2026-08-20

| Piece | Where | Status |
|---|---|---|
| Analyzer `scripts/experiments/token_savings.py` | `main` (merged via #237) | shipped |
| Injection telemetry (4 channels), `core/tokens.py`, tests, protocol doc | PR #232, branch `claude/llm-token-savings-experiment-w112qo` | CI green, draft, awaiting merge |
| Block-flip harness (`flip_block.py`, `analyze_blocks.py`) | `main` (pre-existing) | shipped |
| ON/OFF block log | maintainer's machine, `scripts/experiments/output/experiment-blocks.jsonl` | **not yet initialized for this experiment** |
| Dogfooding data | maintainer's machine, `.entirecontext/db/local.db` | telemetry already accumulating (branch is running locally) |

The dogfooding DB lives only on the maintainer's machine — remote/cloud
agents cannot read it. Any step below marked **[local]** must run there
(or its output must be pasted back).

## Baseline already measured (2026-08-20, `--summary` [local])

78 qualifying sessions (`total_turns >= 5`), content coverage 0.895:

- `avg_session_tokens` ≈ **9.56M** (cumulative transcript volume per session)
- `avg_tokens_per_turn` ≈ 532K; `avg_final_context_tokens` ≈ 388K
- Injection overhead: **111.5 tokens/session** avg (8,694 total) — ~0.001%
  of session volume
- Distribution is heavily skewed: top session (178 turns) ≈ 382M cumulative
  tokens, ~40× the mean

Interpretation locked in so far: the cost side is negligible — injection
breaks even if it saves ~112 tokens/session, i.e. avoids any fraction of a
single re-discovery tool call (whose cost also compounds into every later
turn's transcript). The open question is purely whether injection actually
reduces turns/re-discovery: that is what the ON/OFF blocks answer.

Note `avg_final_context_tokens` (388K) exceeds the real context window —
confirmation that transcript bytes are a *volume proxy* (tool outputs +
JSONL overhead, no compaction), valid for ON-vs-OFF comparison, not as an
absolute bill.

## Next steps, in order

1. **Merge PR #232** (or keep dogfooding on its branch). Telemetry only
   accumulates where the instrumented hooks run.
2. **Initialize the block experiment** [local]:
   ```bash
   uv run python scripts/experiments/flip_block.py --init
   ```
   then install the flip cron per `scripts/experiments/README.md`. Verify
   after the first flip that `.entirecontext/config.toml` gains
   `[decisions.injection] experiment_block = "off"` and that OFF sessions
   stop receiving `## Related Decisions` blocks.
3. **Accumulate ≥ 4 ON/OFF pairs** (8 blocks × 5 qualifying sessions ≈ 40
   meaningful sessions; at current dogfooding pace expect a few weeks).
   Do not change `decisions.injection` settings mid-experiment, and avoid
   unifying the `hooks/handler.py::_estimate_tokens` `//4` budget estimator
   until the experiment ends (it would change injection behavior mid-run).
4. **Analyze** [local]:
   ```bash
   uv run python scripts/experiments/token_savings.py          # token deltas + ROI
   uv run python scripts/experiments/analyze_blocks.py         # turns + compensation check
   ```
   Read `net_saved_tokens_per_session` (positive ⇒ injection saves),
   `savings_roi`, and heed every warning the scripts print — especially the
   compensation check (elevated manual retrieval in OFF blocks changes the
   estimand) and content-coverage warnings.
5. **Record the outcome** as a new dated section in
   `docs/research/token-savings-experiment.md` (numbers + verdict), update
   `docs/research/index.md`, and if the verdict is clear, capture it as an
   `ec` decision so it ranks in future sessions.

## Decision criteria

- `net_saved_tokens_per_session` consistently positive across pairs, ROI ≫ 1
  → keep injection default-on; consider raising `top_k`/`max_tokens`.
- Deltas straddle zero with < 4 pairs → extend the experiment; do not call it.
- Consistently negative → injection isn't reducing re-discovery; investigate
  ranking quality (`ranking_snapshots`) before turning anything off.

## Known follow-ups (deliberately not done yet)

- **Median/trimmed aggregates** in `token_savings.py`: means are dominated by
  outlier sessions (40× skew observed). Add median per-block aggregation if
  pair deltas look noisy.
- **Estimator unification**: retire the `//4` heuristic in
  `hooks/handler.py::_estimate_tokens` in favor of `core.tokens` — *after*
  the experiment concludes.
- **Dashboard surfacing**: injected-token totals could join
  `core/dashboard.py` stats; kept out of PR #232 for scope.

## Code map

- `core/tokens.py` — canonical `estimate_tokens` (tiktoken cl100k, byte
  fallback; offline-safe).
- `core/telemetry.py::record_injection_event` — writes `operation_events`
  rows (`operation_name='context_injection'`, `phase`=channel,
  `metadata.injected_tokens/injected_chars/item_count`).
- Instrumented channels: `hooks/decision_hooks.py::on_session_start_decisions`
  and `::on_post_tool_use_decisions`; `hooks/handler.py::_surface_lessons_on_start`
  and `::_handle_user_prompt` (PDI). All wrapped in try/except — telemetry
  can never break injection.
- `scripts/experiments/token_savings.py` — `session_token_stats`,
  `session_injection_stats`, `analyze_token_blocks`, `summarize_all`.
- Tests: `tests/test_token_savings_experiment.py` (seeding helpers show the
  exact row shapes the analyzer expects).

## Gotchas

- `sessions_in_block` gates on `total_turns >= 5` and is deliberately
  treatment-independent — do not "improve" it with checkpoint/quality
  filters, that reintroduces selection bias.
- Consolidation (`core/consolidation.py`) deletes `turn_content` rows;
  long-delayed analysis under-counts. Run the analysis before aggressive
  consolidation, or trust the coverage warnings.
- tiktoken downloads its BPE file on first use; offline/proxied environments
  silently fall back to the byte heuristic (~utf8/3). Fine for consistency,
  but don't mix estimator environments when comparing absolute numbers.
- One pre-existing env-dependent test failure:
  `test_pdi_optimizer.py::test_encoding_initialized_at_module_level` fails
  wherever tiktoken cannot fetch its BPE file (reproduces on `main`); green
  in CI.
