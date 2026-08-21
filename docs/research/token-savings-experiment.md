# Token Savings Experiment

How much does EntireContext's proactive context injection reduce total LLM
token consumption? This protocol turns the existing injection ON/OFF block
experiment (`scripts/experiments/flip_block.py`) into a token-denominated
measurement.

Current state, measured baseline, and next steps for whoever picks this up:
[token-savings-experiment-handoff.md](token-savings-experiment-handoff.md).

## Hypothesis

Injecting ranked decisions/lessons at SessionStart, UserPromptSubmit (PDI),
and PostToolUse lets the agent skip re-discovery work (re-reading files,
re-searching, re-deriving prior decisions), so sessions finish with a smaller
cumulative transcript than sessions without injection — by more than the
injected payloads themselves cost.

## Metrics

### Injection overhead (cost side)

Every injected payload is now recorded at injection time as an
`operation_events` row with `operation_name = 'context_injection'` and
`phase` = channel (`session_start_decisions`, `session_start_lessons`,
`user_prompt`, `post_tool_use`). `metadata` carries:

- `injected_tokens` — cl100k_base estimate via `core.tokens.estimate_tokens`
  (byte-heuristic fallback when tiktoken's BPE file is unavailable, e.g.
  offline)
- `injected_chars`, `item_count`

Written by `core.telemetry.record_injection_event`; no schema migration.

### Session token footprint (savings side)

Each captured turn stores the full Claude Code transcript JSONL at that
point (`turn_content.content_size` bytes). Because every turn re-sends the
whole conversation to the model, the sum of per-turn transcript sizes
approximates the cumulative input payload the LLM processed over the
session. Tokens ≈ bytes / 4 (configurable via `--bytes-per-token`).

- `cumulative_transcript_tokens` = Σ content_size / bytes_per_token
- `final_context_tokens` = max content_size / bytes_per_token
- `avg_tokens_per_turn` = cumulative / turns

### Estimand

Per paired ON/OFF block (same pairing and treatment-independent gate —
`total_turns >= 5` — as `analyze_blocks.py`):

```
net_saved_tokens_per_session = OFF avg session tokens − ON avg session tokens
savings_roi                  = net_saved / ON avg injected tokens
```

The injected text lands inside ON-session transcripts, so the net delta
already charges the overhead; `savings_roi` shows leverage per injected
token.

## Running it

```bash
# Whole-DB baseline (no blocks needed) — footprint + injection overhead
python scripts/experiments/token_savings.py --summary

# A/B analysis over the flip_block.py block log
python scripts/experiments/token_savings.py

# Machine-readable
python scripts/experiments/token_savings.py --json
```

Prerequisites for the A/B mode: the block-flip cron from
`scripts/experiments/README.md` running long enough to accumulate ≥4 block
pairs (the script warns below that).

## Caveats

- **Proxy, not a bill.** `content_size` includes JSONL structural overhead
  and tool outputs; prompt caching means billed tokens are lower than
  context-window tokens. Treat results as *context volume processed*, which
  tracks cache-read volume, not invoice dollars.
- **Consolidation erases evidence.** `core/consolidation.py` deletes
  `turn_content` rows; the analyzer reports `content_coverage` per block and
  warns below 80% — those blocks are underestimates.
- **Behavioral confound.** If OFF blocks show elevated manual retrieval
  (see `analyze_blocks.py` compensation check), the comparison shifts from
  "injection vs nothing" to "proactive vs on-demand retrieval".
- **Two estimators still exist.** The PDI lesson leftover budget in
  `hooks/handler.py::_estimate_tokens` still uses `len(text)//4`, while
  budgets and telemetry use the cl100k estimator in
  `core/decision_prompt_surfacing` / `core.tokens`. Unifying the handler's
  budget math is deliberately out of scope here (it would change injection
  behavior mid-experiment).
- **<4 pairs = directional only.** Same significance rule as the base block
  experiment.
- **Lessons channel was ungated.** The `session_start_lessons` channel
  ignored `experiment_block` until PR #232. OFF-block data collected
  before the fix is contaminated. Discard it; re-initialize the block log.
