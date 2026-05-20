# PDI Performance Baseline — v0.7.0

Measured with 20 repetitions per corpus size.
Input: 10 file paths + simulated diff (2 hunks) + 10 commit SHAs.

## Results

| Corpus size | p50 (ms) | p95 (ms) | Gate (< 250ms) |
|---|---|---|---|
| 100 | 4.5 | 5.5 | PASS ✓ |
| 500 | 21.1 | 25.3 | PASS ✓ |
| 1,000 | 43.8 | 61.8 | PASS ✓ |

## Decision

**`inject_on_user_prompt` default: `true`**

p95 < 250ms at 1000 decisions → sync PDI path is fast enough for default-ON.

## Raw Timings (ms)

### 100 decisions
4.2, 4.2, 4.3, 4.3, 4.3, 4.4, 4.4, 4.4, 4.4, 4.5, 4.5, 4.6, 4.6, 4.8, 5.0, 5.1, 5.1, 5.3, 5.4, 5.5

### 500 decisions
20.2, 20.3, 20.3, 20.4, 20.5, 20.5, 20.5, 20.8, 20.8, 21.1, 21.1, 21.2, 21.3, 21.4, 21.5, 21.7, 21.8, 23.1, 23.2, 25.4

### 1,000 decisions
41.1, 41.6, 41.7, 42.0, 42.1, 42.2, 42.9, 42.9, 43.1, 43.7, 43.8, 43.8, 44.1, 44.3, 44.8, 45.0, 47.4, 49.9, 56.3, 62.1
