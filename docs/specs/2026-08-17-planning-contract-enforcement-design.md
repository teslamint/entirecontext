---
title: Planning Contract Enforcement
status: approved
date: 2026-08-17
schema: spec/v1
---

# Planning Contract Enforcement Design

## Overview

Planning regressions have passed review in two distinct ways: a Plan silently merged or dropped a Specification-named test, and a Plan published a verification command that had never been executed and could not pass against the authoring checkout. Repository planning needs an executable contract that compares named tests, classifies shell fences, runs exact fail-closed checks, and preserves their full observable evidence.

The governing EC decision is `eb3bc2e9-fe02-44db-9a1f-29cea6ef05a0`.

## Goals

1. Require an explicit disposition for every test identifier named in a Specification's `## Testing` section.
2. Require every shell fence in a governed Plan to be classified as either `plan-check` or `implementation-only`.
3. Require every `plan-check` block to begin with `set -euo pipefail` and declare its expected status and evidence path.
4. Execute each exact `plan-check` block during authoring and persist its combined output, actual status, timestamp, and integrity hashes.
5. Reject missing, stale, tampered, unsafe, or status-mismatched evidence before a Plan is accepted.
6. Keep the enforcement repository-local and standard-library-only.

## Non-Goals

- Adding a public `ec` command or MCP tool.
- Retrofitting historical Plans or archived release evidence.
- Executing `implementation-only` blocks.
- Inferring whether a merged or dropped test rationale is substantively correct.
- Replacing project test runners, CI, or the external Plan frontmatter validator.

## User Scenarios

### S1: Preserve the Specification test contract

A Specification names tests under `## Testing`. Its Plan contains a `## Spec Test Disposition` table with exactly one row for each identifier. Retained tests map to themselves. Merged and dropped tests carry a non-empty rationale, making every deviation reviewable.

### S2: Record exact authoring-time checks

A Plan marks a shell fence as `plan-check`, declares a stable identifier, expected status, and repository-relative evidence path, and starts the command with `set -euo pipefail`. The author runs the repository tool's `record` command. The tool executes the block verbatim from the checkout root and writes full combined output and integrity metadata under `docs/plans/evidence/`.

### S3: Reject stale or altered evidence

A reviewer runs the tool's `validate` command. The command rejects evidence when the Plan, Specification, command text, output, or declared status no longer matches the recorded hashes and values.

### S4: Preserve implementation instructions without executing them

A Plan marks setup, mutation, and implementation command fences as `implementation-only`. The validator confirms their classification but does not execute them.

## Interface Contract

```text
python scripts/validate_plan.py record --plan PLAN --spec SPEC
python scripts/validate_plan.py validate --plan PLAN --spec SPEC
```

A governed shell fence uses one of these info strings:

```text
bash implementation-only reason=<lowercase-slug>
bash plan-check id=<lowercase-slug> expected-status=<integer> evidence=docs/plans/evidence/<plan-stem>-<plan-path-sha256-prefix>/<check>.json
```

`record` validates the Plan structure and Spec disposition table before executing checks. It writes one JSON evidence document per check and exits nonzero if any actual status differs from the declared expected status. `validate` never executes Plan commands; it validates structure, evidence ownership and location, required fields, hashes, timestamp, and status agreement.

## Spec Test Disposition Contract

The Plan section must be headed `## Spec Test Disposition` and use these columns:

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
| `test_example` | retained | `test_example` | — |

Rules:

- Every Specification test appears exactly once; extra and duplicate rows are rejected.
- Disposition is exactly `retained`, `merged`, or `dropped`.
- A retained row maps to the same identifier.
- A merged row names at least one Plan test and has a substantive rationale.
- A dropped row names no Plan test and has a substantive rationale.

## Evidence Contract

Evidence is UTF-8 JSON under a Plan-owned `docs/plans/evidence/<plan-stem>-<plan-path-sha256-prefix>/` directory and contains:

- schema version, Plan and Specification paths, and check identifier;
- exact command text and expected/actual statuses;
- full combined stdout/stderr bytes, represented reversibly with UTF-8 `surrogateescape`;
- timezone-aware recording timestamp;
- SHA-256 hashes of the Plan, Specification, command, output bytes, and canonical full record.

