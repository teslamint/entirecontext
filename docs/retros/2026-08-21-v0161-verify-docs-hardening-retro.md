# Retro: v0.16.1 verify-docs edge-case hardening

- Date: 2026-08-21
- Source: PR #235 (merge `902d4a4`), PR #236 (release `390c5eb`)
- Spec: none (reactive bug-fix driven by automated review comments)

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 14 insertions, 5 deletions across 3 non-test files |
| Test lines | 33 insertions in 1 test file |
| Commits | 4 (2 fixes + 1 merge + 1 release bump) |
| Review rounds | 4 review submissions on PR #235 (2 CodeRabbit, 2 claude[bot]); 6 total comment threads |
| Comments (fixed / deferred) | 5 fixed (URI encoding, absolute path rejection, exception broadening, doc correction, review thread resolution) / 1 deferred (superseded-status orphan — pre-existing design, not introduced by this PR) |
| CI failures | 0 on all required checks; 15/15 passed on PR #236 |
| Duration (first fix commit -> v0.16.1 tag) | ~2 h (`e6b8e1b` 2026-08-20 → `v0.16.1` tag 2026-08-20) |

## Success criteria: measured vs declared

No spec exists for this work. It was reactive bug-fix driven by 6 automated
review comments (3 CodeRabbit, 3 claude[bot]) on PR #235. Success criteria
were not declared before implementation. This section is skipped per protocol.

## Carry-forward from previous retro

Previous retro: `docs/retros/2026-08-19-mcp-sdk-2-migration-retro.md`.
Pre-schema format — no `Carry-forward items registered` table.

| Item | Trigger class | Status | Evidence |
|---|---|---|---|
| Close PR #222 (dependabot bump superseded by PR #233) | event-based | **Done** | `gh pr view 222` → state CLOSED |
| `_FakeMCP` test helper rename | edit-based | Not started | `rg _FakeMCP tests/` → 4 occurrences in `tests/test_contract_sync.py`; LOW priority, no functional impact |

- Reconciliation: registered 0, accounted for 2 — degraded: previous retro has no registration table
- Previous doc shape: pre-schema, exempt

**Process observation:** The 2026-08-17 retro (`pr-226-ordered-reliability-backlog-retro.md`)
registered 5 carry-forward items in a proper table. The two subsequent 2026-08-19
retros (mcp-serve-silent-failure, mcp-sdk-2-migration) are both pre-schema and
did not reconcile those 5 items, creating a 2-cycle reconciliation gap. Key items
from that table:

| Item (from 2026-08-17) | Current status |
|---|---|
| Persist feature-worktree decisions before loop archival | **Done** — `ec decision verify-docs` + `--promote-from` shipped in v0.16.0; ROADMAP.md:364 |
| Decide whether to ship `py.typed` | Not started — ADR 0019 defers to stable; ROADMAP.md:363 |
| Reach maturity 75 | In progress — last measured 71 (2026-08-17) |
| P2 review reply discipline | Not started — no sibling doc created |
| Plan schema adoption | Not started — no new Plans authored since |

## Interview Transcript

- Independence level: same-model fresh-context
- Rounds used: 2 (max 5)
- Tools: code-reviewer subagent (fresh context, no working conversation)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---|---|---|---|---|---|
| T1 | 1 | 4 | Are previous carry-forward items reconciled? | PR #222 CLOSED, `_FakeMCP` 4 occurrences remain, 2-cycle reconciliation gap from 2026-08-17 retro | `gh pr view 222` → CLOSED; `rg _FakeMCP tests/` → 4 hits in test_contract_sync.py; 2026-08-19 retros have no reconciliation section | accepted — PR #222 CLOSED confirmed, _FakeMCP 4 hits confirmed, 2-cycle gap verified against both 2026-08-19 retro docs |
| T2 | 1 | 2 | Do fixes trace to review comments? | 6 comments (3 CodeRabbit + 3 claude[bot]), b9d1481 fixed doc+CLI, e6b8e1b fixed URI/path/exception, superseded-status resolved as pre-existing | `gh api repos/.../pulls/235/comments` → 6 review comments matching claimed split; commit diffs map to comment subjects | accepted — 6 comments (3+3), 2 commits map to them, superseded-status resolution plausible |
| T3 | 1 | 5 | Was tag-before-merge controlled or accidental? | Accidental — direct push blocked by GH006, workaround via release branch + PR #236 | `git log v0.16.0..v0.16.1`; `docs/RELEASE.md` has no branch-protection mention | accepted — GH006 forced workaround, RELEASE.md gap confirmed, risk assessment sound |
| T4 | 1 | 5 | What almost went wrong? | Branch protection rejection; RELEASE.md assumes push availability, no fallback | Extension of T3 evidence | accepted — RELEASE.md assumes push availability, no fallback documented |
| T5 | 2 | 4 | 2026-08-17 retro's 5 registered items: current status? RELEASE.md checklist applies to patch releases? | 1 Done (verify-docs), 1 In progress (maturity 75), 3 Not started (py.typed, P2 review discipline, plan schema). Patch release had no planning phase; carry-forward review step was skipped. | ROADMAP.md:363-364, 383; ADR 0019; no new Plans authored since 2026-08-17 | accepted — ROADMAP.md:363-364, 383 verified; 5 items status accurate (py.typed ROADMAP [x] = defer decision, not shipping); patch-release carry-forward exemption registered as open question |
| T6 | 2 | 3 | b9d1481 mixes doc + CLI change — same scope? | Both respond to CodeRabbit PR #235 feedback. Commit message lists 3 items explicitly. Split is reviewer-response vs. proactive hardening (e6b8e1b). 2-line doc + 3-line CLI fix; splitting adds friction without safety benefit. | `git show b9d1481 --stat` → 2 files; commit message enumerates doc, cli, skip | accepted — 7-line diff verified (4 doc + 3 CLI); commit message enumerates all 3 items; reviewer-response vs proactive-hardening is a legitimate commit boundary |

