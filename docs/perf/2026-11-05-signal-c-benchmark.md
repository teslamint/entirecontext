# Signal C Offline Benchmark (2026-11-05)

This report measures prompt-to-decision retrieval with and without the opt-in semantic signal. It is the measurement that the Signal C spec requires before any default change. See [the spec](../specs/2026-11-05-signal-c-prompt-ranking-design.md) and [ADR 0022](../adr/0022-opt-in-two-pass-semantic-decision-ranking.md).

## Method

- Items: past turns whose `files_touched` list is not empty.
- Labels: decisions linked through `decision_files` to a touched file and created at or before the turn. Touched paths are absolute and can come from linked worktrees, so a link matches when its repository-relative path is a `/`-bounded suffix of the touched path.
- Both rankers see only decisions created at or before the turn. Ranker input is the redacted prompt only, with no file paths and no commits.
- Baseline: `rank_related_decisions` as shipped. Semantic: the same call plus similarity scores from `all-MiniLM-L6-v2`, with the default `weight = 3.0` and `min_similarity = 0.3`.
- Like the worker, the semantic ranker receives only the `top_n` (20) highest similarities.
- Both rankers rank every decision; results created after the prompt are removed before the list is cut to k. Successor-chain resolution in the ranker does not apply `until`, so a later successor can otherwise take a slot.
- Metrics: hit@5 and mean reciprocal rank (MRR).
- "No file mention" excludes items whose prompt contains the basename of a labeled file (a touched file that links to a relevant decision). This subset is the headline number, because full text can match a named file.

## Result

Observed 2026-11-05T08:26:32Z on the project database (read-only) with `sentence-transformers` 6.2.0.

| Subset | Items | Baseline hit@5 | Semantic hit@5 | Baseline MRR | Semantic MRR |
|---|---|---|---|---|---|
| All | 215 | 0.247 | 0.437 | 0.137 | 0.269 |
| Hangul | 144 | 0.111 | 0.403 | 0.068 | 0.285 |
| No file mention | 185 | 0.184 | 0.405 | 0.089 | 0.251 |
| Hangul, no file mention | 134 | 0.067 | 0.381 | 0.035 | 0.265 |

618 turns had touched files. 403 had no eligible label and were dropped. 215 remained.

The semantic signal raised hit@5 in every subset. The largest gain was in the Hangul, no-file-mention subset (0.067 to 0.381). The spec expected little Korean benefit, because the model gives no cross-lingual signal for whole Korean sentences. A likely cause of the observed gain is that Korean prompts in this project often contain English identifiers. This cause is an inference; the benchmark does not test it.

## Limits

- Labels are a proxy. A touched file does not prove that a linked decision was relevant to the prompt.
- Suffix matching can link a common file name such as `pyproject.toml` from another checkout.
- The ranker reads current decision text and links. Decisions edited or relinked after a prompt can change that prompt's result.
- Production ranking also uses the uncommitted diff, recent commits, and file paths. This benchmark measures prompt-only recall.
- The database is live. Decisions updated between runs can reorder tied results, so a rerun can differ in the third decimal place.
- One database, one model, one `k`. The numbers do not by themselves justify a default change.

## Command

Run from the feature checkout. The installed `entirecontext` uv-tool interpreter provides `sentence-transformers`; `PYTHONPATH` selects the checkout source.

```bash
PYTHONPATH=$PWD/src:$PWD ~/.local/share/uv/tools/entirecontext/bin/python \
  scripts/experiments/semantic_ranking_benchmark.py \
  --repo /path/to/project --k 5 --json > /tmp/signal-c-benchmark.json
```
