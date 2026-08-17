---
schema: release-loop/v1
feature: spec-directory-policy
phase: done
phase_status: complete
started: 2026-08-16T08:12:56Z
updated: 2026-08-16T12:52:15Z
branch: orca/spec-directory-policy
base_branch: main
flags: []
spec: docs/specs/2026-08-16-spec-directory-policy-design.md
plan: docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md
retro: docs/retros/2026-08-16-spec-directory-policy-retro.md
design_approved: {by: user, at: 2026-08-16T08:20:00Z}
ship_approved: {by: user, at: 2026-08-16T08:54:00Z, conditions: "PR #224 CI green; merge approved"}
current_unit: null
ci_attempts: 2
review_rounds: 11
feedback_rounds: 0
comments_fixed: 20
comments_deferred: 1
pr: 224
merged: true
blocked_reason: null
final_action:
  kind: merge-to-base
  status: executed
  command: "gh pr merge 224 --squash --delete-branch; gh pr merge 225 --squash --delete-branch"
  marker: "PR #224 merged as 7e07ccb863c21901a2d3af56f274947c21d5b359; follow-up PR #225 merged as 72e0aa533ffd78463534333ef35ecdbafbe65914; tested tree identity verified; remote branches deleted via GitHub API"
  updated: 2026-08-16T12:13:52Z
---

## Log

