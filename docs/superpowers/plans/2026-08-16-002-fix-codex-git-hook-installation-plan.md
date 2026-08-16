# Codex Git Hook Installation Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use test-driven development and execute this plan as one independently reviewable unit.

**Goal:** Install EntireContext's repository Git hooks by default for `--agent codex` without installing Claude agent hooks, while preserving `--no-git-hooks`.

**Architecture:** Keep Claude settings and Codex notify in their existing agent-specific branches. Move the single `_install_git_hooks()` invocation to the shared integration path, still guarded by `no_git_hooks`, because checkpointing and pre-push synchronization are repository lifecycle behavior.

**Tech Stack:** Python 3.12+, Typer, pytest, Git hook fixtures, Ruff.

**Spec:** `docs/specs/2026-08-16-codex-git-hook-installation-design.md`

**Decision:** EC decision `f3dde400-139f-485b-ba39-9c4f5ff11fd3`

## Global Constraints

- Do not create `.claude/settings.local.json` for `--agent codex`.
- Do not change Git-hook script contents or ownership safeguards.
- Do not change Codex notify or MCP registration behavior.
- `--no-git-hooks` must suppress both repository hook files for every agent value.
- Do not change `ec disable`; its cleanup asymmetry remains a separate roadmap item.

---

### Task 1: Make Git-hook installation agent-neutral

**Files:**
- Create: `docs/specs/2026-08-16-codex-git-hook-installation-design.md`
- Create: `docs/superpowers/plans/2026-08-16-002-fix-codex-git-hook-installation-plan.md`
- Modify: `src/entirecontext/cli/project_cmds.py:497-543`
- Modify: `tests/test_project_cmds.py:758-790,1005-1025`
- Modify: `CHANGELOG.md:8-17`
- Modify: `ROADMAP.md:353`

**Interfaces:**
- Consumes: `agent`, `no_git_hooks`, repository path, existing `_install_git_hooks()` ownership checks.
- Produces: identical Git-hook installation for `claude`, `codex`, and `both`, with agent-specific settings still isolated.

- [ ] **Step 1: Write failing Codex lifecycle tests**

Rename the Codex enable and init tests to describe the desired contract. For both commands, require `post-commit` and `pre-push` files containing the EntireContext marker, and require `.claude/settings.local.json` to remain absent.

Run:

```bash
uv run pytest -q tests/test_project_cmds.py -k 'test_enable_codex_installs_git_hooks_without_claude_hooks or test_init_agent_codex_installs_git_hooks_without_claude_hooks'
```

Expected before the source change: both tests fail because `post-commit` does not exist.

Authoring-time observation (2026-08-16): exit 1; `2 failed, 75 deselected`. Both failures stop at `assert hook_path.exists()` for the missing `post-commit` file. This is the intended RED state.

- [ ] **Step 2: Move the existing Git-hook call to the shared path**

In `_install_integrations()`, remove the `_install_git_hooks()` block from the `agent in {"claude", "both"}` branch. Add the same block once at function scope after Claude settings installation and before Codex notify installation. Keep `if not no_git_hooks` around the call.

Do not change `_install_git_hooks()` itself.

- [ ] **Step 3: Pin the opt-out boundary**

Extend the existing Codex `--no-git-hooks` test to assert that neither repository hook path exists. This assertion must pass both before and after the source change; it protects the boundary affected by moving the call.

- [ ] **Step 4: Close the roadmap item and record the user-facing fix**

Change `ROADMAP.md:353` to checked. Record the shared call site, the preserved Claude/Codex separation, the retained opt-out, and the focused module test result. Add an Unreleased changelog entry describing the corrected Codex default and unchanged opt-out.

- [ ] **Step 5: Verify the full changed contract**

```bash
uv run ruff format src/entirecontext/cli/project_cmds.py tests/test_project_cmds.py
uv run ruff check src/entirecontext/cli/project_cmds.py tests/test_project_cmds.py
uv run pytest -q tests/test_project_cmds.py
```

Expected: Ruff exits 0 and the module reports 77 passing tests.

Authoring-time observations (2026-08-16): Ruff format reported `1 file reformatted, 1 file left unchanged`; Ruff check reported `All checks passed!`; the module test reported `77 passed in 8.25s`.

Smoke-test the checkout-local `.venv/bin/ec` rather than the separately installed `ec` command. In an isolated temporary Git repository and temporary `HOME`, run `ec enable --agent codex`; require both Git hooks, Codex notify, and no Claude agent settings.

Authoring-time observation (2026-08-16): the checkout-local executable reported `Git hooks installed: post-commit, pre-push`, `Codex notify installed`, and `MCP server configured`; filesystem assertions confirmed both EntireContext hook files, Codex notify configuration, and no `.claude/settings.local.json`.

## Assumption Recheck

The approved Spec retains three live assumptions. Exact `git show ea66322:...` commands reproduced the nested baseline call and the two old hook-absence assertions. `uv run pytest -q tests/test_project_cmds.py -k 'install_git_hooks'` reported `1 passed, 76 deselected`. No contradiction or unavailable evidence remains.

## Scenario Coverage Map

| Scenario | Unit chain | Observable evidence |
|---|---|---|
| S1: Enable Codex integration | Task 1 Steps 1-3 | `test_enable_codex_installs_git_hooks_without_claude_hooks` plus isolated CLI smoke test |
| S2: Initialize for Codex | Task 1 Steps 1-3 | `test_init_agent_codex_installs_git_hooks_without_claude_hooks` |
| S3: Opt out | Task 1 Step 3 | `test_enable_codex_writes_user_notify` hook-absence assertions |

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Carry-forward Trigger Audit

- `ROADMAP.md:204`, `:231`, `:300`, `:301`, and `:383` are drift-based and fired: fresh `ec dashboard` and `ec checkpoint assess-accuracy` observations are recorded in those rows in this change (`distill=17`; maturity 64; applied-context 1%; lesson reuse 20%; enriched n=24; agreement 95.8%). Targets remain open.
- `ROADMAP.md:353` is edit-based and fired: included in Task 1.
- `ROADMAP.md:354` touches the same lifecycle module but governs `disable`; explicitly deferred to the next dedicated cleanup item because the approved Scope/Out excludes disable behavior.
- `ROADMAP.md:359` is edit-based for new Plans and fired: this Plan names every Spec test one-for-one; no test is merged or dropped.
- `ROADMAP.md:360` is drift-based and already latched. The smoke attempt with the installed `uv run ec` reproduced checkout/install drift; it remains deferred to the separately ordered build-SHA provenance item.
- `ROADMAP.md:362` is edit-based for verification commands and fired: the authoring-time RED, formatter, lint, module-test, and checkout-local smoke observations are recorded immediately after their commands in this Plan.
- `ROADMAP.md:364` is drift-based and not fired: the governing EC decision was created directly in the base checkout database and resolves there.
- `ROADMAP.md:380` is drift-based and already latched: squash commit `11fb9ad` is processed but reachable-history convergence remains incomplete; remeasurement and disposition remain deferred to the ordered prerequisite-evaluation item.
- Every other open ROADMAP row was classified against the planned files and fresh observable state. None has an edit-based target in this unit or a newly fired drift/event condition; product candidates remain deferred to the ordered prerequisite-evaluation item.

## Open Unknowns

None. The implementation has one shared call-site change and no product fork.

## Deferred to Follow-Up Work

- `ec disable` MCP/Codex cleanup symmetry (`ROADMAP.md:354`).
- Build-SHA provenance for installed-tool drift (`ROADMAP.md:360`).
