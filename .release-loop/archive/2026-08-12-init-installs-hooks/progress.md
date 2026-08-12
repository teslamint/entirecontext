---
schema: release-loop/v1
feature: init-installs-hooks
phase: done
phase_status: complete
started: 2026-08-11T00:00:00Z
updated: 2026-08-12T00:00:00Z
branch: feat/init-installs-hooks
base_branch: main
flags: []
spec: docs/specs/2026-08-11-init-installs-hooks-design.md
plan: docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md
retro: docs/retros/2026-08-12-init-installs-hooks-retro.md
design_approved: {by: user, at: 2026-08-11T00:10:00Z}
plan_approved: {by: user, at: 2026-08-11T00:30:00Z}
ship_approved: {by: user, at: 2026-08-11T08:55:19Z}
current_unit: null
ci_attempts: 2
review_rounds: 5
feedback_rounds: 4
comments_fixed: 15
comments_deferred: 3
pr: "https://github.com/teslamint/entirecontext/pull/205"
merged: true
blocked_reason: null
final_action:
  kind: merge-to-base
  command: "gh pr merge 205 --squash --delete-branch"
  status: executed
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
- 2026-08-11T01:20:00Z implement/U3: README quick start, CLI table, MCP section, and hook section updated; docs/spec.md 176-186 and the manual's getting-started, command description, and command list sections updated. SC7 grep clean. Committed at `01ea111`. U3 complete. Plan U3 step 6's "command list near lines 443-448" was inspected and left unchanged: section 8.1 is a bare list of command names and both commands survive, so there is nothing to change there.
- 2026-08-11T01:25:00Z review: final branch review (advisor) returned Spec PASS + Quality PASS. Scenario delivery verified on the actual branch — S1 and S2 walked end to end in isolated-HOME temp repos (one command installs 5 Claude hooks + 2 git hooks + MCP entry; `--no-hooks` leaves repo and home untouched while still creating the DB), S3 by SC4=0 with the existing suite unmodified, S4/S5/S6 by their 9 named tests. SC1-SC7 all measured: SC4=0, SC5 greps all 1, SC7 no match, full suite 2136 passed / 1 skipped. No cross-unit defects. MinorFindings carried forward unchanged; none block merge.
- 2026-08-11T01:25:00Z review→ship: entering Ship. Note for the ship gate: local `main` is 1 commit (`bf790bc`, the release-loop archive chore) ahead of origin/main and this branch contains it, so main must be pushed first or the PR diff will carry the archive files.
- 2026-08-11T01:35:00Z ship: `main` pushed (`5701996..bf790bc`) so the archive chore lands separately; branch pushed and PR #205 created. PR diff contains only this change (8 files), no archive files.
- 2026-08-11T01:35:00Z final_action: determined — `gh pr merge 205 --squash --delete-branch`. Preparation evidence — first-hand consent still required.
- 2026-08-11T02:00:00Z ship/CI: all checks green on `01ea111` (first run) and again on `a52c91f`. Residual: CodeRabbit reported `Review rate limited` on the second run, so it did not re-review the round-1 fixes; claude-review, CodeQL, GitGuardian, lint, type-check, and both test matrices did.
- 2026-08-11T02:00:00Z ship/feedback round 1: 6 comments, 6 fixed, 0 deferred. `3755755781`+`3755755779`+`3755765254` in `485bb73`; `3755765241`+`3755765246`+`3755765251` in `a52c91f`. Two P1/P2 git-hook defects were reproduced before fixing (foreign hook destroyed by `ec init`; hooks dir unresolved in a linked worktree). Both predate this change but its blast radius widened them. Scope expansion authorized by the user and recorded in `docs/deviations/2026-08-11-git-hook-installation-safety.md`. ADR 0005 added per AGENTS.md public-interface-contract policy.
- 2026-08-11T02:00:00Z ship: SC4 deliberately deviated — 4 `TestGitHooksInstallation` tests changed from fake `.git/hooks` mkdir to real `git init`; no assertion weakened. Recorded in the deviation doc and the PR.
- 2026-08-11T02:00:00Z ship: full suite 2146 passed / 1 skipped on `79aa293`. PR state MERGEABLE / CLEAN / APPROVED, 6 of 6 threads resolved. final_action unchanged and still determined. Awaiting USER merge gate.
- 2026-08-11T02:10:00Z ship: CI green on first run (12 checks). Review round 1 fetched via API: 6 comments (CodeRabbit 2, Codex connector 4), one a duplicate. All 6 verified against code before acting, all 6 fixed, replied, and resolved; re-fetched from the API afterward and confirmed 0 unresolved.
- 2026-08-11T02:10:00Z ship: scope expanded with explicit user authorization to cover two pre-existing `_install_git_hooks` defects whose blast radius this change widened — foreign git hooks were overwritten (data loss, reproduced) and the hooks dir was unresolvable in a linked worktree (silent no-op, reproduced). Both fixed in `a52c91f`; recorded in `docs/deviations/2026-08-11-git-hook-installation-safety.md` because they also change `ec enable`. ADR 0005 added per AGENTS.md.
- 2026-08-11T02:10:00Z ship: SC4 no longer holds — 4 TestGitHooksInstallation tests changed from fake `.git` dirs to real `git init` repos. Fixture upgrade, no assertion weakened. Stated in the deviation record and the PR body rather than quietly restated.
- 2026-08-11T02:30:00Z ship/feedback round 2: 3 comments (`3755884180` P1, `3755884172` P2, `3755884176` P2), all fixed in `42aa5af`. The P1 was self-inflicted: round 1's hooks-directory resolution made `ec` follow `core.hooksPath`, which the pre-change code never did, so two repos sharing a hooks directory would have `ec disable` in either delete the other's hooks. Closed by refusing to manage hooks when that config is set. advisor consulted before choosing the approach and caught a trap: quoting the Claude settings command would break `_is_ec_hook`'s substring match, so quoting is applied to git hook scripts only.
- 2026-08-11T02:45:00Z ship/feedback round 3: 3 comments. `3755985910` (P2, `--no-hooks` must supersede `--agent`) and `3755985915` (P2, exec bit on owned hooks) fixed in `bbc49b5`. `3755985909` (P1, spec belongs in `docs/superpowers/specs/`) deferred — real drift between AGENTS.md and the last four specs, which all landed in `docs/specs/`; moving only this one would not resolve it.
- 2026-08-11T03:00:00Z ship/feedback round 4 (cap): 3 comments. `3756069218` (P2, empty `core.hooksPath` read as unset — a defect in round 2's own code) fixed in `79aa293`. `3756069221` (P1, Claude hook group loses sibling commands) and `3756069214` (P2, unquoted Claude hook commands) deferred at the cap: both are pre-existing `ec enable` behavior and both need `_is_ec_hook`'s matching contract changed, which carries a migration question for installed configs. All 3 deferrals plus the 2 round-1 asymmetries registered in ROADMAP.md.
- 2026-08-11T03:10:00Z ship/feedback round 5: 3 CodeRabbit doc-quality comments on my own artifacts — inconsistent test counts across documents, broken numbering in the deviation doc (`1,2,4,5,6,7,3` under a heading claiming three items), and ROADMAP carry-forwards lacking a target version. All three valid; fixed rather than deferred since they are documentation hygiene on this PR's own output.
- 2026-08-11T03:10:00Z ship: full suite 2146 passed / 1 skipped on `79aa293`. 15 comments fixed, 3 deferred with rationale in ROADMAP and the PR body.
- 2026-08-12T00:00:00Z retro→done: retrospective committed at `1c955f6` (`docs/retros/2026-08-12-init-installs-hooks-retro.md`). 4 of 7 success criteria Met, 2 Partially met, 1 Not met, all re-measured fresh. Heterogeneous facilitator (GPT-5.5 via `codex exec`, fresh context), 2 of 5 rounds, all exchanges finally accepted after one rejection and one respondent-initiated correction. Four new carry-forwards registered in ROADMAP v0.16.0; compound wrote `docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md` and seeded a Tool provenance cluster in `CONCEPTS.md`. Plan flipped to `status: done` / `completed_by: 705765762c13fe3befbd484ed7a752ae6bdecfdf`.
- 2026-08-12T00:00:00Z archive-destination: .release-loop/archive/2026-08-12-init-installs-hooks
- 2026-08-12T00:00:00Z reconstruction: this record was found live at `phase: ship / in_progress` with `merged: false`, but git and the GitHub API both show PR #205 merged at 2026-08-11T08:55:19Z as squash commit `7057657` with `feat/init-installs-hooks` deleted. The ship phase completed and the record was never advanced — the session ended between the merge and the state write. State rebuilt from that evidence per the resume rule (progress.md + git log outrank conversation memory); `final_action` flipped to `executed`, `ship_approved` stamped at the merge time, `merged: true`. Entering Retro.
- 2026-08-12T00:00:00Z retro/prereq: the working tree carried an uncommitted LESSONS.md regression — every heading had lost the assessment-ID suffix that PR #214 added to fix MD024. Root cause is not this repo's source but the `ec` tool install: `~/.local/share/uv/tools/entirecontext` predated #214, so hook-driven `auto_distill` regenerated LESSONS.md with the old code and silently reverted the shipped fix. Reinstalled from the checkout (`uv tool install --force .`), verified `futures.py:176` now carries the suffix in the installed package, and reverted the file. Recorded as a retro finding, not a side fix.
- 2026-08-11T03:25:00Z ship: rounds 2-5 committed (`42aa5af`, `bbc49b5`, `79aa293`, `c6c2005`). CI green on `c6c2005`. 18 threads total, 15 resolved, 3 left open by design — the deferred findings, each with a reply naming the cap and the ROADMAP v0.16.0 registration. PR MERGEABLE / CLEAN / APPROVED. final_action unchanged and still determined. Awaiting USER merge gate.