- 2026-08-16T08:12:56Z init: Orca worktree `/Users/teslamint/orca/workspaces/entirecontext/spec-directory-policy` created from `71a1383`; branch `orca/spec-directory-policy` off `origin/main`.
- 2026-08-16T08:12:56Z final_action: predicted merge-to-base; no PR yet.
- 2026-08-16T08:12:56Z design: entering Design phase for the repository-wide spec directory policy.
- 2026-08-16T08:20:00Z design: user approved approach A — make `docs/specs/` the sole active Specification path and preserve historical archive paths.
- 2026-08-16T08:27:07Z design: approved spec committed at `69eadd1`; independent reviewer was unavailable due to provider rate limit, so self-review completed with placeholder scan and repository grounding checks. Entering Plan phase.
- 2026-08-16T08:28:31Z plan: implementation plan committed at `2bc31fb`; plan self-review passed placeholder, scope, and spec-coverage checks. Entering Implement phase U1.
- 2026-08-16T08:31:00Z implement/U1: companion ADR `0010` added with EC decision `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`; AGENTS.md policy and ROADMAP.md row updated. Commits `3440adb`, `244b732`, `8f5baac` contain only policy, ADR, and spec documentation changes.
- 2026-08-16T08:33:20Z review: independent reviewer unavailable due provider rate limit; self-review completed. Active traceability validation passed; `git diff --check 71a13830 HEAD` passed; `git diff --name-status 71a13830 HEAD -- docs/specs docs/superpowers/specs` returned only the new Spec as `A` and no `R`/`D`; allowed Conventional Commit subjects passed. No runtime tests were required because no runtime files changed. Entering Ship gate.
- 2026-08-16T08:48:20Z ship: user approved push and PR creation; branch pushed; PR #224 created.
- 2026-08-16T08:49:51Z ship/CI: Commit Lint, Tidy Pilot, CI (type-check, Python 3.12/3.13 tests, lint), and PR CodeQL workflows all completed successfully.
- 2026-08-16T08:50:14Z final_action: determined — `gh pr merge 224 --squash --delete-branch`. Preparation evidence only; first-hand merge approval still required.
- 2026-08-16T08:54:00Z ship: user approved PR #224 squash merge.
- 2026-08-16T08:55:54Z ship: PR #224 merged; merge SHA `7e07ccb863c21901a2d3af56f274947c21d5b359`; remote branch deleted via GitHub API.
- 2026-08-16T08:56:21Z retro: post-merge Codex review identified two valid P2 documentation defects in the plan's verification command: status assertion does not match ADR Markdown, and regex uses `\\s`, so it can report success without validating target paths. Follow-up fix required before archive.
- 2026-08-16T10:30:38Z retro/follow-up: PR #225 at `dc2cc1a` incorporates all twelve plan-checker findings, including tracked-only scanning, inline and multi-target labeled references, fenced-example exclusion, local Markdown-link destinations, file targets, and staged rename/delete detection. Exact Step 4 validation reports `68 checked; Markdown destinations: 5; bold references: 8; labels: 25`; all CI workflows pass. User elected to keep PR #225 open, so archive remains blocked pending a future merge decision.
- 2026-08-16T10:41:19Z retro/follow-up: PR #225 head `199554f` fixes three additional valid P2 findings: its Python guard now fails closed, the just-created untracked ADR participates in validation, and an unavailable external skill-contract path is no longer represented as a local `docs/...` pointer. The remaining P2 request to reject `M` status entries was rejected against the approved Specification: SC3 requires only no move or rename, measured explicitly as no `D`/`R`; in-place content edits are not prohibited. CI remains green; user keeps PR #225 open.
- 2026-08-16T11:26:17Z retro/follow-up: PR #225 head `cba9990` fixes the valid reference-style Markdown and checkout-escape P2 findings. The exact Step 4 check rejects both a missing reference-style destination and a local link resolving to `/etc/passwd`; CI is green. The prior `M`-status request remains rejected because the approved SC3 permits content edits and requires only no `D`/`R` move/rename entries. User keeps PR #225 open.
- 2026-08-16T11:32:42Z retro/correction: The prior rejection of the `M`-status P2 was incorrect. Spec §Scope/Out explicitly prohibits “Changing Specification content,” independently of SC3's no-`D`/`R` measurement. PR #225 head `29902ee` restores the Specification unchanged and fails Step 4 for `M`, `D`, or `R`; its exact check passes clean and all CI workflows are green. User keeps PR #225 open.
- 2026-08-16T12:11:45Z ship/follow-up preparation: `gh pr merge 225 --squash --delete-branch`; preparation evidence — first-hand consent still required. PR #225 head `29902ee` is `CLEAN` and `APPROVED`; all GitHub Actions checks pass. Fresh local verification: `uv run python -m pytest` → `2111 passed, 98 skipped, 1 warning` (the skipped MCP tests lack the optional `mcp` extra).
- 2026-08-16T12:13:52Z ship/follow-up: user authorized `gh pr merge 225 --squash --delete-branch`; GitHub merged PR #225 at `2026-08-16T12:12:09Z` as `72e0aa533ffd78463534333ef35ecdbafbe65914`. The initial command reported only a local worktree cleanup conflict after the remote merge. `git diff --quiet 29902ee83ed94cec74d09f5f029270ec5ef44bf7 FETCH_HEAD` confirmed the tested pre-merge tree is identical to merged `main`; remote `orca/fix-spec-policy-plan-check` was then deleted via GitHub API. The Orca-managed local worktree is preserved.
- 2026-08-16T12:52:15Z retro: all five declared Success Criteria remeasured and verified; facilitator accepted the fail-closed validation, whole-Spec contract, ledger reconciliation, and maturity carry-forward findings after one evidence re-probe.
- 2026-08-16T12:52:15Z retro/compound: created `docs/solutions/workflow-issues/make-verification-commands-fail-closed.md` and added `Fail-closed verification` to `CONCEPTS.md`.
- 2026-08-16T12:52:15Z retro/close: counters reconciled to 11 review submissions, 20 fixed comments, and 1 explicit deferred request; retro written to `docs/retros/2026-08-16-spec-directory-policy-retro.md`; phase complete.
- 2026-08-16T12:52:15Z retro/traceability: `main` could not resolve feature-worktree decision `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`; preserved the original row and ID in the main database, linked ADR/Spec/Plan/ROADMAP, recorded an accepted outcome, and verified `ec decision show` from `main`. Active references and approved Specification content remain unchanged; a temporary diagnostic duplicate was superseded by the original decision.
- 2026-08-16T12:52:15Z archive-destination: `.release-loop/archive/2026-08-16-spec-directory-policy/`; only the current loop ledger moved, leaving unrelated live evidence directories untouched.
