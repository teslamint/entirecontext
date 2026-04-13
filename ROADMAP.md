# EntireContext Roadmap

_Updated against codebase on 2026-03-12._

## Product Thesis

EntireContext should become the system that helps coding agents accumulate engineering judgment over time.

The goal is not to store more agent history. The goal is to make past decisions, lessons, and feedback reappear at the exact moment they can improve the next code change.

In short:

`capture -> distill -> retrieve -> intervene`

## What We Are Optimizing For

1. Better decisions in repeated coding workflows
2. Less context loss across sessions, repos, and agents
3. Reuse of past lessons before mistakes repeat
4. Strong git grounding for trust, auditability, and rewindability

## Current Position

The project already has broad infrastructure in place:

- capture hooks for sessions, turns, checkpoints, and tool activity
- git-aware rewind, attribution, and checkpoint history
- hybrid retrieval across search, AST, graph, dashboard, and MCP tooling
- futures assessments, feedback loops, lessons, and trend reporting
- sync, filtering, export, and consolidation for operating the memory layer

That foundation is useful, but it is broader than the product wedge. The next phase should narrow EntireContext around **decision memory for coding agents**, not expand it horizontally as a generic memory platform.

The main implementation hardening gap still on the table is sync merge/retry policy alignment between runtime and docs.

## Now

- [ ] **Sharpen product messaging around decision memory**
  - Keep README, roadmap, and product-facing docs centered on the decision-memory loop
  - Move broad platform capabilities into supporting sections instead of leading with them
  - Make the primary persona explicit: engineers and small teams already doing agentic coding

- [x] **Define a first-class decision model**
  - Represent decision, rationale, rejected alternatives, supporting evidence, scope, and staleness
  - Link decisions to commits, checkpoints, files, and assessments
  - Clarify how decisions differ from summaries, assessments, and lessons (documented in README + CLI/MCP examples)

- [ ] **Make retrieval proactive, not just query-based**
  - Surface relevant past decisions when similar files, diffs, or intents appear
  - Rank results by current-change relevance, not only text similarity
  - Expose the retrieval path through MCP so agents can consume it automatically

## Next (1-3 weeks)

- [ ] **Decision extraction pipeline**
  - Extract candidate decisions from sessions, checkpoints, and assessments
  - Allow confidence scoring plus lightweight human or agent confirmation
  - Validate extraction quality against noisy, real coding sessions

- [ ] **Relevance-based reactivation**
  - Use touched files, diff similarity, git relationships, and assessment links
  - Present "read these past decisions first" suggestions before new work starts
  - Verify usefulness on repeated-task and regression-fix scenarios

- [x] **Staleness and contradiction handling** (#39)
  - Retrieval hard-filters superseded/contradicted via central `_apply_staleness_policy` helper
  - Supersession chain collapse substitutes terminal successors; cycle-safe via multi-hop detection and depth cap
  - Auto-promotion of `contradicted` status from outcome feedback (configurable threshold, one-way ratchet)
  - Documented retrieval policy matrix and deprecation window in README § Staleness Policy

## Later (1-3 months)

- [x] **Sync merge/retry 정책 정비** (P2, spec §10 #4)
  - `sync/merge.py`에 merge helpers 존재하지만 `sync/engine.py`에서 미사용
  - 선택지: app-level merge/retry 루프 구현 또는 docs/README에 정책 축소 명문화
  - 영향 파일: `sync/engine.py`, `sync/merge.py`, docs
  - 테스트: 선택한 정책의 구현/문서 일관성 검증

- [ ] **Decision quality loop**
  - Track whether retrieved guidance was accepted, ignored, or contradicted
  - Measure which decisions and lessons actually improve later changes
  - Use those outcomes to improve ranking and distillation quality

- [ ] **Team policy and review memory**
  - Capture recurring team preferences, review heuristics, and architectural constraints
  - Separate repo-local norms from cross-repo lessons
  - Generate team-facing reports about repeated decisions and repeated mistakes

- [ ] **Sync and runtime hardening**
  - Resolve merge/retry policy alignment in the sync engine or narrow the documented policy explicitly
  - Keep docs and runtime behavior consistent for shared usage
  - Test divergent shadow-branch conflict scenarios

## Done Foundations

- [x] Capture hooks, checkpoints, rewind, and attribution
- [x] Hybrid search, AST search, graph/dashboard tooling, and MCP exposure
- [x] Futures assessments, typed relationships, feedback, lessons, and trend analysis
- [x] Async workers, filtering, export, consolidation, and cross-repo support

## Exploration

- **Temporal queries** — how decisions and lessons change over time
- **Agent learning reports** — where prior guidance helped and where it was ignored
- **Decision packs by area** — reusable memory bundles for domains like sync, testing, or search
- **Human-in-the-loop correction UX** — fast review of extracted decisions and stale lessons

## Non-Goals for This Phase

- Becoming a generic knowledge management system
- Expanding dashboard or graph breadth before retrieval quality improves
- Storing more raw transcripts without better distillation
- Adding platform surface area that does not reinforce the decision-memory loop

## References

- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
