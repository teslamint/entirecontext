---
schema: release-loop/v1
feature: init-installs-hooks
phase: implement
phase_status: in_progress
started: 2026-08-11T00:00:00Z
updated: 2026-08-11T00:00:00Z
branch: feat/init-installs-hooks
base_branch: main
flags: []
spec: docs/specs/2026-08-11-init-installs-hooks-design.md
plan: docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md
retro: null
design_approved: {by: user, at: 2026-08-11T00:10:00Z}
plan_approved: {by: user, at: 2026-08-11T00:30:00Z}
ship_approved: null
current_unit: U3
ci_attempts: 0
review_rounds: 0
feedback_rounds: 0
comments_fixed: 0
comments_deferred: 0
pr: null
merged: false
blocked_reason: null
final_action:
  kind: merge-to-base
  command: null
  status: predicted
---

## Log

- 2026-08-11T00:00:00Z init: worktree `.worktrees/init-installs-hooks` created from `bf790bc`; branch `feat/init-installs-hooks` off `main`.
- 2026-08-11T00:00:00Z final_action: predicted merge-to-base; no PR yet.
- 2026-08-11T00:00:00Z decisions: `ec_decision_related` returned 10 records; none on-point for the init/enable command-surface split (top hits cover hook `--type` plumbing, decision-hook config gating, MCP registration parity). Proceeding without an applicable prior decision (AGENTS.md rule 7).
- 2026-08-11T00:00:00Z design: entering Design phase.
- 2026-08-11T00:00:00Z design: 3 scope questions answered by user (move all four install actions; keep `ec enable` as repair path; install by default with `--no-hooks` opt-out).
- 2026-08-11T00:00:00Z design: spec draft committed at `3332272`. Empirical grounding caught 2 falsified claims pre-review (`rg -c mcpServers` returns 2 not 1; `mock_git_root` is a `@patch` arg, not a conftest fixture) — both fixed.
- 2026-08-11T00:00:00Z design: advisor review found 1 material defect — the Architecture diagram flattened `enable()`'s conditional nesting (git hooks are claude-only; MCP registration is unconditional). Fixed in Architecture + S4 + test table + SC2; 2 hygiene items also applied. Awaiting USER approval gate.
- 2026-08-11T00:10:00Z design→plan: spec approved by user; `status: approved` committed. Entering Plan phase.
- 2026-08-11T00:25:00Z plan: draft committed at `7189ea4`; validator exit 0. advisor review re-derived the carry-forward audit (14 open / 1 fired / 0 unobservable — matches) and found 1 blocking defect: tests written as direct `project_cmds.init(...)` calls would hit Typer's truthy `OptionInfo` defaults. Corrected to `runner.invoke(app, [...])`, this file's universal convention; per-test expected-failure reasons corrected. Committed at `d941f48`.
- 2026-08-11T00:30:00Z plan→implement: plan approved by user; `status: approved` + `body_seal ecefd1bb` committed. Starting U1.
- 2026-08-11T00:40:00Z implement/U1: characterization test passed against pre-refactor code, then `_install_integrations()` extracted. 37/37 tests pass (test_project_cmds + test_e2e_hooks_install), ruff check clean, 0 existing test lines edited. Committed at `16d3d1a`. U1 complete.
- 2026-08-11T00:40:00Z implement: executing inline serially, not via subagents — this session is instructed not to use the Agent tool. Review passes use the `advisor` tool (separate stronger reviewer, not self-approval) at the U1+U2 code boundary and again for the final branch review, rather than once per unit.
- 2026-08-11T01:00:00Z implement/U2: 8 new init tests written failing (4 with exit_code 2 / "No such option", 3 on file assertions, 1 on OSError propagation), then `init()` implemented with `--no-hooks`/`--no-git-hooks`/`--agent` and warn-and-exit-0 degradation. 45/45 in scope, full suite 2136 passed / 1 skipped, ruff clean. SC5 greps all return 1. Committed at `2a1f696`. U2 complete.
- 2026-08-11T01:05:00Z review (U1+U2): advisor returned Spec PASS + Quality PASS with one verification gap to close first — no one had checked whether tests outside the two grepped files invoke `ec init`, which now writes `~/.claude/settings.json`; such a test would pollute the real home while still passing. Closed: `rg` over tests/ and scripts/ found 0 CLI `init` invocations (all `"init"` hits are `git init` subprocesses), and the real `~/.claude/settings.json` mtime (14:34) predates the full-suite run (~15:05-15:15). No contamination.
- MinorFindings: (1) `ec init --no-hooks --agent bogus` exits 2 because `_parse_agent_option` runs first; consistent with `enable`'s value validation and not the combination-rejection the spec forbids — interpretation recorded, no code change. (2) SC4's mechanical no-deleted-test-lines check against `main` deferred to the final branch review. (3) A future test invoking `["init"]` without HOME isolation would write the real home; zero such tests exist today, so nothing to fix now.
