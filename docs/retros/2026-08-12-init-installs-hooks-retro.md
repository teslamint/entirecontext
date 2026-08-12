# Retro: ec init installs hooks

- Date: 2026-08-12
- Source: PR #205
- Spec: `docs/specs/2026-08-11-init-installs-hooks-design.md`
- Plan: `docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 1107 (1048 added + 59 removed) across 12 files |
| Commits | 27 branch commits, squash-merged as `7057657` |
| Review rounds | 8 processed; a 9th comment arrived 20 s before merge and was never processed |
| Comments (fixed / deferred) | 46 comments in 25 threads — 23 resolved / 2 unresolved (1 registered-deferred, 1 unseen) |
| CI failures | 0 (sampled head SHAs `01ea111`, `a52c91f`, `c6c2005`, `3ed0320`) |
| Duration (first spec commit → merge) | 3 h 05 m (`3332272` 05:50:14Z → 08:55:19Z) |
| Units planned / completed | 3 / 3 |

This retro is written one day after the merge. The release-loop ledger was never advanced
past round 5 and still recorded `merged: false`; every number above was re-derived from git
and the GitHub API rather than read from the ledger.

## Success criteria: measured vs declared

All measurements below were run fresh on merged `main` during this retro, not copied from
the PR body.

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | A fresh repo needs one command — `.claude/settings.local.json` holds all five EC hook types | `uv run pytest -k test_init_installs_hooks_by_default` | verified: passed | Met |
| 2 | All four installation actions move with their conditional structure intact | existence + run of the four named tests | verified: 3 of 4 named tests exist and pass; `test_init_agent_codex_writes_notify` does not exist (`rg -c` returns 0). Its assertion was merged into `test_init_agent_codex_skips_claude_and_git_hooks` (`tests/test_project_cmds.py:954`, `assert "codex-notify" in .codex/config.toml`), which passes | Partially met — the behavior is covered and green; the criterion names a test that was never written, the plan merged it (`plan:150` lists seven tests, not nine), and no artifact records the merge |
| 3 | `--no-hooks` restores the old behavior | `uv run pytest -k test_init_no_hooks_skips_installation` | verified: passed | Met |
| 4 | `ec enable` is unchanged — suites green AND 0 deleted/modified existing test lines | `uv run pytest` both suites; `git diff -U0 bf790bc 7057657 -- <both files> \| grep -c '^-[^-]'` | verified: 78 passed; the diff count is **24**, declared target 0 | Not met — four `TestGitHooksInstallation` tests were converted from fake `.git/hooks` mkdir to real `git init` repos under authorized scope expansion; no assertion weakened. Recorded in `docs/deviations/2026-08-11-git-hook-installation-safety.md:68`, not in the criterion |
| 5 | Installation logic exists once — four `rg -c` counts each return 1 | the four declared `rg -c` commands against `src/entirecontext/cli/project_cmds.py` | verified: 1 / 1 / 1 / 1 | Met |
| 6 | Failure is loud, not fatal | `uv run pytest -k test_init_hook_failure_warns_and_exits_zero` | verified: passed | Met |
| 7 | No documentation states `ec enable` is required after `ec init` | the spec's exact command: `rg -n 'Run .*ec enable' README.md docs/ --glob '!docs/specs/**'` | verified: **3 matches**, all inside `docs/plans/2026-08-11-001-…-plan.md`. Adding `--glob '!docs/plans/**'` — which the plan's own acceptance criterion has and the spec's does not — returns no match | Partially met — the user-facing intent holds, but the measurement was widened after the spec froze so that it would pass |

## Carry-forward from previous retro

Previous retro: `docs/retros/2026-07-29-pr-enrichment-consolidation-retro.md`, which registered
three items. All three are accounted for below.

| Item | Status | Evidence |
|---|---|---|
| Maturity 75 dogfooding with `ec context apply` (drift-based) | In progress | `get_dashboard_stats()` today: 64/100 Operational, breakdown `{capture 17/30, distill 17/25, retrieve 25/25, intervene 5/20}`. Prior retros recorded 61, so +3. Third consecutive retro In Progress (T6, T6-R1) |
| Post-squash archaeology convergence (event-based) | Not started | `ROADMAP.md:369` still `[ ]`; the triggering event — explicit repository-content export authorization — was never requested this cycle (T7) |
| General Git C-style escaped paths (event-based) | Not started | `_decode_git_quoted_path` at `core/archaeology.py:38` unchanged; last touching commit `a720c58` is a repo-wide ruff-format CI chore, not a behavior change (T7) |

- Previous doc shape: violations recorded as findings — the doc has an Interview Transcript
  section with a valid independence level (`self-checklist`, 0 rounds), but none of its four
  findings carries the template's required `**Cites**:` line (`rg -c "Cites"` returns 0),
  which its own predecessor `2026-07-21-blame-sha-lookup-complexity-retro.md` did carry at
  lines 63, 68, 75, 82. Recorded as a finding below, not silently repaired (T16).

## Interview Transcript

- Independence level: heterogeneous (GPT-5.5 via `codex exec -s read-only`, fresh context, artifacts only)
- Rounds used: 2 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---|---|---|---|---|---|
| T1 | 1 | 3 | Was SC2 met, including every specifically named test? | Partially met; `test_init_agent_codex_writes_notify` was never written, so the Codex notify path of `ec init` has no direct test coverage | `rg -c` returns 0; sibling `test_enable_codex_writes_user_notify:698` covers `enable` not `init` | accepted |
| T1c | 2 | 3 | (respondent-initiated correction to T1) | The "no direct test coverage" claim was false. The plan merged the assertion into `test_init_agent_codex_skips_claude_and_git_hooks`, which asserts `codex-notify` in `.codex/config.toml` and is green. True scope is narrower: the criterion names a nonexistent test and the merge is unrecorded | `plan:150` lists seven tests; `tests/test_project_cmds.py:944-959` | accepted |
| T2 | 1 | 3 | Was SC4 met, and how should the 24 changed existing test lines be classified? | Not met — 24 against a target of 0; authorized scope expansion converting four tests from fake `.git/hooks` to real `git init`; no assertion weakened, but the criterion as written is now false | diff count 24 vs 0; `docs/deviations/2026-08-11-git-hook-installation-safety.md` | accepted |
| T3 | 1 | 3 | Was SC7 met under the criterion's exact measurement? | Partially met — the spec's exact command returns 3 matches, all in the plan doc; the plan's acceptance added a `!docs/plans/**` glob the spec lacked, widening the measurement to make it pass | 3 matches; the glob difference between spec and plan | accepted |
| T4 | 1 | 5 | What nearly failed, what actually failed, and what evidence distinguishes them? | A P2 comment landed 20 s before merge and was never seen; reproduced today on merged main as a real defect — `_strip_ec_hooks` drops a user-owned matcher whose `hooks` list was already empty. Same data-loss class as `3756069221`, whose fix in `b3f667c` introduced this instance. Nothing caught it; the merge raced the reviewer | comments `3756532937` / `3756069221`; commit `b3f667c`; reproduction on main | accepted |
| T5 | 1 | 4 | How accurate was the final release-loop ledger? | It under-reports: 5 rounds / 15 fixed / 3 deferred recorded against 8 rounds, 46 comments, 25 threads, 23 resolved; two "permanent" deferrals were later fixed; `merged: false` persisted a full day after merge | ledger counters vs PR commits API and GraphQL threads; ROADMAP:348-349 | accepted |
| T6 | 1→2 | 4 | What is the dogfooding-maturity status, and what specifically blocks closure? | In progress, 64 vs 61 vs a 75 target; blocked by attribution, not effort — the metric rewards application events and release-loop work generates decisions far more readily | dashboard score, prior score, target | rejected: The measurements establish status and movement, but no dashboard component breakdown or event counts demonstrate that attribution—rather than another scoring component—is the blocker. |
| T6-R1 | 2 | 4 | Show the component breakdown and the events accounting for the 11-point gap | `{capture 17/30, distill 17/25, retrieve 25/25, intervene 5/20}`. Retrieve is at ceiling; intervene holds 15 unearned points and is the only component whose failures are rate thresholds — `applied_context_rate` 1% vs 10% required (−8) and `lesson_reuse_rate` 14% vs 20% required (−7). Capture and distill also leave 21 points, so intervene is not the only route to 75, but it is the binding measured constraint | `get_dashboard_stats()`; `core/dashboard.py:300-336` | accepted |
| T7 | 1 | 4 | What happened to the other two previous-retro carry-forwards? | Both Not started; both event-based with no triggering event this cycle | `ROADMAP.md:369` unchecked; `archaeology.py:38` unchanged; `a720c58` | accepted |
| T8 | 1 | 5 | What was the installed-tool staleness defect and why was it operationally significant? | PR #214's MD024 fix shipped to the repo but was inert in the environment that runs it; hooks call a uv-installed `ec`, not the checkout, so hook-driven regeneration silently reverted a shipped fix | PR #214; uv tool install path; observed reversal | accepted |
| T9 | 2 | 5 | What commit and regression test will correct `3756532937`? | No such commit exists — the defect is live on main. Fixing it inside a retrospective would put an unreviewed behavior change in a docs commit, so it is registered as a carry-forward with its regression test specified: a matcher with `"hooks": []` and no EC command must survive `ec init`, `ec enable`, and `ec disable` — all three, because `_strip_ec_hooks` is called from `project_cmds.py:529` and `:603` | reproduction on main; both call sites | accepted |
| T10 | 2 | 5 | What merge gate would detect an unread review, and does it close the race? | Re-query `reviewThreads` and the max `comments.created_at` immediately before merge, comparing against the last processed round. It would have caught this instance (6-minute window), but it narrows rather than closes: a comment can land between check and merge, and GitHub offers no compare-and-swap on merge. Only a server-side branch-protection rule requiring all threads resolved actually closes it | `3ed0320` 08:48:58Z → comment 08:54:59Z → merge 08:55:19Z | accepted |
| T11 | 2 | 3 | Where did the named test disappear from the planned work, and why did completion reporting still pass? | At the plan, not at implementation — `plan:150` lists seven tests where the spec listed nine. Unit acceptance was written against the plan's list (`plan:160`), never against the spec's, so no gate compares the two and the drop was invisible to U2 acceptance, branch review, and the ledger | `plan:150`, `plan:160`; spec test table | accepted |
| T12 | 2 | 3 | Who authorized the SC4 deviation, and why was the criterion not amended? | Ledger entry 2026-08-11T02:00:00Z records user authorization; the deviation doc's "Test-fixture change (SC4)" section (line 68) made it visible pre-merge. The criterion was not amended because the spec was `status: approved` and the convention freezes approved specs, recording departures separately — at the cost that SC4 reads as live and false | ledger entry; `docs/deviations/…:68` | accepted |
| T13 | 2 | 4 | Reconstruct the final ledger values and identify the failed write boundary | Rounds 5→8; 15/3 → 46 comments in 25 threads, 23 resolved; 2 of 3 deferrals actually fixed in `b3f667c`; `merged: false`→true. The boundary that failed is the ledger's own "write at the moment it happens, not batched at phase end" rule — everything after `e505997` went unwritten and the session ended before the real end. Detection: reconcile ledger against the PR API on resume, which is exactly what caught it today | PR commits API; GraphQL; `e505997`; ROADMAP:348-349 | accepted |
| T14 | 2 | 5 | Quantify the installed-tool staleness window | #214 merged 03:09:10Z; installed version before reinstall `0.14.0`; reinstall ~05:47Z; one known hook-driven regeneration inside the window (assessment `db44034f`, 03:35:07Z). Window ≈ 2 h 38 m. The pre-reinstall source revision is **unrecoverable** — I overwrote it with `uv tool install --force .` before capturing it, so I cannot state how long the install had been stale before #214. Versions were identical (`0.14.0`) on both sides, which is why nothing surfaced the drift | PR API; `ec --version`; `ec dashboard` | accepted |
| T15 | 2 | 5 | What provenance check would ensure hooks run the intended build? | Not a version comparison — both sides read `0.14.0`, so that check would have passed. Either make the checkout authoritative (hooks call `uv run ec`; costs startup time and breaks non-checkout users) or stamp the git SHA at build time and have `ec doctor` compare it against `git rev-parse HEAD`. Registering the second, because the first changes behavior for every user to fix a developer-machine problem | identical version strings from T14 | accepted |
| T16 | 2 | 4 | Why did the previous retro ship without `**Cites**:` lines? | Execution failure with a validation gap. The template did not change: `2026-07-21-…-retro.md` carries four `**Cites**:` lines, its successor carries zero. The gap is that Phase 8's pre-commit check validates only the Interview Transcript section's presence, while the findings-citation check lives in end-of-interview checks that are skipped at `self-checklist` with 0 rounds — the configuration that most needs the check is the one that omits it | `rg -c "Cites"`: 4 vs 0; retrospective SKILL.md Phase 8 | accepted |

## Findings

### What worked well

- **What happened**: The reviewer's data-loss finding `3756069221` (a Claude hook matcher entry losing sibling commands) was raised, deferred at the round-4 cap, and then fixed anyway in `b3f667c` before merge — with ROADMAP lines 348-349 updated to `[x]` to match.
  **Why**: The cap governs how many rounds a session processes, not whether a finding is legitimate. Treating the deferral as provisional rather than final let the fix land in the same PR that created the exposure.
  **How to apply**: When a cap defers a finding whose blast radius the current PR widened, re-open it before the merge gate rather than shipping the exposure and the registration together.
  **Cites**: T5; T13; Phase 2 data

- **What happened**: SC5's four `rg -c` counts each returned exactly 1 when re-run today, one day after merge, with no drift from the values claimed at merge time.
  **Why**: SC5 was written as four mechanical counts against a named file rather than as a judgment about duplication, so it stays measurable by anyone at any later time.
  **How to apply**: Prefer criteria that a stranger can re-run without reconstructing intent — the ones that survived this retro's fresh-measurement rule unchanged were exactly the mechanical ones.
  **Cites**: Phase 3 row 5

### What to improve

- **What happened**: A P2 review comment (`3756532937`) was posted at 08:54:59Z and the merge executed at 08:55:19Z — 20 seconds later. It was never read. Reproduced today against merged `main`: `_strip_ec_hooks` drops a user-owned matcher entry whose `hooks` list was already empty, because it cannot distinguish "became empty from our filtering" from "was already empty". The same reviewer's earlier finding `3756069221` produced the fix (`b3f667c`) that introduced this instance.
  **Why**: The merge gate's evidence was a review snapshot taken minutes earlier. Nothing re-checked for comments arriving between the last snapshot and the merge call, so a fix for one data-loss bug shipped with a second one in the same function.
  **How to apply**: Re-query review threads immediately before executing the merge, and treat a server-side "all threads resolved" branch-protection rule as the real fix — the client-side check narrows the window to a round-trip but cannot close it.
  **Cites**: T4; T10; T9

- **What happened**: SC2 names `test_init_agent_codex_writes_notify`; the plan's U2 step 2 enumerates seven tests and omits it, folding its assertion into a sibling. Every unit's acceptance criterion was written against the plan's list, never the spec's, so all three units reported complete with a declared test missing.
  **Why**: The plan is allowed to restructure the spec's tests, but no gate compares the plan's test enumeration against the spec's, and no artifact records a deliberate merge. The drop is indistinguishable from an omission.
  **How to apply**: Make the plan's test enumeration diff against the spec's an explicit planning-phase check, and require an inline note when the plan merges or drops a spec-named test.
  **Cites**: T11; T1c; Phase 3 row 2

- **What happened**: SC7's declared command returns 3 matches today. The plan's acceptance criterion for the same criterion carries an extra `--glob '!docs/plans/**'` that the spec's does not, and under the widened command it returns none.
  **Why**: The plan was written after the spec froze, and the plan author extended the measurement to exclude the document being written rather than flagging that the spec's command was under-specified.
  **How to apply**: When a plan needs a different measurement than the spec declared, that is a spec defect to surface, not a plan detail to absorb — the retro will re-run the spec's version.
  **Cites**: T3; Phase 3 row 7

- **What happened**: The release-loop ledger recorded 5 review rounds / 15 fixed / 3 deferred and `merged: false`; the record shows 8 processed rounds, 46 comments in 25 threads, two "permanent" deferrals subsequently fixed, and a merge that completed a full day before this retro read the file.
  **Why**: Everything after `e505997` — rounds 6-8, the deferral reversals, and the merge itself — happened after the last state write. The ledger's own rule is to write at the moment of the event; batching to what the session assumed was the end meant a record built to survive context loss did not survive it.
  **How to apply**: Reconcile the ledger against the PR API on every resume before trusting any field. A `phase: ship` record with `merged: false` against an API state of MERGED is stale by construction — that check is what produced this retro.
  **Cites**: T5; T13

- **What happened**: PR #214's MD024 fix was inert in the environment that runs it. The agent hooks invoke an `ec` from `~/.local/share/uv/tools/entirecontext`, whose `core/futures.py` predated #214, so hook-driven `auto_distill` regenerated `LESSONS.md` with the old code and silently reverted a shipped fix. Both sides reported version `0.14.0`.
  **Why**: The repository and the installed tool are two copies with no provenance link, and the version string is too coarse to distinguish them. A same-version drift is invisible to every check that exists.
  **How to apply**: Stamp the git SHA at build time and have `ec doctor` compare it against `git rev-parse HEAD` — a version comparison would have passed here.
  **Cites**: T8; T14; T15

### Process observations

- **What happened**: The heterogeneous facilitator rejected the dogfooding-maturity answer for asserting attribution without a component breakdown. Producing the breakdown (`retrieve 25/25`, `intervene 5/20`) confirmed the claim but also corrected it: capture and distill leave 21 further points, so intervene is the binding constraint, not the only route to 75.
  **Why**: The original answer was directionally right and evidentially empty. An independent facilitator has no way to distinguish a correct hunch from a rationalization, so it demands the measurement either way.
  **How to apply**: When a carry-forward is explained by a mechanism, measure the mechanism's component before writing the explanation into the retro.
  **Cites**: T6; T6-R1

- **What happened**: Probing T11 overturned an answer the facilitator had already accepted in round 1 — that the Codex notify path had no test coverage. Reading the plan and the test body showed the assertion lives in a sibling test and is green.
  **Why**: The round-1 answer was built from an existence check on a test name rather than from the behavior the name was standing in for. The probe about provenance forced the reading that corrected it.
  **How to apply**: When a named test is missing, check whether its assertion moved before reporting the coverage gap; and record the correction rather than letting the accepted answer stand.
  **Cites**: T1; T1c; T11

- **What happened**: The previous retro shipped with zero `**Cites**:` lines, while its own predecessor carried four. The retrospective skill's Phase 8 pre-commit check validates only that an Interview Transcript section exists; the findings-citation check lives in end-of-interview checks that a `self-checklist` run with 0 rounds skips.
  **Why**: The validation is attached to the interview rather than to the document, so the degraded mode that most needs a citation check is precisely the one that omits it.
  **How to apply**: Move the findings-citation check into the Phase 8 pre-commit gate so it runs regardless of independence level.
  **Cites**: T16

- **What happened**: The pre-reinstall source revision of the installed `ec` is unrecoverable, because the reinstall was run before the revision was captured.
  **Why**: The fix was applied as tree hygiene before the evidence value of the broken state was recognized.
  **How to apply**: When a defect is found in a mutable environment, capture its state before repairing it — the repair destroys the measurement.
  **Cites**: T14

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| `_strip_ec_hooks` drops pre-existing empty hook groups (reproduced on main; needs the three-command regression test) | edge-case | P2 | `ROADMAP.md` v0.16.0 |
| Re-query review threads immediately before merge; adopt an all-threads-resolved branch-protection rule as the closing fix | process | P2 | `ROADMAP.md` v0.16.0 |
| Plan-vs-spec test enumeration check in the planning phase | process | P3 | `ROADMAP.md` v0.16.0 |
| Build-SHA provenance stamp compared by `ec doctor` against `git rev-parse HEAD` | architecture | P3 | `ROADMAP.md` v0.16.0 |
| Maturity 75 dogfooding — intervene component (`applied_context_rate` 1%→10%, `lesson_reuse_rate` 14%→20%) | process | P3 | `ROADMAP.md` v0.15.0 carry-forward (ongoing, third cycle) |
| Post-squash archaeology convergence | process | P3 | `ROADMAP.md` v0.15.0 carry-forward |
| General Git C-style escaped paths | edge-case | P4 | `ROADMAP.md` v0.14.0/v0.15.0 carry-forward |

## Lessons

- **"A fix for a data-loss bug is the most likely place to find the next one."** `b3f667c` fixed a matcher entry losing sibling commands and, in the same function, introduced an entry-dropping bug for already-empty groups — caught only by a reviewer whose comment lost a 20-second race with the merge.
- **"Same version, different code is the drift no check catches."** The repo and the installed tool both reported `0.14.0` while one carried PR #214's fix and the other silently reverted it on every hook run.
- **"A plan may restructure the spec's tests, but nothing compares the two lists."** SC2's named test vanished at the plan, not at implementation, and all three units still reported complete because acceptance was written against the plan's enumeration.
- **"When the retro re-runs the spec's command instead of the plan's, widened measurements come back."** SC7 passed at merge under a glob the plan added and the spec never had.

## Compounding

- compound invocation: `Documentation complete — docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md`

Overlap against existing `docs/solutions/` was scored Low (0–1 of 5 dimensions matched
`workflow-issues/measure-archaeology-against-reachable-history.md`; both concern measurement
provenance but neither the problem, the referenced files, nor the fix overlap), so a new doc
was written rather than an update. `CONCEPTS.md` gained a **Tool provenance** cluster
(install provenance, same-version drift, executing copy). No discoverability edit was needed —
`CLAUDE.md` and `AGENTS.md` already point at `docs/solutions/` and `CONCEPTS.md`. No refresh
of an older doc is recommended.
