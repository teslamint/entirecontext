# Decision Outcome Semantics

This document specifies the current behavior of the five decision outcome types.
It records **how the system works now**, not a proposed change — any meaning change
requires a separate decision record.

## Truth Table

| Outcome | `quality_score` delta | Ranking boost | Shows as active | Auto-triggered by | Who sets it |
|---|---|---|---|---|---|
| `accepted` | `+1.0` | Binary `accepted_outcome_boost` after relevance match | Yes | — | User / subsequent decision work |
| `ignored` | `−0.5` | — | Yes | — | User |
| `contradicted` | `−2.0` | — | Yes (auto-promote candidate possible) | `_maybe_auto_promote_contradicted` | User |
| `refined` | 0 | — | Yes | — | User |
| `replaced` | 0 | — | Effectively no (superseded) | `supersede_decision` auto-link | `supersede_decision` caller |

### Notes

- **`replaced` quality_score = 0**: intentional design. `decisions.py` contains an
  explicit comment: *"paired with staleness superseded factor, no double-penalty"*.
  The staleness factor already down-ranks superseded decisions; a second score hit
  would double-penalise them unfairly.

- **`accepted` boost status**: accepted outcomes add a configurable binary boost
  only after another relevance signal already matched the decision. The boost is
  not a standalone retrieval seed.

- **`contradicted` auto-promote**: `_maybe_auto_promote_contradicted` may surface a
  competing candidate when a decision is contradicted. See `core/decisions.py` for
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
The set is defined in `core/decisions.py` as `VALID_DECISION_OUTCOME_TYPES`.

> **Ops note**: MCP stdio servers do not auto-restart after `uv sync`. After any
> upgrade that changes `VALID_DECISION_OUTCOME_TYPES` or outcome logic, restart
> Claude Code to pick up the new server binary.

## Resolved Questions

- ~~Should `accepted` boost become weighted by outcome count or recency, or stay binary?~~ — Resolved in v0.7.0: configurable binary boost (`accepted_boost_amount=0.10`, `accepted_boost_threshold=0.6`). Binary with threshold, not weighted.
- Supersede chains show only the head decision in list views; `ec decision chain <id>` walks the full chain for debugging.
