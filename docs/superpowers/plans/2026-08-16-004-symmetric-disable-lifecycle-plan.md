# Symmetric Disable Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development and execute this plan as one independently reviewable unit.

**Goal:** Make `ec disable` clean up selected agent and repository integrations symmetrically while requiring an explicit flag for global MCP removal.

**Architecture:** Keep Claude hooks and Codex notify agent-specific, move EntireContext-owned Git hook removal to the shared disable path, and gate exact standard MCP entry removal behind `--remove-mcp`.

**Tech Stack:** Python 3.12+, Typer/Rich, JSON configuration, pytest.

**Spec:** `docs/specs/2026-08-16-symmetric-disable-lifecycle-design.md`

**ADR:** `docs/adr/0012-explicit-global-mcp-cleanup.md`

**EC Decision:** `30f75661-044d-49e3-a434-b3ca93989be1`

---

## Global Constraints

- Do not delete configuration EC cannot identify as a standard EC form.
- Default disable must not mutate the global MCP entry.
- Preserve sibling MCP servers, unrelated top-level settings, empty containers, foreign Git hooks, and user-authored Claude hook structure.
- Do not add a repository-consumer ledger, schema migration, or dependency.
- Do not edit user-owned `LESSONS.md`, `.entire/`, or `.opencode/`.
- The Specification's six named tests and this Plan's test list must remain one-to-one.

### Task 1: Pin the lifecycle contract

**Files:**
- Modify: `tests/test_project_cmds.py`
- Modify: `tests/test_e2e_hooks_install.py`

**Interfaces:**
- Consumes: isolated repositories, fake HOME directories, `CliRunner` output and generated config files.
- Produces: observable assertions for selected-agent cleanup, shared repository cleanup, explicit global cleanup, and preservation boundaries.

- [x] **Step 1: Add the six Specification-named tests without merging**

1. `test_enable_disable_claude_with_explicit_mcp_cleanup`
2. `test_enable_disable_codex_removes_codex_and_repo_integrations_only`
3. `test_enable_disable_both_with_explicit_mcp_cleanup`
4. `test_disable_preserves_unrecognized_entirecontext_mcp_registration`
5. `test_disable_removes_generated_python_module_mcp_registration`
6. `TestHookInstall::test_disable_removes_hooks`

- [x] **Step 2: Verify authoring-time RED**

```bash
uv run pytest -q tests/test_project_cmds.py::TestEnableDisableRoundTrip tests/test_e2e_hooks_install.py::TestHookInstall::test_disable_removes_hooks
```

Observed 2026-08-16: `6 failed, 1 passed`. Explicit-cleanup cases exited 2 because `--remove-mcp` did not exist; the Codex-only case showed that unconditional MCP removal would break the retained Claude integration. This is the intended RED.

### Task 2: Implement safe symmetric cleanup

**Files:**
- Modify: `src/entirecontext/cli/project_cmds.py`

**Interfaces:**
- Consumes: `--agent`, `--remove-mcp`, current repository path, Claude/Codex settings, and user-level MCP JSON.
- Produces: selected agent cleanup, shared repository Git-hook cleanup, and optional standard MCP cleanup.

- [x] **Step 1: Recognize only standard EC MCP forms**

Add `_is_ec_mcp_server(value)` using the existing cross-platform `_executable_name()` helper. Accept only exact stdio dictionaries for `ec[.exe] mcp serve` or a Python executable running `-m entirecontext.cli mcp serve`.

- [x] **Step 2: Remove only the eligible entry**

Add `_remove_mcp_registration()` that deletes only `mcpServers.entirecontext`, preserves the `mcpServers` container and every sibling/top-level value, and returns whether it changed the file.

- [x] **Step 3: Separate repository and global cleanup**

Move `_remove_git_hooks(repo_path)` outside the agent-specific branches. Add `--remove-mcp`; call the MCP helper only when it is present. Keep Claude hooks and Codex notify in their existing agent branches.

- [x] **Step 4: Verify focused GREEN**

The Task 1 command reported `7 passed` after implementation.

### Task 3: Close the user-facing contract

**Files:**
- Modify: `README.md`
- Modify: `docs/spec.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md:301,354,383`
- Create: `docs/specs/2026-08-16-symmetric-disable-lifecycle-design.md`
- Create: `docs/adr/0012-explicit-global-mcp-cleanup.md`
- Create: `docs/superpowers/plans/2026-08-16-004-symmetric-disable-lifecycle-plan.md`

