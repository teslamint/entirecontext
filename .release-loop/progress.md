---
schema: release-loop/v1
feature: init-installs-hooks
phase: design
phase_status: in_progress
started: 2026-08-11T00:00:00Z
updated: 2026-08-11T00:00:00Z
branch: feat/init-installs-hooks
base_branch: main
flags: []
spec: docs/specs/2026-08-11-init-installs-hooks-design.md
plan: null
retro: null
design_approved: null
plan_approved: null
ship_approved: null
current_unit: null
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
