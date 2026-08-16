# 0013. Enforce Executable Plan Contracts

**Status:** accepted
**Date:** 2026-08-17
**EC Decision:** `eb3bc2e9-fe02-44db-9a1f-29cea6ef05a0`

## Context

Two planning defects reached completed work despite explicit Specifications. One Plan omitted a Specification-named test by folding it into a sibling without recording the deviation. Another published a verification command that had never run and could not pass against the authoring checkout. A later review also proved that a multi-command block could emit an inner failure and still exit zero because its final command succeeded.

The external Plan validator covers frontmatter, not repository-specific test enumeration, shell classification, command execution, or durable evidence. Review prose and checklist completion therefore cannot establish that the Specification and executable Plan contract agree.

## Decision

Add a standard-library repository developer tool at `scripts/validate_plan.py` with two operations:

- `record` validates a Plan against its Specification, executes every exact `plan-check` block from the checkout root, and writes hash-bound JSON evidence to the validator-derived Plan/check-owned path under `docs/plans/evidence/` through anchored nonblocking/no-follow file operations and regular-file checks.
- `validate` checks the same structural contract and rejects missing, stale, tampered, unsafe, unowned, duplicate-key, or status-mismatched evidence without executing Plan commands.

Every governed Plan shell fence begins in column zero and is classified as `plan-check` or `implementation-only reason=<lowercase-slug>`; potential verification commands cannot remain in inline code. Every check starts with `set -euo pipefail` and declares an identifier, expected status, and canonical evidence path. Plan and Specification inputs are UTF-8/LF; command text and combined output bytes are preserved without newline or decoding normalization. Every Specification test identifier receives exactly one retained, merged, or dropped row in the Plan's Spec Test Disposition table; merged and dropped rows require rationale.

This remains a repository authoring tool rather than an `ec` CLI or MCP feature.

## Consequences

- Plan authors must execute exact final checks before approval and commit their full observable evidence.
- Reviewers can reproduce a deterministic structural and integrity check without rerunning implementation commands.
- Silent test merges and drops become explicit review decisions.
- Fail-open multi-command checks are rejected before execution.
- Evidence binds the canonical full record as well as individual content hashes. This detects accidental partial edits, but is not a signature against a malicious editor who can recompute the hash.
- Historical Plans remain untouched; enforcement applies when a new behavior-changing Plan adopts this contract.
- Evidence JSON adds durable repository artifacts, but each file is canonically owned by one Plan/check and contains only command output the author explicitly chose to record.

## Rejected Alternatives

### Rely on reviewer memory and manual comparison

Rejected. Both roadmap items exist because a manual planning/review process reported completion while violating the Specification.

### Extend only the external Plan validator

Rejected. The installed validator is an external frontmatter contract and does not own this repository's Specification layout, test disposition table, command evidence directory, or mutation requirements.

### Add the guard to the product CLI

Rejected. Plan authoring policy is repository maintenance behavior, not an EntireContext user-facing runtime capability.

### Re-execute checks during validation

Rejected. Validation must be side-effect-free and suitable for review. Execution is explicit in `record`; `validate` verifies its evidence and integrity bindings.

### Hash the entire working tree

Rejected. Runtime files and hook-generated artifacts make a whole-checkout fingerprint unstable and unrelated to a Plan's authored contract. Evidence instead binds the exact Plan, Specification, command, byte-preserved output, expected/actual status, timestamp, and canonical full record.

## References

- Specification: [`docs/specs/2026-08-17-planning-contract-enforcement-design.md`](../specs/2026-08-17-planning-contract-enforcement-design.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- Failure guidance: [`docs/solutions/workflow-issues/make-verification-commands-fail-closed.md`](../solutions/workflow-issues/make-verification-commands-fail-closed.md)