- [x] **Step 1: Document default and explicit cleanup**

State that default disable preserves the global MCP registration, every agent mode removes current-repository Git hooks, and `--remove-mcp` explicitly removes a standard global entry. Replace the manual JSON-removal recipe with the CLI command while retaining the exact manual-edit boundary.

- [x] **Step 2: Close and refresh roadmap evidence**

Mark `ROADMAP.md:354` complete with the new lifecycle boundary and evidence. The authoring-time carry-forward audit found fresh `lesson_reuse_rate=19%`, so refresh the stale 20% measurements at `ROADMAP.md:301` and `ROADMAP.md:383`. Other measured gates remain unchanged: maturity 64 (`capture=17`, `distill=17`, `retrieve=25`, `intervene=5`), applied-context rate 1%, enriched assessment `n=24`, agreement 95.8%.

### Task 4: Verify the complete changed contract

- [x] **Step 1: Run focused formatting and tests**

```bash
uv run ruff format src/entirecontext/cli/project_cmds.py tests/test_project_cmds.py tests/test_e2e_hooks_install.py
uv run ruff check src/entirecontext/cli/project_cmds.py tests/test_project_cmds.py tests/test_e2e_hooks_install.py
uv run pytest -q tests/test_project_cmds.py tests/test_e2e_hooks_install.py
```

Expected: Ruff exits 0 and both complete affected test modules pass.

Observed 2026-08-17: Ruff passed and the two complete affected modules reported `94 passed`.

- [x] **Step 2: Smoke-test the checkout-local command**

In an isolated Git repository and fake HOME, run `ec enable --agent codex`, then `ec disable --agent codex`, and observe notify plus Git hooks removed while MCP remains. Re-enable, run `ec disable --agent both --remove-mcp`, and observe all selected and explicitly requested artifacts removed while sibling configuration remains.

Observed 2026-08-16 with the checkout `.venv/bin/ec`, an isolated Git repository, and a fake HOME: Codex enable produced MCP, notify, and both Git hooks without Claude settings; Codex disable preserved MCP and removed notify plus both Git hooks; both-agent disable with `--remove-mcp` removed all EC integrations while preserving a sibling MCP server.

- [x] **Step 3: Run repository checks and traceability validation**

Run the full repository suite, `uv run ruff check .`, `uv run mypy src`, the active-reference validator, and `git diff --check`. Record exact outputs before commit and repeat the reference validator against committed `HEAD`.

Observed 2026-08-17 after resolving an independent configuration-safety review finding: the full suite reported `2233 passed, 1 skipped`; Ruff and mypy passed. The staged active-reference validator reported `84 checked; Markdown destinations: 9; bold references: 14; labels: 29`; the Specification name-status was one `A` entry with no `D`, `M`, or `R`; `git diff --cached --check` exited 0. The Specification and Plan enumerate the same six required tests in the same order. The review fix replaced marker-substring Git-hook ownership with exact generated-shape and command validation, then added foreign/composed-hook preservation and Python-fallback cleanup regressions; focused re-review returned clean.

## Assumption Recheck

- Automatic MCP removal is unsafe because the generated standard form is identical to the documented manual form and may serve other repositories or retained agent integrations.
- A cross-repository consumer ledger cannot reconstruct legacy installations and is out of scope for this P3 correction.
- Repository Git hooks are agent-neutral under accepted decision `f3dde400-139f-485b-ba39-9c4f5ff11fd3`; shared removal is therefore the correct inverse of shared installation.
- The six Specification test names appear one-for-one in Task 1; no test is merged or dropped.

## Carry-Forward Audit

- `ROADMAP.md:301` fired: recorded lesson reuse 20%, fresh dashboard 19%.
- `ROADMAP.md:383` fired: recorded lesson reuse 20%, fresh dashboard 19%.
- `ROADMAP.md:354` is implemented by this unit and will close.
- No other drift-based row changed from the fresh measurements listed in Task 3.

## Deferred Follow-Up Work

- Pre-merge review-thread race gate (`ROADMAP.md:358`).
- Plan-vs-Spec test-enumeration automation (`ROADMAP.md:359`).
- Any future cross-repository MCP consumer ledger; this change deliberately avoids claiming ownership it cannot prove.
