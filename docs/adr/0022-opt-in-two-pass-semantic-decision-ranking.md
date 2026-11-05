# 0022. Opt-in Two-Pass Semantic Decision Ranking

**Status:** accepted
**Date:** 2026-11-05
**EC Decision:** `d3430f87`

## Context

Every decision gets an embedding (`[decisions] auto_embed = true`), but no ranking path read them.
Prompt-time decision injection runs inside the `UserPromptSubmit` hook with a 250 ms ranking budget.
Loading the `all-MiniLM-L6-v2` model took 24.66 s cold and 5.04 s warm on the development workstation.
So the hook cannot embed the prompt.
EC decision `d3430f87` chose a two-pass design: compute semantic scores in the background and use them on a later prompt.

The [spec](../specs/2026-11-05-signal-c-prompt-ranking-design.md) required a measurement before any default change.
The [benchmark report](../perf/2026-11-05-signal-c-benchmark.md) measured hit@5 from 0.166 to 0.406 on prompts that do not name their files (175 items).

## Decision

Add an opt-in semantic signal, off by default:

- New configuration `[decisions.semantic]`: `enabled = false`, `weight = 3.0`, `min_similarity = 0.3`, `top_n = 20`, `max_age_seconds = 900`, `model = "all-MiniLM-L6-v2"`.
- When enabled, the hook writes the redacted prompt to `.entirecontext/state/semantic-prompt-<session>.txt` (mode 0600) and launches one exclusive worker (`worker-semantic`).
- The worker writes `.entirecontext/state/semantic-scores-<session>.json`: decision IDs, similarities, model name, and a timestamp. It never stores prompt text.
- The next prompt's injection reads fresh scores for the same model and passes them to `rank_related_decisions`, which adds candidates and a `semantic` score-breakdown entry.
- Every failure falls back to the existing ranking.

Rejected alternatives:

- Embed the prompt inside the hook: the model load exceeds the 250 ms budget by more than 20 times.
- Write results only to the fallback Markdown file: the default-on injection path would never use them.
- Switch to a multilingual model now: all stored embeddings would need rebuilding, with no measurement yet.
- Enable by default now: one database and one model do not justify a default change.

## Consequences

- Users can opt in without a schema change. The two state files are a new on-disk contract.
- Scores lag by one prompt. A topic change can surface candidates from the previous prompt once.
- An opt-in user pays one background model load per worker start.
- A later ADR can enable the signal by default or change the model, citing new benchmark runs.