The validator resolves every input and evidence path against the checkout root. Absolute paths, `..` traversal, every symlinked evidence component, non-JSON files, and evidence paths not canonically derived from the Plan path and check identifier are rejected. Evidence is opened through anchored nonblocking/no-follow directory descriptors with regular-file checks, then written through a random exclusive temporary and atomic replacement; an existing record with mismatched Plan/check ownership is never overwritten.

## Error and Safety Behavior

- Missing sections, malformed tables, duplicate identifiers or JSON keys, unsupported fence metadata, backticks inside a backtick-fence info string, and unclosed fences fail closed.
- A governed shell fence must begin in column zero. Any whitespace-indented, blockquote-prefixed, or list-prefixed shell-fence-looking block is rejected rather than silently treated as top-level, container-nested, or literal code. Every shell fence requires either `implementation-only reason=<lowercase-slug>` or `plan-check`; command-shaped inline code spans are rejected for any matched backtick-delimiter length. Unambiguous bare project runners (`pytest`, `ruff`, `mypy`, `make`) are always command-shaped; spans introduced by Run/execute/invoke/call and multi-token spans containing any known shell/tool command are also command-shaped.
- A `plan-check` whose first nonblank line after removing only ASCII spaces/tabs is not exactly `set -euo pipefail` fails validation. Plans and Specifications must be UTF-8 with LF line endings; Unicode line/paragraph separators are never normalized into command boundaries.
- `record` uses `/bin/bash -c` with the exact block text, merges stderr into stdout, preserves output bytes losslessly, and does not use `shell=True`.
- Evidence is written even when a check returns an unexpected status so the failure remains inspectable; the command still exits nonzero.
- `validate` recomputes individual content hashes and the canonical whole-record hash. The whole-record hash detects accidental mutation; it is not a cryptographic signature against a malicious editor.
- No Plan command runs during `validate`.

## Testing

The implementation must retain these distinct observable tests without merging or renaming them silently:

1. `test_validate_accepts_recorded_plan_contract`
2. `test_validate_rejects_missing_spec_test_disposition`
3. `test_validate_rejects_merged_test_without_rationale`
4. `test_validate_rejects_unclassified_shell_fence`
5. `test_validate_rejects_plan_check_without_fail_closed_prefix`
6. `test_validate_rejects_inline_verification_command`
7. `test_validate_rejects_non_lf_plan_commands`
8. `test_validate_rejects_stale_command_evidence`
9. `test_validate_rejects_tampered_output_evidence`
10. `test_validate_rejects_evidence_path_escape`
11. `test_record_propagates_masked_failure`
12. `test_validate_rejects_status_mismatch`

## Success Criteria

1. A clean fixture can record and validate one Plan check.
   - **Measured by**: `test_validate_accepts_recorded_plan_contract` passes.
2. Missing or unjustified Specification test dispositions are rejected.
   - **Measured by**: the missing-disposition and missing-rationale tests pass.
3. Every shell fence is classified with a rationale where required, every check is fail-closed, and verification commands cannot hide in inline code.
   - **Measured by**: the unclassified-fence, inline-command, non-LF, missing-prefix, and masked-failure tests pass.
4. Evidence remains bound to Plan/check-owned safe paths and exact Plan, Specification, command, output bytes, and status values.
   - **Measured by**: the stale-command, tampered-output, path-escape/symlink/ownership, duplicate-key, whole-record-hash, and status-mismatch mutations pass.
5. The repository policy requires the guard for new behavior-changing Plans.
   - **Measured by**: `AGENTS.md` documents the two commands, fence classifications, disposition table, and committed evidence requirement.
6. ROADMAP items 359 and 362 close with executable evidence.
   - **Measured by**: both rows are checked and cite this Specification, ADR 0013, and the repository tool.

## Open Decisions

None. The ordered roadmap work authorizes the repository-local guard. The EC decision rejects reviewer-memory, frontmatter-only, and public-product-CLI alternatives.
