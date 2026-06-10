# Development Process Conventions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish four development process guardrails: Conventional Commits CI gate, measure-first principle, ADR tracking, and mypy strict type checking (with grandfather for legacy).

**Architecture:** CI workflow additions + AGENTS.md policy updates + new `docs/adr/` directory + mypy strict config in pyproject.toml with per-module overrides for legacy code.

**Tech Stack:** GitHub Actions (`amannn/action-semantic-pull-request@v5`), mypy 2.1+, pyproject.toml

**Callers:** CI pipeline (ci.yml), all agent workflows (AGENTS.md), contributor onboarding.

**Invariants:**
- Existing CI jobs (lint, test) must not break.
- `uv run mypy src/entirecontext/` must pass with zero errors after changes — strict default + grandfather overrides guarantee this.
- AGENTS.md remains the canonical policy source.

**Prior retro carry-forward:** measure-first lesson from v0.8.1 retro.

**Follow-up (out of scope):** Add `type-check` and `commit-lint` to branch protection required checks — repo settings change, not automatable via code.

---

### Task 1: Conventional Commits CI Gate

**Files:**
- Create: `.github/workflows/commit-lint.yml`

- [ ] **Step 1: Create commit-lint workflow**

Use `amannn/action-semantic-pull-request@v5` (1350★, validates PR titles). Since the repo uses squash-merge, PR title = final commit message.

```yaml
name: Commit Lint

on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

permissions:
  pull-requests: read

jobs:
  conventional-commits:
    runs-on: ubuntu-latest
    steps:
      - uses: amannn/action-semantic-pull-request@v5
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          types: |
            feat
            fix
            ref
            perf
            docs
            test
            build
            ci
            chore
            style
            meta
            license
            revert
          validateSingleCommit: true
          validateSingleCommitMatchesPrTitle: true
```

Notes:
- `ref` is the project convention for refactoring (not `refactor`).
- `validateSingleCommit: true` catches single-commit PRs where GitHub suggests the commit message instead of PR title.
- `permissions: pull-requests: read` — minimum required.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/commit-lint.yml
git commit -m "ci: add Conventional Commits PR title validation

Uses amannn/action-semantic-pull-request@v5 to enforce
project commit types including 'ref' for refactoring."
```

---

### Task 2: Measure-First Principle + ADR Workflow in AGENTS.md

**Files:**
- Modify: `AGENTS.md` — add two new sections

- [ ] **Step 1: Add Measure-First Principle section**

Insert after the "Dogfooding Workflow" table (after line 33, before "Decision and Lesson Reuse Policy"):

```markdown
## Measure-First Principle

Before implementing any feature or behavior change:

1. Define measurable success criteria (metric name, target value, measurement method).
2. Verify the measurement infrastructure exists and works (dashboard query, test assertion, CLI command).
3. If measurement infra is missing, build it first as a separate commit/PR.
4. After implementation, verify the metric moved as expected.

Skip only for pure documentation, config, or CI-only changes. State when skipped and why.

Rationale: v0.8.1 showed that building features without pre-existing measurement leads to formula bugs that ship undetected across multiple releases.
```

- [ ] **Step 2: Add ADR Workflow section**

Insert immediately after "Measure-First Principle":

```markdown
## Architecture Decision Records (ADR)

Decisions with cross-cutting or long-lived impact go into `docs/adr/` using the template in `docs/adr/README.md`.

### When to write an ADR
- New module boundaries, data model changes, or public interface contracts
- Technology or dependency choices
- Convention or policy establishment (like this one)
- Any decision where "why not the obvious alternative?" deserves a written answer

### ADR ↔ EC Decision bridge
- ADRs reference EC decision IDs in their footer when an EC record exists.
- EC decisions that graduate to project-wide policy should get a companion ADR.
- Lightweight decisions stay as EC records only; ADRs are for durable, cross-cutting policy.
```

- [ ] **Step 3: Add Spec → ADR → Plan → Code traceability note**

In the existing "Commit & Pull Request Guidelines" section (line 13), append:

```markdown
- Decision traceability chain: Spec (`docs/superpowers/plans/`) → ADR (`docs/adr/`) → Plan → Code. PRs that change behavior should reference the governing ADR or EC decision.
```

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): add measure-first principle, ADR workflow, and traceability chain"
```

---

### Task 3: ADR Directory Bootstrap

**Files:**
- Create: `docs/adr/README.md`
- Create: `docs/adr/0001-adr-process.md`