## Findings

### What worked well

- **What happened**: The 5-lane code review (correctness, security, tests,
  architecture, standards) completed in ~2 minutes of wall-clock with a
  `clean` verdict, confirming the 4 edge-case fixes were well-scoped and
  correctly implemented.
  **Why**: each fix was minimal (1-3 lines) with a dedicated test case, so
  reviewers could verify the fix-to-test correspondence without tracing
  through complex call chains.
  **How to apply**: for defensive hardening PRs, pair each fix with its
  regression test in the same commit so reviewers can verify 1:1 coverage.
  **Cites**: Phase 2 release data; T2.

- **What happened**: Automated review (CodeRabbit + claude[bot]) identified
  all 3 edge-case gaps in a single review round, before any manual review.
  **Why**: the verify-docs gate operates on file paths and DB connections —
  domains where automated tools excel at spotting encoding/traversal issues.
  **How to apply**: automated reviewers are most valuable on I/O boundary
  code; prioritize enabling them on modules that handle paths, URIs, and
  external connections.
  **Cites**: T2; `gh api repos/.../pulls/235/comments` → 6 threads.

### What to improve

- **What happened**: The release process hit branch protection (`GH006:
  Protected branch update failed`) when attempting to push the release
  commit directly to main. The tag `v0.16.1` was pushed before the commit
  landed on main, creating a window where the tag pointed to a commit
  reachable only via the tag ref itself.
  **Why**: `docs/RELEASE.md` does not document that direct pushes to main
  are blocked. The operator assumed the same flow as pre-branch-protection
  releases.
  **How to apply**: update `docs/RELEASE.md` to document the
  branch-protection-aware release flow: create release branch, push, open
  PR, merge, then tag. Tag should follow the merge, not precede it.
  **Cites**: T3; T4; `docs/RELEASE.md` gap confirmed by facilitator.

- **What happened**: Two pre-schema retros (2026-08-19) broke the
  carry-forward reconciliation chain, leaving 5 items from the 2026-08-17
  retro unreconciled for 2 cycles.
  **Why**: the retros were written in an ad-hoc format without the
  registration table or Interview Transcript sections. No gate prevented
  committing a non-conformant retro.
  **How to apply**: when writing a retro outside the `compound-loop`
  skill, include at minimum the `Carry-forward items registered` table
  and reference the previous retro's items. The backward check in the
  next conformant retro catches violations one cycle late.
  **Cites**: T1; T5; Phase 4 reconciliation (registered 0, accounted for 2, degraded).

### Process observations

- The `--admin` flag was needed to merge PR #236 because auto-merge is
  disabled on the repository. For patch releases that are version-bump-only
  with all CI green, this is acceptable friction.
- The `_FakeMCP` rename has been deferred for 2 cycles now (first
  registered 2026-08-19). It is LOW priority with no functional impact
  but should be addressed to prevent indefinite drift.

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Update `docs/RELEASE.md` with branch-protection-aware release flow | process | P3 | This retro (no ROADMAP row yet) |
| `_FakeMCP` test helper rename in `tests/test_contract_sync.py` | edge-case | P4 | Inherited from 2026-08-19 retro |
| Reach maturity 75 without inferring causes from component scores alone | measurement | P3 | ROADMAP.md:383 |
| Decide whether to ship `py.typed` | architecture | P4 | ROADMAP.md:363; ADR 0019 defers |

## Lessons

- When branch protection blocks direct pushes, always merge the release
  commit to the target branch before pushing the tag. The reverse order
  creates a window where the tag is unreachable from the branch, and a
  failed CI run would leave an orphaned tag requiring manual cleanup.

## Compounding

Not attempted — the tag-before-merge lesson is specific and actionable but
scoped to this project's release process documentation (`docs/RELEASE.md`).
Updating RELEASE.md directly (registered as carry-forward P3) is more
appropriate than a standalone `docs/solutions/` entry. No reusable
cross-project pattern emerged this cycle.

---

Retrospective complete — docs/retros/2026-08-21-v0161-verify-docs-hardening-retro.md
