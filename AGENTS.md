# Repository Guidelines

CLAUDE.md and AGENTS.md are independently maintained. CLAUDE.md carries compact project reference and review principles; AGENTS.md carries workflow policies.

After `uv sync` that touches `mcp/` or `core/decisions.py`, restart Claude Code — the stdio MCP server does not auto-reload.

## Test

Tests use real git repos via fixtures (`git_repo`, `ec_repo`, `ec_db`, `isolated_global_db`). External deps are isolated with `monkeypatch`. See `tests/conftest.py`.

When modifying a source module, always run the existing tests for that module before committing — not just newly written tests. Test verification scope must match the change scope.

## Commit & Pull Request Guidelines
- Conventional Commit prefixes: `feat(...)`, `fix(...)`, `refactor(...)`, `docs(...)`.
- Keep each commit focused on one change area with scope (example: `feat(search): add hybrid reranking`).
- PRs should include: purpose, key changes, test evidence (commands + results), and linked issue/task.
- Include CLI output snippets or screenshots when user-facing command behavior changes.
- Decision traceability chain: Spec (`docs/superpowers/plans/`) → ADR (`docs/adr/`) → Plan → Code. PRs that change behavior should reference the governing ADR or EC decision.

## Dogfooding Workflow

This project's own features should be actively used during development sessions.

### When to use what

| Phase | Action |
|---|---|
| Before work | `ec search` / `ec_search` — find past work on the topic |
| Before work | `ec_lessons` — scan lessons for applicable guidance |
| During work | `ec checkpoint create` — snapshot progress at meaningful milestones |
| After work | `ec futures assess` / `ec_assess_create` — evaluate changes against roadmap |
| After work | `ec_feedback` — record agree/disagree on prior assessments |
| Debugging | `ec_related` with file paths — find turns that touched the area |
| Cross-session | `ec_session_context` — get the previous session's summary |

## Measure-First Principle

Before implementing any feature or behavior change:

1. Define measurable success criteria (metric name, target value, measurement method).
2. Verify the measurement infrastructure exists and works (dashboard query, test assertion, CLI command).
3. If measurement infra is missing, build it first as a separate commit/PR.
4. After implementation, verify the metric moved as expected.

Skip only for pure documentation, config, or CI-only changes. State when skipped and why.

Rationale: v0.8.1 showed that building features without pre-existing measurement leads to formula bugs that ship undetected across multiple releases.

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

## Decision and Lesson Reuse Policy

Agents working in this repository must use stored decisions and lessons as part of the development workflow, not optional background context.

### When to check
Before non-trivial analysis or implementation when the task:
- changes behavior, policy, schema, or interfaces
- touches retrieval, ranking, sync, session lifecycle, hooks, dashboard, assessments, telemetry, or decision memory
- implements or reinterprets a roadmap item
- revisits an area with repeated bugs, repeated refactors, or prior design discussion
- involves debugging a regression or issue structurally similar to a previously assessed change

### Required workflow
1. Retrieve relevant decisions before implementation.
2. Read the selected decisions before proposing or applying changes.
3. Scan lessons for applicable guidance, especially when debugging regressions or working in areas with prior narrow verdicts.
4. Prefer fresh decisions by default.
5. Do not silently apply stale, contradicted, or superseded decisions.
6. If decisions conflict, surface the conflict explicitly.
7. If no relevant decision exists, say that clearly before proceeding.
8. If a decision materially informed the work, record that usage.
9. After the work completes, record whether the result confirmed, contradicted, refined, or replaced the decision.
10. If the work creates a stable new policy or architectural judgment, create or update a decision record.
11. If assessed work completed, provide agree/disagree feedback with a reason so lessons accumulate.

### Retrieval paths
- MCP: `ec_decision_related`, `ec_decision_get`, `ec_decision_list`, `ec_lessons`, `ec_feedback`
- CLI fallback: `ec decision list`, `ec decision show`, `ec futures lessons`, `ec futures feedback`
- Context application: `ec_context_apply(...)` / `ec context ...`
- Decision outcome: `ec_decision_outcome(...)` / corresponding CLI command

### MCP Call Discipline
- Treat tool schema as strict; do not infer argument shapes from descriptions alone.
- For repo filters, prefer `repos` as a list even when targeting a single repo.
- Prefer `search_type="hybrid"` for natural-language queries before falling back to FTS.
- On schema/parser errors, stop and correct argument shape before retrying.

### Minimum behavior
For non-trivial tasks, do not skip decision and lesson check unless the user explicitly asks. State when skipped and why.

### Final reporting
When decisions or lessons were relevant, include:
- which decisions were considered, applied, rejected, or treated as stale
- whether completed work confirmed, contradicted, superseded, or extended prior guidance
- which lessons were reviewed and whether any influenced the approach
- which assessments received feedback during this task

### Interpretation rule
Stored decisions are inputs to judgment, not blind rules. Verify fit against current code, task, and user intent.

## Hook-Driven Automation
- **SessionStart** → creates/resumes session tracking
- **UserPromptSubmit** → captures turn; **injects top-k relevant decisions** (Proactive Decision Injection, v0.7.0+)
- **PostToolUse** → tracks tools and files touched
- **Stop** → captures assistant response summary
- **SessionEnd** → generates summaries, triggers auto-sync/embed/distill
- **PostCommit** (git hook) → creates checkpoint on each commit
- **pre-push** (git hook) → triggers `ec sync --if-enabled`

### Proactive Memory Reuse (v0.7.0+)

The `UserPromptSubmit` hook is the default delivery channel for relevant decisions. Relevant decisions appear automatically as `<system-reminder>` context tagged "UserPromptSubmit hook additional context:". Use explicit MCP/CLI retrieval only when:
- you need decisions beyond the injected top-k
- you need to filter by staleness, file, or outcome
- PDI was skipped (no session, capture disabled, or timeout exceeded)
- you want to record usage or outcomes

## Adding New CLI Commands
1. Create `cli/<name>_cmds.py` with `@app.command()` decorators
2. Import and register in `cli/__init__.py`
3. Keep business logic in `core/` — CLI layer handles args/output only
4. Add corresponding MCP tool in `mcp/server.py` if the feature is useful for in-session queries
5. Update `CLAUDE.md` architecture section if new module is added

## Code Review Principles

Principles for automated code review (CI and agent review alike). These guide the reviewer, not the code author.

### Grounding
- Every finding must cite specific code location (file:line)
- Do not present inferences as facts; label hypotheses clearly
- Ground claims in repository context or tool outputs, not assumptions

### Confidence Threshold
- Only submit a finding if you can point to a specific code path that causes the issue
- Do not submit findings based on pattern-matching alone without tracing the actual call or data flow
- If confidence is low, omit the finding rather than labeling it a "suggestion"

### Severity
- Categorize findings: Critical (must fix) / Important (should fix) / Suggestion
- Critical: correctness bugs, data loss, security vulnerabilities
- Important: missing error handling, contract mismatches between docs and code, edge cases
- Suggestion: readability, naming, minor optimization

### Depth
- After first plausible issue, check second-order failures: empty-state handling, retries, stale state, rollback paths
- Verify contract consistency: if CLAUDE.md, docstrings, or specs state X, code must match

### False Positive Avoidance
- Do not flag pre-existing issues unrelated to the change
- Do not flag issues ruff, pytest, or other configured CI steps already enforce
- Do not flag intentional behavior changes that align with the PR's stated purpose
- Do not flag style preferences not codified in this file or ruff config

### Scope
- Review only the changed code and its immediate blast radius
- Do not suggest unrelated refactors or cleanup
