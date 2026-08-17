# Planning Contract Enforcement Implementation Plan

> **For agentic workers:** execute this Plan as one independently reviewable repository-policy unit. Use test-driven development and preserve every Specification-named test.

**Goal:** Close ROADMAP 359 and 362 with a repository-local guard that enforces Spec test dispositions and exact authoring-time verification evidence.

**Architecture:** Add one standard-library developer script with structural parsing, explicit command recording, and side-effect-free evidence validation. Keep the feature outside `ec`; pytest exercises the observable CLI contract in isolated temporary checkouts.

**Tech Stack:** Python 3.12+ standard library, pytest, Markdown, JSON, Bash.

**Spec:** `docs/specs/2026-08-17-planning-contract-enforcement-design.md`

**Decision:** EC decision `eb3bc2e9-fe02-44db-9a1f-29cea6ef05a0`; companion ADR `docs/adr/0013-executable-plan-contracts.md`

## Global Constraints

- Do not add product CLI, MCP, schema, dependency, or runtime-package surface.
- Execute only explicitly classified `plan-check` blocks and only through the `record` operation.
- `validate` must remain side-effect-free.
- Preserve full combined command output; do not truncate or normalize it.
- Reject unsafe evidence paths before creating directories or opening files.
- Historical Plans and archived evidence remain unchanged.
- Every rejection path named by the Specification receives an observable mutation test.

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
| `test_validate_accepts_recorded_plan_contract` | retained | `test_validate_accepts_recorded_plan_contract` | — |
| `test_validate_rejects_missing_spec_test_disposition` | retained | `test_validate_rejects_missing_spec_test_disposition` | — |
| `test_validate_rejects_merged_test_without_rationale` | retained | `test_validate_rejects_merged_test_without_rationale` | — |
| `test_validate_rejects_unclassified_shell_fence` | retained | `test_validate_rejects_unclassified_shell_fence` | — |
| `test_validate_rejects_plan_check_without_fail_closed_prefix` | retained | `test_validate_rejects_plan_check_without_fail_closed_prefix` | — |
| `test_validate_rejects_inline_verification_command` | retained | `test_validate_rejects_inline_verification_command` | — |
| `test_validate_rejects_non_lf_plan_commands` | retained | `test_validate_rejects_non_lf_plan_commands` | — |
| `test_validate_rejects_stale_command_evidence` | retained | `test_validate_rejects_stale_command_evidence` | — |
| `test_validate_rejects_tampered_output_evidence` | retained | `test_validate_rejects_tampered_output_evidence` | — |
| `test_validate_rejects_evidence_path_escape` | retained | `test_validate_rejects_evidence_path_escape` | — |
| `test_record_propagates_masked_failure` | retained | `test_record_propagates_masked_failure` | — |
| `test_validate_rejects_status_mismatch` | retained | `test_validate_rejects_status_mismatch` | — |

---

### Task 1: Pin the executable contract with failing tests

**Files:**
- Create: `tests/test_validate_plan.py`
- Test: `tests/test_validate_plan.py`

- [x] **Step 1: Build isolated Plan, Spec, and evidence fixtures**

Create temporary checkout fixtures with a minimal approved Specification, a governed Plan, and repository-relative evidence paths. Invoke the repository validator script through the current Python interpreter so tests cover argument parsing, filesystem behavior, command execution, diagnostics, and exit status.

- [x] **Step 2: Add all twelve Specification-named tests**

Keep every test distinct. The clean test records then validates one successful check. Mutation tests remove a Spec row, remove merged-test rationale, leave a shell fence unclassified, omit an implementation-only rationale, nest a shell fence under whitespace indentation, a blockquote/list prefix, or a list continuation, put a backtick in backtick-fence info, hide commands in single- and double-backtick inline code, use CRLF or Unicode separators, remove the fail-closed prefix, change a recorded command, alter byte-exact stored output, escape or symlink the evidence root, attempt cross-Plan evidence ownership, pre-create the old predictable temporary as a symlink, substitute a FIFO evidence target, run an inner failure followed by success, introduce duplicate JSON keys, alter actual status, and mutate a whole-record-bound failed status.

- [x] **Step 3: Run authoring-time RED**

```bash implementation-only reason=authoring-red
uv run pytest -q tests/test_validate_plan.py
```

Expected before implementation: collection or execution fails because `scripts/validate_plan.py` does not exist.

### Task 2: Implement structural validation and evidence recording

**Files:**
- Create: `scripts/validate_plan.py`
- Modify: `tests/test_validate_plan.py`

- [x] **Step 1: Parse and compare the Spec test contract**

Extract backticked test identifiers from the Specification `## Testing` section. Parse the Plan's exact four-column `## Spec Test Disposition` table. Reject missing, extra, duplicate, invalid, or unjustified rows; retained rows map to the same identifier, merged rows name Plan tests and rationale, and dropped rows name rationale without Plan tests.

- [x] **Step 2: Parse and classify shell fences**

Recognize Bash, `sh`, and `shell` fences only when they begin in column zero. Reject whitespace-indented, blockquote-prefixed, list-prefixed, and list-continuation shell-fence-looking blocks plus backticks inside backtick-fence info rather than silently over- or under-recognizing them. Accept only `implementation-only reason=<lowercase-slug>` or `plan-check` classifications. Reject command-shaped inline code for any matched backtick-delimiter length. Require check metadata keys `id`, `expected-status`, and `evidence`, unique IDs and paths, a lowercase slug ID, canonical Plan/check-owned evidence paths, UTF-8/LF inputs, and `set -euo pipefail` as the first nonblank command line after removing ASCII spaces/tabs only. Reject malformed or unclosed fences.

