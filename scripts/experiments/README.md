# Experiment Scripts

## Block Flip Automation

Cron job flips `experiment_block` between ON/OFF when qualifying sessions reach N (default 5).

### Setup

```bash
# Install cron (runs every 30 min, idempotent)
(crontab -l 2>/dev/null; echo "*/30 * * * * cd /Users/teslamint/workspace/entirecontext && /Users/teslamint/.local/bin/uv run python scripts/experiments/flip_block.py >> scripts/experiments/output/flip-cron.log 2>&1") | crontab -
```

### Manual check

```bash
python scripts/experiments/flip_block.py          # check status
python scripts/experiments/flip_block.py --n 3    # override block size
python scripts/experiments/analyze_blocks.py      # analyze results
```

### Cron log

```bash
tail -f scripts/experiments/output/flip-cron.log
```

### Remove cron

```bash
crontab -l | grep -v flip_block | crontab -
```

## Token Savings Analysis

Estimate token overhead of context injection and net per-session savings from the
ON/OFF block experiment. Reads `operation_events` (`context_injection` rows) for
injected-token totals and `turn_content` transcript sizes for session footprint.
Pairs ON/OFF blocks (via `experiment-blocks.jsonl`) into per-pair deltas.

```bash
python scripts/experiments/token_savings.py --summary   # whole-DB baseline (no blocks)
python scripts/experiments/token_savings.py             # per-block A/B analysis
python scripts/experiments/token_savings.py --json       # machine-readable output
```

`--bytes-per-token` defaults to `4.0`. Fewer than 4 ON/OFF pairs and sub-80%
turn-content coverage emit warnings rather than failure.
