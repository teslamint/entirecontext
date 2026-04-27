# Decision Conflict Flagging

_Draft brainstorm. Created 2026-04-27. Milestone: v0.7.1. Confidence: 78%._

## Intent

When a new decision is written (via `create_decision` or `confirm_candidate`), an FTS5 keyword-overlap check scans existing decisions for potential conflicts and surfaces flagged pairs as review queue entries. Human review resolves conflicts — the system never auto-writes `contradicted` outcomes.

The hard constraint: keyword co-occurrence does not equal semantic contradiction. Auto-generating `contradicted` outcomes based on FTS5 overlap would corrupt F2 penalty scoring by injecting false-positive contradictions into the ranking signal. Conflict flagging is a discovery aid, not an automated outcome recorder.

User-visible outcomes:

- New decisions that share significant keyword overlap with existing decisions are flagged in the `ec review` queue automatically.
- Operators can inspect flagged pairs and manually resolve them without the system having decided for them.
- The `ec review` queue remains the single interface for human-in-the-loop conflict resolution.

## Scope

### In

- Trigger: after `create_decision` / `confirm_candidate` commit, run `fts_decisions MATCH <extracted keywords>` against existing decisions.
- Flagged pairs stored as conflict candidates accessible via `ec review` queue.
- Config section `[decisions.conflict_flagging]`: `enabled` (default `false`), `min_overlap_score` (default 0.3), `max_candidates_per_decision` (default 10).
- Conflict candidates include: both decision IDs, overlap score, overlapping terms, and `source: conflict` marker.
- `ec review` displays conflict candidates distinctly from extraction candidates (separate label or filter).
- Unit tests for FTS5 overlap query, score threshold filtering, and duplicate-pair deduplication.

### Out

- Semantic or embedding-based conflict detection (FTS5 keyword overlap only for v0.7.1).
- Auto-promotion of flagged pairs to `contradicted` outcome.
- Auto-write of `decision_outcomes` records for conflict candidates (would corrupt F2 penalty scoring).
- Resolution UX beyond existing `ec review` queue (no new commands).
- Detection across cross-repo decisions.

## Storage Decision

Two options for persisting flagged conflict pairs:

| Option | Approach | Pros | Cons |
|---|---|---|---|
| A | Reuse `decision_candidates` table with new `source = 'conflict'` value | No schema change; reuses existing review queue path | `decision_candidates` semantics are for extraction candidates, not conflict pairs; storing two decision IDs as a "candidate" is semantically awkward |
| B | New `decision_conflicts` table: `(id, decision_a_id, decision_b_id, overlap_score, overlapping_terms, status, created_at)` | Clean separation; conflict-specific fields fit naturally; no semantic overloading | Requires schema v15 migration; adds table surface |

**Recommended: Option B** — a dedicated `decision_conflicts` table is semantically cleaner and avoids polluting `decision_candidates` with a fundamentally different entity type (a pair vs. a single candidate). The schema bump can be batched with other v0.7.1 changes.

This storage decision must be confirmed before implementation starts. It directly determines whether a schema migration is required.

## FTS5 Overlap Scoring Contract

```
-- Extract keywords from new decision (title + rationale, stop words removed)
keywords = extract_keywords(new_decision.title + " " + new_decision.rationale)

-- Query FTS5 for matching decisions
candidates = SELECT rowid, rank FROM fts_decisions
             WHERE fts_decisions MATCH <keywords>
             AND rowid != <new_decision_id>
             ORDER BY rank DESC
             LIMIT <max_candidates_per_decision>

-- Compute overlap score (rank-normalized)
overlap_score = normalize(rank)  -- must be defined; FTS5 rank is negative BM25

-- Filter by min_overlap_score, deduplicate pairs (A,B) == (B,A)
-- Insert non-duplicate pairs into decision_conflicts
```

The overlap score normalization formula must be defined explicitly before implementation — FTS5 BM25 rank is negative and unbounded.

## Proposed Action Items

### v0.7.1 Core

[ ] Confirm storage decision (Option A vs B) before any code changes.

[ ] If Option B: add `decision_conflicts` table to schema with `(id, decision_a_id, decision_b_id, overlap_score, overlapping_terms, status, created_at)`. Add schema v15 migration.

[ ] Add `[decisions.conflict_flagging]` config section: `enabled = false`, `min_overlap_score = 0.3`, `max_candidates_per_decision = 10`.

[ ] Implement keyword extraction helper (stop-word removal, tokenization) for FTS5 MATCH query assembly. Do not use raw user text as FTS5 query — sanitize input.

[ ] Define BM25 rank normalization formula. Document the chosen formula in code and in this brainstorm.

[ ] Wire trigger in `core/decisions.py`: after `create_decision` and `confirm_candidate` commit, if `conflict_flagging.enabled`, run overlap check and insert conflict candidates.

[ ] Implement `ec review` display path for conflict candidates: list flagged pairs with overlap score and overlapping terms.

[ ] Unit tests: FTS5 overlap query with known keyword sets, score threshold filtering, pair deduplication, and disabled-config fast path.

[ ] Update CHANGELOG, ROADMAP, and `ec review` documentation.

## Risks

- False positive rate: FTS5 keyword overlap flags legitimate but non-conflicting decisions that share domain vocabulary. A high false positive rate will cause operators to ignore the queue entirely.
- Score normalization ambiguity: FTS5 BM25 rank is negative and repo-size-dependent. Without a defined normalization, `min_overlap_score` thresholds are meaningless across repos of different sizes.
- F2 corruption risk: if the storage choice or a future config change accidentally causes conflict candidates to be treated as `contradicted` outcomes, F2 penalty scoring degrades immediately. The hard constraint (no auto-write of outcomes) must be enforced in tests, not just documentation.
- Queue pollution: if `max_candidates_per_decision` is too high (e.g., 50), every new decision floods the review queue with low-quality pairs.
- Schema bump: Option B requires a migration; if batched with other v0.7.1 changes, the migration complexity increases.

## Review Questions

- Which storage option is preferred — reuse `decision_candidates` with `source = 'conflict'` (Option A) or dedicated `decision_conflicts` table (Option B)?
- What is the correct BM25 rank normalization formula for computing `overlap_score`? The chosen formula determines what `min_overlap_score = 0.3` actually means.
- Should conflict flagging run synchronously inside `create_decision` / `confirm_candidate` or as a detached `launch_worker` subprocess? The overlap check adds latency to every decision write.
- How should the `ec review` queue distinguish conflict candidates from extraction candidates — by a separate `--type conflict` filter flag, or by a separate section in the default output?
- Should flagged pairs that were already reviewed and dismissed be re-surfaced if new keyword overlap evidence appears, or suppressed permanently once a `status = dismissed` is recorded?
