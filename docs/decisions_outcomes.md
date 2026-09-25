# Decision Outcome Semantics

This document describes how the five decision outcome types work now.
It records current behavior, not a proposed change.
Make a separate decision record for any change in meaning.

## Truth Table

| Outcome | `quality_score` delta | Ranking boost | Shows as active | Auto-triggered by | Who sets it |
|---|---|---|---|---|---|
| `accepted` | `+1.0` | Binary `accepted_outcome_boost` after relevance match | Yes | — | User / subsequent decision work |
| `ignored` | `−0.5` | — | Yes | — | User |
| `contradicted` | `−2.0` | — | Yes (auto-promote candidate possible) | `_maybe_auto_promote_contradicted` | User |
| `refined` | 0 | — | Yes | — | User |
| `replaced` | 0 | — | Effectively no (superseded) | `supersede_decision` auto-link | `supersede_decision` caller |

### Notes

- **`replaced` quality_score = 0**: This is intentional. `decisions.py` contains an explicit comment: *"paired with staleness superseded factor, no double-penalty"*.
  The staleness factor already down-ranks superseded decisions. A second score hit
  would unfairly penalise them twice.

- **`accepted` boost status**: accepted outcomes add a configurable binary boost
  only after another relevance signal already matched the decision. The boost is
  not a standalone retrieval seed.

- **`contradicted` auto-promote**: `_maybe_auto_promote_contradicted` may surface a
  competing candidate when someone records a `contradicted` outcome for a decision. See `core/decisions.py` for
  the promotion logic.

## When to Use Each Outcome

| Outcome | Use when |
|---|---|
| `accepted` | Subsequent work confirmed or followed this decision |
| `ignored` | The decision was surfaced but deliberately not acted on |
| `contradicted` | New evidence or a new decision directly refutes this one |
| `refined` | This decision was partially updated but remains the core reference |
| `replaced` | A newer decision supersedes this one entirely (use `ec decision supersede`) |

## CLI / MCP Validity

Both the CLI (`ec decision outcome`) and the MCP tool (`ec_decision_outcome`) accept
the same valid set: `accepted`, `ignored`, `contradicted`, `refined`, `replaced`.
`core/decisions.py` defines the set as `VALID_DECISION_OUTCOME_TYPES`.
> **Ops note**: MCP stdio servers do not restart automatically after `uv sync`.
> After an upgrade changes `VALID_DECISION_OUTCOME_TYPES` or outcome logic, restart
> Claude Code to use the new server binary.

## Resolved Questions

- ~~Should `accepted` boost become weighted by outcome count or recency, or stay binary?~~ — Resolved: Ranking uses `accepted_outcome_boost` (default 2.0, `[decisions.ranking]`).
  The system applies it after another relevance signal matches. Version v0.7.0 separately added an extraction confidence boost (`accepted_boost_amount=0.10`, `accepted_boost_threshold=0.6`, `[decisions.extraction]`). Both boosts remain binary, not weighted.
- Supersede chains show only the head decision in list views; `ec decision chain <id>` walks the full chain for debugging.