- [x] **Step 3: Record exact command evidence**

Execute each check with `/bin/bash` and its `-c` option from the checkout root with stderr merged into stdout. Preserve output bytes reversibly with UTF-8 `surrogateescape`. Write schema, relative Plan/Spec paths, check ID, exact command, expected/actual status, full output, timezone-aware timestamp, individual SHA-256 hashes, and a canonical whole-record hash. Recheck the Plan and Specification after execution. Write through anchored nonblocking/no-follow directory descriptors, regular-file checks, a random exclusive temporary, and atomic replacement; never overwrite mismatched ownership. Write evidence even on unexpected status, then return nonzero.

- [x] **Step 4: Validate without execution**

Resolve all paths within the checkout. Require the exact `docs/plans/evidence/<plan-stem>-<plan-path-sha256-prefix>/<check>.json` destination and reject absolute paths, traversal, every symlinked component, and ownership mismatch. Read through anchored no-follow descriptors. Reject duplicate JSON keys; recompute current Plan/Spec/command, byte-exact stored-output, and whole-record hashes; validate the timestamp and required fields; and reject missing, stale, tampered, or status-mismatched evidence without spawning a Plan command.

- [x] **Step 5: Reach GREEN and run focused static checks**

```bash implementation-only reason=focused-green
uv run ruff format scripts/validate_plan.py tests/test_validate_plan.py
uv run ruff check scripts/validate_plan.py tests/test_validate_plan.py
uv run pytest -q tests/test_validate_plan.py
```

Expected: Ruff exits 0 and all twelve Specification-named tests pass.

### Task 3: Establish repository policy and close the roadmap rows

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md:359,362`
- Create: `docs/specs/2026-08-17-planning-contract-enforcement-design.md`
- Create: `docs/adr/0013-executable-plan-contracts.md`
- Create: `docs/superpowers/plans/2026-08-17-005-planning-contract-enforcement-plan.md`

- [x] **Step 1: Document the planning gate**

Add an AGENTS policy for new behavior-changing Plans: exact Spec Test Disposition coverage, classified shell fences, fail-closed checks, `record` before approval, `validate` before commit/review, and committed evidence under `docs/plans/evidence/`. State that historical Plans are not retroactively governed.

- [x] **Step 2: Close ROADMAP 359 and 362**

Record the concrete tool, evidence boundary, twelve mutation/acceptance tests, governing Specification, ADR 0013, and EC decision. Do not close ROADMAP 364; instead verify this unit's decision resolves from the base checkout before completion.

- [x] **Step 3: Update the unreleased changelog**

Add one process-tooling entry describing executable Spec test dispositions and authoring-time check evidence without presenting the script as product surface.

### Task 4: Record and verify the final authored contract

**Files:**
- Create: `docs/plans/evidence/2026-08-17-005-planning-contract-enforcement-plan-b16ed3b221fe/planning-contract.json`
- Test: repository checks below

- [x] **Step 1: Finalize the Plan before recording**

Mark completed steps and ensure no later edit changes the Plan or Specification. Run the record operation for this Plan and Specification; the declared check below is executed verbatim and its complete evidence is written to the declared path.

- [x] **Step 2: Validate persisted evidence without execution**

Run the validate operation against the same Plan and Specification. Confirm it exits 0, then mutation-test stale command, tampered output, path escape, masked failure, and status mismatch through the focused pytest module.

- [x] **Step 3: Verify repository traceability and decision persistence**

Run the active-reference validator, confirm the new Specification is one added file with no modification/deletion/rename of approved Specifications, and verify the linked EC decision from the base checkout.

```bash plan-check id=planning-contract expected-status=0 evidence=docs/plans/evidence/2026-08-17-005-planning-contract-enforcement-plan-b16ed3b221fe/planning-contract.json
set -euo pipefail
uv run ruff check scripts/validate_plan.py tests/test_validate_plan.py
uv run pytest -q tests/test_validate_plan.py
ec decision show eb3bc2e9-fe02-44db-9a1f-29cea6ef05a0 >/dev/null
```

Expected: Ruff exits 0 and the focused module passes all twelve Specification-named tests. The `record` operation preserves this exact output and status; the subsequent `validate` operation confirms the evidence bindings.

## Assumption Recheck

- Existing pytest infrastructure can measure every acceptance and mutation contract; no measurement prerequisite is missing.
- The installed external Plan validator covers frontmatter only and cannot enforce this repository's executable contracts.
- `docs/plans/evidence/` is a durable repository path; it is not under ignored `.release-loop/` runtime state.
- Full-tree hashing is intentionally rejected because runtime and hook-generated files would make valid evidence unstable.

## Carry-Forward Audit

- `ROADMAP.md:359` is implemented by the Spec Test Disposition guard and will close.
- `ROADMAP.md:362` is implemented by exact check recording, fail-closed classification, and evidence validation and will close.
- `ROADMAP.md:364` remains open; this unit satisfies its immediate risk manually by verifying the new decision from the base checkout before completion.
- No measurement row is refreshed by this process-only unit.

## Deferred Follow-Up Work

- Integrating `scripts/validate_plan.py` into CI after enough repository usage establishes a stable scope and runtime.
- Retrofitting historical Plans; this unit deliberately governs new behavior-changing Plans only.
- Automating base-worktree decision promotion under ROADMAP 364.
