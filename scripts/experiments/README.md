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
