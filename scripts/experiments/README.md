# Experiment Scripts

## Block Flip Automation

The cron job flips `experiment_block` between ON and OFF when qualifying sessions reach N (default 5).

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

This script estimates token overhead from context injection and net per-session
savings in the ON/OFF block experiment. It reads `operation_events` rows marked
`context_injection` to total injected tokens. It reads transcript sizes in
`turn_content` to measure the session footprint. It pairs ON/OFF blocks from
`experiment-blocks.jsonl`. It calculates the delta for each pair. See the
protocol and caveats in `docs/research/token-savings-experiment.md`.

```bash
python scripts/experiments/token_savings.py --summary   # whole-DB baseline (no blocks)
python scripts/experiments/token_savings.py             # per-block A/B analysis
python scripts/experiments/token_savings.py --json       # machine-readable output
```

The `--bytes-per-token` value defaults to `4.0`. The script warns instead of
failing when it finds fewer than 4 ON/OFF pairs. It also warns instead of
failing when turn-content coverage is sub-80%.
