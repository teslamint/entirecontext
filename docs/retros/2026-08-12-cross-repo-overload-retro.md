# Retro: cross-repo @overload for include_warnings

- Date: 2026-08-12
- Source: PR #217
- Spec: `docs/specs/2026-08-12-cross-repo-overload-design.md`
- Plan: `docs/plans/2026-08-12-001-refactor-cross-repo-overload-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 961 (921 added + 40 removed) across 9 files; zero test files touched |
| Commits | 9 branch commits, merged as merge commit `99e1667` |
| Review rounds | 1 phase-gate round (4 lanes degraded to inline + codex, 0 findings) + 1 PR feedback round (5 comments) |
| Comments (fixed / deferred) | 5 comments — 1 fixed (ADR 0008, `41d38e5`) / 4 declined-or-replied with cited evidence; all 5 threads resolved |
| CI failures | 0 (two full green waves, head SHAs `28f2856` and `41d38e5`) |
| Duration (first spec commit → merge) | 3 h 37 m (`6879a07` 07:11:54Z → 10:49:14Z) |
| Units planned / completed | 4 / 4 |

The implementing session died between U1's commit and its ledger write; this cycle's resume
reconstructed state from `git log` (see T4) rather than trusting `current_unit: U1`.

## Success criteria: measured vs declared

All measurements below were run fresh in this retro's execution, in the merged-identical
worktree (`git diff origin/main HEAD` empty at measurement time).

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | The four casts are gone (package-wide zero) | `rg -c "\bcast\(" src/entirecontext/` | verified: no matches (rg exit 1) | Met |
| 2 | No unused import survives | `uv run ruff check .` | verified: All checks passed, exit 0 | Met |
| 3 | mypy remains at zero with the casts removed | `uv run mypy src/entirecontext/` | verified: Success: no issues found in 120 source files | Met |
| 4 | All eleven functions converted | `rg -c "^@overload"` and `rg -c "include_warnings: Literal"` on `core/cross_repo.py` | verified: 22 and 22 | Met |
| 5 | Runtime behavior unchanged | `uv run pytest -q` vs the 94291a4 baseline | verified: 2183 passed, 1 skipped in 177.12s — identical counts | Met |
| 6 | The overloads are load-bearing, not inert | non-vacuity check during implementation, recorded in the ledger with observed error text | verified: ledger 09:40 entry — deleting `cross_repo_rewind`'s stubs produced `mcp/tools/checkpoint.py:107: error: "None" object is not iterable [misc]`; restore → Success. Run in this session's execution | Met |

No measurement was weakened after the spec froze; SC1 was strengthened during design from a
per-file check to a package-wide zero (ledger design entry, 06:15).

## Carry-forward from previous retro

Previous retro: `docs/retros/2026-08-12-init-installs-hooks-retro.md`, seven items registered.
All seven are accounted for below.

| Item | Status | Evidence |
|---|---|---|
| `_strip_ec_hooks` drops pre-existing empty hook groups (edit-based) | Not started | `ROADMAP.md:356` still `[ ]`; `project_cmds.py` untouched by PR #217's diff |
| Re-query review threads immediately before merge (event-based) | In progress | Applied client-side this cycle: GraphQL re-fetch returned total=5 resolved=5 immediately before the merge call (ledger 11:20, T2). The registered closing fix — a server-side all-threads-resolved rule — was not adopted; `ROADMAP.md:357` stays open |
| Plan-vs-spec test enumeration check (event-based) | In progress | Applied manually: the plan's Carry-forward audit row for `ROADMAP.md:358` records all five spec-declared checks appearing in U4's acceptance with nothing merged or dropped. No durable planning-phase gate exists yet; the row stays open |
| Build-SHA provenance stamp (event-based) | Not started | `ROADMAP.md:359` still `[ ]`; no commit this cycle touches `ec doctor` or build config |
| Maturity 75 dogfooding — intervene component (drift-based) | In progress | `ec dashboard` today: **67/100 Operational**, breakdown `{capture 17, distill 25, retrieve 25, intervene 0}` vs previous `{17, 17, 25, 5}` — distill +8 to ceiling, intervene −5 to 0, net +3. Fourth consecutive cycle below 75 (T7) |
| Post-squash archaeology convergence (event-based) | Not started | The triggering event (repository-content export authorization) did not occur this cycle |
| General Git C-style escaped paths (event-based) | Not started | `core/archaeology.py` absent from PR #217's diff |

- Previous doc shape: conformant — Interview Transcript present with valid level
  (`heterogeneous`, 2 rounds), and every finding carries a `**Cites**:` line.

## Interview Transcript

- Independence level: self-checklist (both dispatch channels failed in-session: subagent spawn
  → `400 tools.34.custom.input_schema: Field required` deterministic 4/4; codex proxy → `401
  Invalid API key` on the facilitator dispatch, `codex exec` empty output on retry. Ladder
  exhausted to the terminal rung)
- Rounds used: 0 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---|---|---|---|---|---|
| T1 | — | 3 | Were all six SCs met under their exact declared measurements; was any weakened post-freeze? | All six Met, remeasured fresh (table above); SC6 via the ledger-recorded non-vacuity run from this session's execution. None weakened; SC1 strengthened pre-freeze | Phase 3 table; ledger 06:15, 09:40 | self-attested |
| T2 | — | 4 | Was ROADMAP:357's pre-merge re-query applied, and is the item closed? | Applied client-side (re-fetch → total=5 resolved=5, then merge); not closed — server-side rule not adopted | ledger 11:20; `ROADMAP.md:357` open | self-attested |
| T3 | — | 5 | What infrastructure failed during review, and what shows degradation preserved quality? | All 4 lane subagents died at spawn with the identical 400 schema error; degraded to inline AST comparison (ALL SIGNATURE SETS CONSISTENT), byte-level de-cast diff review, plus a heterogeneous codex pass → NO FINDINGS | ledger 10:00, 10:30 | self-attested |
| T4 | — | 5 | Was the previous retro's ledger-reconcile-on-resume lesson actually reused? | Yes: ledger read `current_unit: U1` while git had U1 committed (`1365d74`) and U2 complete-but-uncommitted; state was rebuilt from `git log`, U2 verified before committing, stale field corrected and retro-logged | ledger 09:20 entries | self-attested |
| T5 | — | 5 | What did the fresh run of plan U4 step 5's pyproject check show? | The rg matches the 2026-06-09 grandfathered `ignore_errors` block — including `entirecontext.core.cross_repo` itself (pyproject.toml:116) — equally true at baseline. The plan's literal wording was never satisfiable; its intent (nothing reintroduced) holds. The only plan check not pre-executed during planning was the one whose wording was false | ledger 09:40 deviation note; pyproject.toml:83-156 | self-attested |
| T6 | — | 5 | The U4 positional-rejection check first failed for an unrelated reason — what, and what did it enable? | `import-untyped`: no `py.typed` ships, so mypy skips the installed package; the check needed `MYPYPATH=src`. That discovery became the decisive evidence for declining review comment `3765653667` — external typed callers cannot consume the stubs at all. Recorded in ADR 0008 with a revisit condition | ledger 09:40; ADR 0008; reply `3765695877` | self-attested |
| T7 | — | 4 | Maturity status without asserting an unmeasured cause? | 67/100; distill +8 to ceiling, intervene −5 to 0, net +3 vs 64. No component-level cause measured for the intervene drop, so none claimed; intervene event counts named as the next measurement | `ec dashboard` output | self-attested |

## Findings

### What worked well

- **What happened**: The previous retro's "reconcile the ledger on every resume" lesson was
  applied verbatim: the stale `current_unit: U1` field was overridden by `git log` evidence,
  U2's complete-but-uncommitted edits were verified against their acceptance before being
  committed, and the correction was retro-logged rather than silently absorbed.
  **Why**: The lesson was written as a mechanical rule ("a `phase: ship` record with
  `merged: false` against an API state of MERGED is stale by construction"), so a resuming
  session could apply it without judgment.
  **How to apply**: Keep writing resume rules as evidence-comparison procedures, not advice.
  **Cites**: T4

- **What happened**: The pre-merge thread re-query registered by the previous retro ran this
  cycle: GraphQL re-fetch confirmed total=5 resolved=5 immediately before the merge call, and
  the merge followed with no unread-comment window incident.
  **Why**: The carry-forward was event-based and this cycle produced the event; the plan's
  audit had explicitly routed the item to the Ship phase so it was not rediscovered late.
  **How to apply**: Route event-based carry-forwards to the phase that owns the event at
  planning time, as this plan's Carry-forward audit did.
  **Cites**: T2; ledger 11:20

- **What happened**: The two U4 negative checks converted static-typing claims into measured
  evidence, and one of them paid twice: the positional-rejection check's incidental
  `import-untyped` failure (no `py.typed`) later became the decisive citation for declining
  the bool-fallback review comment.
  **Why**: A check that fails for an unexpected reason is a measurement of the environment;
  recording it verbatim in the ledger made it retrievable when the review needed it.
  **How to apply**: Record unexpected check failures with their full error text even after
  working around them — they are evidence, not noise.
  **Cites**: T6; T1

### What to improve

- **What happened**: Plan U4 step 5's wording — the pyproject rg "must return no
  `ignore_errors` context" — was never satisfiable: `entirecontext.core.cross_repo` has sat in
  the grandfathered override block since 2026-06-09, at baseline as much as at HEAD. Every
  other check in the plan had been pre-measured during design or planning; the single
  unexecuted one was the single false one.
  **Why**: The plan author wrote the check from intent ("nothing reintroduced") without
  running the command against the current tree, and no planning gate requires verification
  commands to be pre-executed.
  **How to apply**: Pre-execute every verification command in a plan against the current tree
  at authoring time; a check that has never run is a claim, not a check.
  **Cites**: T5

- **What happened**: Both independence channels died in one session: all four review-lane
  subagents failed at spawn with a deterministic harness schema error, and the codex proxy —
  which had served the heterogeneous review pass an hour earlier — returned 401 by the time
  the retro facilitator dispatch went out. The interview degraded to `self-checklist`.
  **Why**: Independence is an infrastructure dependency with no fallback beyond the local
  session; the ladder worked as designed but its terminal rung has no external check on
  self-assessment.
  **How to apply**: Treat repeated same-session dispatch failures as a signal to complete
  independent passes early while a channel is up — the review's codex pass succeeded only
  because it ran before the proxy died.
  **Cites**: T3; Interview header

### Process observations

- **What happened**: The intervene dogfooding component dropped 5 → 0 while distill rose to
  its 25-point ceiling; net maturity 64 → 67, a fourth consecutive cycle below the 75 target.
  No component-level cause for the intervene drop was measured this cycle.
  **Why**: This cycle's work was type-only refactoring with heavy ledger/dashboard activity
  (distill) and no context-application events (intervene); but that is an unmeasured
  hypothesis, not a finding.
  **How to apply**: Measure the intervene event counts (`applied_context_rate`,
  `lesson_reuse_rate` inputs) before the next retro asserts any cause.
  **Cites**: T7

- **What happened**: The Ship USER gate question timed out after 300 s with the user away; the
  loop fell to the prepare-only path (PR body written to a file, merge command persisted with
  the non-authorization marker, nothing pushed) and resumed cleanly when the user answered
  "merge까지" in-session.
  **Why**: The prepare-before-gate rule meant the timeout cost nothing: every outward command
  was staged and the gate re-resolved with first-hand consent.
  **How to apply**: Keep the prepare-only terminal state as the default answer to gate
  timeouts; never downgrade an unanswered USER gate to auto-approval.
  **Cites**: ledger 10:40, 10:50

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Pre-execute plan verification commands at authoring time (a never-run check is a claim) | process | P3 | `ROADMAP.md` v0.16.0 |
| Decide whether to ship `py.typed` (would expose the overload contract externally; ADR 0008 revisit condition) | architecture | P4 | `ROADMAP.md` v0.16.0 |
| Maturity 75 — measure intervene event counts before asserting a cause | process | P3 | `ROADMAP.md` (ongoing, fourth cycle) |

## Lessons

- **"The one check the plan never ran was the one whose wording was false."** Every
  pre-measured check in the plan held; U4 step 5, written from intent without execution,
  described a pyproject state that had not existed since 2026-06-09.
- **"An unexpected check failure is a measurement of the environment — record it verbatim."**
  The `import-untyped` miss revealed the package ships no `py.typed`, which later became the
  decisive evidence for declining a P2 review comment.
- **"Independence is infrastructure: complete independent passes while the channel is up."**
  The codex review pass succeeded an hour before the same proxy returned 401 to the retro
  facilitator; the subagent path was dead the whole session.

## Compounding

- compound invocation: not attempted — the pre-execute-plan-checks lesson is already carried
  as a ROADMAP row and the py.typed condition lives in ADR 0008; neither needs a
  `docs/solutions/` doc this cycle, and forcing one would duplicate the tracker entries.
