# T2-rollback — batch-end embedding

- Plan: `docs/superpowers/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md`, row T2
- Source commit: `c925e49df964701794e57816b435c555d0848cc9`

This cell's proof is analytical, per the brief (U1-brief.md line 67) and the plan text (line 204: "Rollback: not applicable — embeddings are derived, regenerable data with no consumer that assumes their absence; no compensation needed."). No command output is fabricated for this cell.

Reasoning:
- Embedding rows (`embeddings` table, `source_type='decision'`) are a derived cache over already-committed `decisions` rows, produced by `generate_embeddings(conn, repo_path, decisions_only=True)`. They are not part of the atomicity boundary that promotes a candidate into a decision — that boundary is entirely `confirm_candidate`'s `BEGIN IMMEDIATE` block (T1's concern), which completes and commits before the batch-end embedding step ever runs.
- Because embeddings are purely additive/derived and idempotent to regenerate (see T2-rerun), there is no "compensating rollback" needed if the embedding step fails or is interrupted: the confirmed decisions remain valid and correct with or without their embeddings present. A missing embedding row is a degraded-search-quality condition, not a data-integrity violation — no other table or invariant depends on an embedding row existing for a given decision.
- This is why `confirm_candidates_batch` wraps the embedding tail in a bare `try/except: pass` (T2-forced-failure) rather than any transactional or compensating-update pattern: there is nothing to compensate.

Verification pointer: T2-forced-failure demonstrates executably that a raised exception in the embedding step is swallowed without affecting the batch's `confirmed`/`failed` outcome; T2-rerun demonstrates that a later call safely fills in any embeddings a prior failed/skipped step left missing.