- [ ] **Step 1: Create ADR README with template**

`docs/adr/README.md`:

```markdown
# Architecture Decision Records

This directory contains Architecture Decision Records (ADR) for the EntireContext project.

## Convention

- Number sequentially: `NNNN-short-title.md`
- Status lifecycle: `proposed` → `accepted` → (`deprecated` | `superseded by NNNN`)
- Use the template below for new ADRs.

## Template

```
# NNNN. Short Title

**Status:** proposed | accepted | deprecated | superseded by [NNNN](NNNN-title.md)
**Date:** YYYY-MM-DD
**EC Decision:** `<id>` (if applicable)

## Context

What is the issue that we're seeing that is motivating this decision or change?

## Decision

What is the change that we're proposing and/or doing?

## Consequences

What becomes easier or more difficult to do because of this change?
```
```

- [ ] **Step 2: Create bootstrap ADR (0001)**

`docs/adr/0001-adr-process.md`:

```markdown
# 0001. Use ADRs for Cross-Cutting Decisions

**Status:** accepted
**Date:** 2026-06-09

## Context

The project uses EntireContext's decision memory for tracking implementation decisions.
However, durable cross-cutting policies (coding conventions, CI gates, architectural boundaries)
need a format that is version-controlled, discoverable without tooling, and readable in plain text.

## Decision

Adopt Architecture Decision Records in `docs/adr/` for cross-cutting decisions.
Lightweight implementation decisions remain as EC decision records.
ADRs reference EC decision IDs when both exist.

## Consequences

- Contributors can discover project policies by browsing `docs/adr/`.
- The ADR ↔ EC decision bridge avoids duplicate record-keeping.
- New ADRs require a PR, adding review friction (intentional for durable decisions).
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/
git commit -m "docs(adr): bootstrap ADR directory with template and process record"
```

---

### Task 4: mypy Strict with Grandfather Overrides

**Files:**
- Modify: `pyproject.toml` — add `[tool.mypy]` strict config + overrides
- Modify: `.github/workflows/ci.yml` — add type-check job
- Create: `docs/adr/0002-mypy-strict-gradual.md`

**Key design: strict default + grandfather.** mypy runs in strict mode globally. The 79 legacy modules that currently fail get `ignore_errors = true` overrides. New files are strict from day one. The override list shrinks over time as modules are annotated.

- [ ] **Step 1: Add mypy strict configuration to pyproject.toml**

Add after `[tool.ruff]` section:

```toml
[tool.mypy]
python_version = "3.12"
strict = true

# Legacy modules grandfathered from strict mode (2026-06-09).
# Shrink this list over time. See docs/adr/0002-mypy-strict-gradual.md.
[[tool.mypy.overrides]]
module = [
    "entirecontext.cli.ast_cmds",
    "entirecontext.cli.blame_cmds",
    "entirecontext.cli.checkpoint_cmds",
    "entirecontext.cli.dashboard_cmds",
    "entirecontext.cli.decisions_cmds",
    "entirecontext.cli.event_cmds",
    "entirecontext.cli.futures_cmds",
    "entirecontext.cli.graph_cmds",
    "entirecontext.cli.hook_cmds",
    "entirecontext.cli.import_cmds",
    "entirecontext.cli.index_cmds",
    "entirecontext.cli.mcp_cmds",
    "entirecontext.cli.project_cmds",
    "entirecontext.cli.purge_cmds",
    "entirecontext.cli.repo_cmds",
    "entirecontext.cli.rewind_cmds",
    "entirecontext.cli.search_cmds",
    "entirecontext.cli.session_cmds",
    "entirecontext.cli.sync_cmds",
    "entirecontext.core.activation",
    "entirecontext.core.agent_graph",
    "entirecontext.core.ast_index",
    "entirecontext.core.async_worker",
    "entirecontext.core.attribution",
    "entirecontext.core.auto_apply",
    "entirecontext.core.auto_assess",
    "entirecontext.core.checkpoint",
    "entirecontext.core.config",
    "entirecontext.core.consolidation",
    "entirecontext.core.content_filter",
    "entirecontext.core.context",
    "entirecontext.core.cross_repo",
    "entirecontext.core.dashboard",
    "entirecontext.core.decision_candidates",
    "entirecontext.core.decision_extraction",
    "entirecontext.core.decision_prompt_surfacing",
    "entirecontext.core.decisions",
    "entirecontext.core.embedding",
    "entirecontext.core.event",
    "entirecontext.core.futures",
    "entirecontext.core.knowledge_graph",
    "entirecontext.core.llm",
    "entirecontext.core.project",
    "entirecontext.core.purge",
    "entirecontext.core.resolve",
    "entirecontext.core.search",
    "entirecontext.core.security",
    "entirecontext.core.session",
    "entirecontext.core.telemetry",
    "entirecontext.core.tidy_pr",
    "entirecontext.core.turn",
    "entirecontext.db.migrations",
    "entirecontext.db.migrations.v005",
    "entirecontext.db.migrations.v011",
    "entirecontext.db.migrations.v012",
    "entirecontext.db.schema",
    "entirecontext.hooks.codex_ingest",
    "entirecontext.hooks.decision_hooks",
    "entirecontext.hooks.handler",
    "entirecontext.hooks.session_lifecycle",
    "entirecontext.hooks.turn_capture",
    "entirecontext.mcp.runtime",
    "entirecontext.mcp.server",
    "entirecontext.mcp.tools.checkpoint",
    "entirecontext.mcp.tools.decision_candidates",
    "entirecontext.mcp.tools.decisions",
    "entirecontext.mcp.tools.futures",
    "entirecontext.mcp.tools.misc",
    "entirecontext.mcp.tools.search",
    "entirecontext.mcp.tools.session",
    "entirecontext.sync.auto_sync",
    "entirecontext.sync.coordinator",
    "entirecontext.sync.engine",
    "entirecontext.sync.export_flow",
    "entirecontext.sync.exporter",
    "entirecontext.sync.git_transport",
    "entirecontext.sync.merge",
    "entirecontext.sync.security",
    "entirecontext.sync.shadow_branch",
]
ignore_errors = true
```

