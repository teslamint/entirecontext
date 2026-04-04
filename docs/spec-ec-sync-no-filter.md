# Spec: `ec sync --no-filter` Runtime Propagation

## Status
- Proposed
- Owner: EntireContext CLI/Sync
- Scope: `ec sync` command path only

## Problem Statement
`ec sync` currently accepts `--no-filter`, but the option is not propagated to the runtime sync config passed to `perform_sync(...)`.
As a result, export filtering behavior is not explicitly controlled by the CLI flag at runtime.

## Goal
Define and enforce the runtime contract for `ec sync --no-filter` so that the behavior is deterministic and testable.

## Non-Goals
- Redesign of the full security filtering system
- Changes to unrelated commands (`pull`, search, purge, etc.)
- New filtering patterns or masking algorithms

## Public Interface
CLI entrypoint:
- `ec sync`
- `ec sync --no-filter`

Runtime contract to `perform_sync(conn, repo_path, config=...)`:
- The CLI must pass a `config` object containing `security.filter_secrets`.
- `security.filter_secrets=False` when `--no-filter` is provided.
- `security.filter_secrets=True` when `--no-filter` is not provided.

## Expected Behavior
### Positive Condition
When the user runs `ec sync --no-filter`:
- Sync runtime config must include `{"security": {"filter_secrets": false}}`.
- Export path must treat filtering as disabled.

### Negative Condition
When the user runs `ec sync` (without `--no-filter`):
- Sync runtime config must include `{"security": {"filter_secrets": true}}`.
- Export path must keep filtering enabled by default.

### Failure Condition (Spec Guard)
If the CLI flag is not propagated and `perform_sync(..., config={})` is used:
- Spec tests must fail with explicit assertions indicating missing runtime propagation.

## Design Constraints
- Keep behavior explicit at call boundary (CLI -> sync engine).
- Do not rely on implicit defaults for this contract; pass intent explicitly.
- Preserve existing sync result handling and output format.

## TDD Red Test Spec
Target file:
- `tests/test_sync_cmds.py`

Required tests:
1. `test_sync_no_filter_option_disables_filtering_in_runtime_config`
2. `test_sync_default_keeps_filtering_enabled`

Assertion focus:
- Inspect `perform_sync` call args and validate:
  - `config["security"]["filter_secrets"] is False` for `--no-filter`
  - `config["security"]["filter_secrets"] is True` for default

Required failure messages:
- `"--no-filter must propagate to runtime sync config"`
- `"default sync must keep secret filtering enabled in runtime config"`

## Acceptance Criteria
- The two contract tests above exist and are executable.
- In Red stage (before implementation), both fail for the current missing propagation.
- Failures clearly indicate config propagation gap, not unrelated runtime errors.

## Implementation Notes (for Green stage)
- Wire `no_filter` in `src/entirecontext/cli/sync_cmds.py` into a runtime config dict passed to `perform_sync`.
- Ensure sync engine/export path consumes `security.filter_secrets` consistently.
- Keep backward compatibility for callers that do not pass this key.

## Risks
- If engine/export ignore `security.filter_secrets`, Green can pass CLI tests but still fail end-to-end filtering behavior.
- Additional e2e tests may be needed after Green to validate actual redacted/unredacted output.

