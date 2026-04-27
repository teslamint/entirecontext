# v0.6.0 Roadmap Plan

_Draft for external plan review. Created 2026-04-27._

## Intent

v0.6.0 should strengthen the decision outcome lifecycle after v0.5.0 closed correctness debt. The release should keep a narrow product shape: outcome semantics, outcome recording, and ranking behavior.

User-visible outcomes:

- Agents can distinguish guidance that was accepted, ignored, contradicted, refined, or replaced.
- Accepted decisions can rank higher without contaminating extraction confidence.
- Replacement/refinement outcomes do not get confused with staleness or supersession state.

Prioritization rule: ship only changes that improve outcome recording or reuse without changing extraction confidence. Defer data-hygiene CLI work unless it blocks the outcome lifecycle contract.

## Scope

### In

- F5 outcome enum expansion: add `refined` and `replaced`.
- Schema v14 migration for `decision_outcomes.outcome_type`.
- Outcome recording paths updated for the expanded outcome vocabulary.
- Accepted ranking behavior verified and adjusted only if the existing quality-score path is insufficient.
- MCP, CLI, README, CHANGELOG, and tests updated to agree on the expanded outcome vocabulary.
- Tests and documentation for all public behavior changes.

### Out

- Applying accepted boost to extraction confidence.
- Automatic LLM-generated explanations for historical rejected alternatives.
- `ec decision alternatives ...` audit, normalize, and manual set commands.
- Structured rejected-alternative normalization/backfill.
- Broad dashboard, graph, or generic knowledge-management features.
- Reworking decision storage beyond the minimum needed for outcome semantics.

## Outcome Semantics Contract

The v0.6.0 plan must define a truth table before implementation starts:

| Outcome | Meaning | Quality score | Staleness auto-promotion | Supersession / successor chain | Extraction confidence |
|---|---|---|---|---|---|
| `accepted` | Decision was applied or reused successfully | Positive signal; existing behavior must be verified before adding new weight | No direct stale promotion | No chain mutation | No effect |
| `ignored` | Decision was surfaced but not used | Negative or neutral signal according to existing quality behavior | No direct stale promotion | No chain mutation | No effect |
| `contradicted` | Decision was wrong for the observed use | Negative signal; existing auto-promotion behavior remains | May trigger contradicted staleness under existing threshold rules | No chain mutation | Penalty-only behavior remains unchanged |
| `refined` | Decision remains valid but was made more precise by later work | To be defined explicitly; must not silently double-count as accepted unless documented | No direct stale promotion | May reference the newer decision only if an explicit link already exists | No effect |
| `replaced` | Decision was superseded by a newer decision or should no longer be followed directly | To be defined explicitly; must not conflict with contradicted scoring | No direct stale promotion unless also contradicted | Must be reconciled with existing `supersede` / successor-chain behavior | No effect |

Recording-path requirements:

- Manual outcome recording must accept all five outcome values through CLI and MCP.
- Existing `ec_context_apply` accepted recording must remain unchanged unless the user explicitly chooses a different outcome.
- SessionEnd ignored inference must remain limited to `ignored`.
- `ec decision supersede` must explicitly define whether it records `replaced`, updates successor state, or both.
- Candidate confirmation must not infer `refined` or `replaced` without an explicit source event.

## Proposed Action Items

### v0.6.0 Core

[ ] Update `ROADMAP.md` with v0.6.0 theme, scope, non-goals, and v0.7.0 deferral for extraction confidence boost.

[ ] Define the outcome truth table for quality score, staleness auto-promotion, successor chains, display/filter behavior, extraction confidence, and recording paths.

[ ] Add schema v14 migration for `decision_outcomes.outcome_type`: rebuild the constrained table safely, preserve existing rows, recreate indexes, update fresh schema, and test v13 to v14 migration rollback behavior.

[ ] Update decision outcome validation across core, CLI, MCP, docs, and tests to support `accepted`, `ignored`, `contradicted`, `refined`, and `replaced`.

[ ] Update recording paths so `refined` and `replaced` can be recorded intentionally without changing existing `ec_context_apply` accepted behavior or SessionEnd ignored inference.

[ ] Verify whether existing quality-score behavior already provides accepted ranking boost. If a delta is still needed, define the exact weight, cap, config key, score breakdown label, and regression tests proving accepted outcomes are counted once.

[ ] Add tests proving extraction confidence is unchanged by accepted ranking behavior and by the new `refined` / `replaced` outcomes.

[ ] Update README, CHANGELOG, ROADMAP, and MCP tool documentation with the schema v14 breaking note and expanded outcome vocabulary.

### v0.6.1 Candidate

[ ] Add rejected alternative normalization helpers in `src/entirecontext/core/decisions.py` that accept legacy strings and structured objects.

[ ] Add `ec decision alternatives audit` to list reasonless, malformed, mixed, or legacy alternatives without mutating data.

[ ] Add `ec decision alternatives normalize` to convert legacy strings to structured objects using `Unknown from recorded context` for missing reasons.

[ ] Add `ec decision alternatives set` or equivalent manual update command for explicit structured replacements.

[ ] Tighten decision extraction prompts to request rejected alternative reasons only when the source text contains enough evidence, and ensure parser/candidate confirmation paths share the same normalizer.

[ ] Add tests for legacy string compatibility, malformed JSON detection, mixed arrays, empty alternatives, empty reasons, audit categories, normalization idempotency, and manual set behavior.

## Risks

- Scope creep: outcome vocabulary, ranking feedback, and rejected-alternative quality are related but still three implementation tracks.
- Self-reinforcing feedback: accepted boost must stay out of extraction confidence in v0.6.0.
- Data integrity: historical rejected alternatives must not get invented rationale.
- Contract drift: MCP, CLI, README, and changelog must agree on the expanded outcome vocabulary and alternatives shape.
- Double-counting: accepted outcomes already contribute to existing quality scoring, so v0.6.0 must verify current behavior before adding any new ranking weight.
- Semantic drift: `replaced` must not become a second, incompatible supersession mechanism.

## Review Questions

- Should `refined` affect quality score, or should it remain a display/audit outcome only?
- Should `replaced` automatically accompany `ec decision supersede`, or should it remain a separate manual outcome?
- Is the existing accepted quality score sufficient, or does v0.6.0 need a separate capped ranking boost?
- Which MCP tools need explicit signature or documentation changes for the expanded outcome vocabulary?