- [ ] **Step 2: Verify mypy passes**

```bash
uv run mypy src/entirecontext/
```

Expected: `Success: no issues found in 111 source files` (or similar zero-error output). If any errors remain, the override list is incomplete — add the missing module.

- [ ] **Step 3: Add type-check CI job**

Add to `.github/workflows/ci.yml` after the `lint` job:

```yaml
  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Type check
        run: uv run mypy src/entirecontext/
```

- [ ] **Step 4: Create ADR-0002 documenting the gradual mypy strategy**

`docs/adr/0002-mypy-strict-gradual.md`:

```markdown
# 0002. Gradual mypy Strict Adoption

**Status:** accepted
**Date:** 2026-06-09

## Context

The codebase has 111 Python source files. 79 of them (71%) fail mypy `--strict` due to
missing type annotations and `Any` usage accumulated over organic development. Adding
type annotations to all 79 modules in one pass would be a large, risky change.

## Decision

Enable mypy strict mode globally. Grandfather the 79 failing modules via
`[[tool.mypy.overrides]]` with `ignore_errors = true`. New files are strict from day one.

The override list in `pyproject.toml` is the single source of truth for legacy debt.
To annotate a module: remove it from the list, run mypy, fix errors, commit.

## Consequences

- New code is strictly typed from the start — no regression.
- Legacy modules can be annotated incrementally without blocking other work.
- The override list is visible, countable, and shrinks monotonically.
- `ignore_errors = true` silences ALL mypy diagnostics in grandfathered modules, including potential real bugs. Accepted trade-off: fixing those modules is the remedy.
```

- [ ] **Step 5: Run full verification**

```bash
uv run mypy src/entirecontext/ && echo "mypy: PASS"
uv run ruff check . && echo "ruff: PASS"
uv run pytest && echo "pytest: PASS"
```

All three must pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml docs/adr/0002-mypy-strict-gradual.md
git commit -m "ci: add mypy strict type checking with grandfather overrides

Enable mypy strict globally. 79 legacy modules get ignore_errors=true
overrides (see ADR-0002). New files are strict from day one."
```

---

## Verification

1. `uv run mypy src/entirecontext/` — zero errors
2. `uv run ruff check .` — lint clean
3. `uv run pytest` — all tests pass
4. All four commits present with conventional format
5. New files: `.github/workflows/commit-lint.yml`, `docs/adr/README.md`, `docs/adr/0001-adr-process.md`, `docs/adr/0002-mypy-strict-gradual.md`
6. Modified files: `AGENTS.md`, `pyproject.toml`, `.github/workflows/ci.yml`
