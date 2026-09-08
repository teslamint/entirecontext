---
schema: plan/v1
title: Optional Project Decision Policy Guidance
type: docs
status: draft
date: 2026-09-08
execution: non-code
origin: docs/specs/2026-09-08-project-decision-policy-design.md
---

# Optional Project Decision Policy Plan

## Goal

Publish an optional project policy template with clear adoption, authority, and enforcement boundaries.
Make it discoverable from the README and existing user reuse template.

## Architecture notes

Use the existing template pattern: a short introduction, one copyable Markdown block, and separate adoption guidance.
Keep EC-specific links and examples outside the copied policy.
Use explicit project-choice placeholders inside the block; approval and exception sections remain removable.
Preserve the existing user template's copied block byte-for-byte.
No source code, dependency, or EC development-policy changes are needed.

Known Pattern: the existing user template separates suggested insertion from customization guidance.
Known Pattern: `docs/solutions/workflow-issues/make-verification-commands-fail-closed.md` requires positive and negative verification evidence.
Use the installed Markdown parser for bounded checks; no new validator package or test file is warranted.
External SDK research is unnecessary because the deliverable uses existing Markdown conventions.

## Assumption Recheck

All commands ran in the feature checkout at `02ab1dd`, observed at `2026-09-08T01:48:52Z`.

| Approved claim | Exact command | Fresh evidence | Outcome |
|---|---|---|---|
| README links separate user and maintainer templates. | `sed -n '216,222p' README.md` | Both links present; exit 0. | match |
| The user template contains workflow requirements. | `rg -n 'Required workflow' docs/templates/entirecontext-user-decision-reuse-template.md` | Section at line 27; exit 0. | match |
| EC excludes policy enforcement. | `rg -n 'Policy enforcement / governance' ROADMAP.md` | Non-goal at line 465; exit 0. | match |

Contradictions require a separate committed deviation addendum before finalization; preserve the approved specification.
Unavailable evidence remains a planning-time unknown until resolved or narrowed by the user.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `README.md` | Modify Agent Setup Templates | Recommend a project-owned policy and link the template. |
| `docs/templates/entirecontext-project-decision-policy-template.md` | Create | Provide choices, a copyable policy, examples, and non-adoption guidance. |
| `docs/templates/entirecontext-user-decision-reuse-template.md` | Modify introduction | Explain optional adoption and link the complementary policy template. |

## Global Constraints

- Policy adoption does not grant or restrict code-change authority; existing project rules govern changes.
- EC records do not create permission, and non-adoption does not waive existing requirements.
- No runtime, schema, dependency, mandatory-field, or existing copied-workflow changes.
- Keep consumer guidance independent of specific development tools.
- Preserve unrelated work and approved specification content.

## Scenario coverage map

| Scenario | Unit chain | Observable verification |
|---|---|---|
| S1 | U1 | Follow the README link, copy and adapt the block in a temporary repository, and read it without EC-internal files. |
| S2 | U1 | Read the rationale example and confirm the example project requires no companion plan. |
| S3 | U1 | Read the retry example and identify project approval, a short plan, a measurable bound, and evidence reference. |
| S4 | U1 | Read the non-adoption explanation and confirm the same retry change follows existing project instructions. |

## Implementation Units

## U1: Publish optional project policy guidance

Files:
- Create: `docs/templates/entirecontext-project-decision-policy-template.md`.
- Modify: `README.md` and `docs/templates/entirecontext-user-decision-reuse-template.md`.

Steps:
1. Add a README recommendation that names project ownership, optional adoption, and the EC maintainer boundary.
2. Write one copyable policy block covering recording scope, canonical location and references, implementation criteria, optional approval and exceptions, and maintenance.
3. Mark each editable value as a project choice using double-brace placeholders. Explain adaptation and removal of optional sections before copying.
4. Add two short example decisions outside the block. Use existing parser rationale and a retry change with a maximum of three attempts.
5. Label all example paths as illustrative. Include a verification-result reference without presenting it as evidence from this repository.
6. Explain that declining adoption leaves existing instructions and contribution rules intact, including for the same retry change.
7. Add adoption context and the complementary link before the existing user template's copied block; preserve that block exactly.
8. Execute T1-T4 below, retain exact observed results, and obtain an independent compliance and quality review.
9. Commit the three deliverable files as `docs(policy): Explain optional project-owned decision policies`.

Acceptance: T1-T4 pass, all S1-S4 walkthroughs complete, and no Important or Critical review finding remains.

## Spec Test Disposition

| Spec check | Disposition | Plan evidence |
|---|---|---|
| T1 | retained | Parse the links in the three deliverables and resolve local file destinations and anchors. |
| T2 | retained | Copy and adapt the policy in a temporary repository without EC-internal files. |
| T3 | retained | Independently review examples, non-adoption, all seven success criteria, and all six issue acceptance criteria. |
| T4 | retained | Compare changed paths and the existing copied workflow with the base commit; check whitespace. |

## Verification procedure

T1: Use `markdown_it` to enumerate inline links in the three deliverables.
Resolve every local destination relative to its containing file and require a regular file.
Check any local anchor against the destination's headings.
Retain the checked destinations and count; require the new template to be reachable from both entry points.
Prove the check rejects a broken destination in a disposable copy, then rerun the unchanged documents.

T2: Extract the new template's sole Markdown fence into a temporary consumer repository.
Complete every double-brace project choice with a concrete example value and remove optional sections.
Read the resulting policy independently; require recording scope, canonical authority, implementation criteria, and maintenance to remain understandable.
Require zero remaining placeholders, broken local links, or EC-internal file dependencies.
Preserve the adapted policy as review evidence. Do not treat adaptation as real consumer adoption.

T3: Walk S1-S4 and evaluate each specification success criterion against the resulting documents.
Require the rationale and retry examples to reflect one explicitly hypothetical project policy.
Require approval to come from that project, with non-adoption neither prohibiting changes nor waiving existing rules.
Missing evidence or ambiguous wording fails the review and returns U1 for correction.

T4: Require only the three deliverable paths to change after this plan's approval commit.
Extract the original user template's Markdown fence from base `2d79a573ceb96bde1e5e799a1444740cd8acbaaf` and compare it with the final block.
Prove identical blocks compare equal and a disposable one-word alteration compares different before checking the actual blocks.
Check whitespace with Git's diff checker. Keep source and dependency changes out of the diff.
Run existing lint, format, type, and full test checks; report skips and failures explicitly.

The repository's behavior-changing Plan validator is not required for this documentation-only plan.
Use the packaged plan frontmatter validator for draft and approved documents.
The verification procedure uses named observable checks rather than publishing unexecuted shell recipes.

## Mutation/failure-state matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Carry-forward trigger audit

Audited ROADMAP.md at 2d79a573ceb96bde1e5e799a1444740cd8acbaaf: 10 open rows, 1 fired, 4 unobservable.

| Open rows | Trigger class | Observation | Disposition |
|---|---|---|---|
| Lines 204, 265, 300, 383: maturity and application-rate gates | drift-based | Current cross-session telemetry is unobservable from this documentation checkout; historical numbers are not current measurements. | Keep the four existing roadmap targets open. |
| Lines 338, 385: Git path escapes | event-based | No real path-escape failure in this task. | Not fired. |
| Line 380: post-squash archaeology | event-based | No content-export authorization or archaeology work in this task. | Not fired. |
| Line 396: alpha to stable | edit-based | README changes, but not the badge or release classifier named by the trigger. | Not fired. |
| Line 414: sharpen messaging | unclassifiable; assess as event-based | This guidance clarifies decision-memory boundaries. | Fold the bounded clarification into U1; broader messaging remains follow-up work. |
| Line 416: team-scoped decisions | unclassifiable; assess as event-based | No team scope or visibility capability changes. | Not fired. |

Known prior carry-forward: fail-closed verification applies to U1's checks; retain positive and negative evidence.

## Deferred to Follow-Up Work

- ROADMAP line 414: broader product messaging remains outside this bounded policy guide.
- The four existing maturity/application targets require cross-session measurements, not documentation edits or synthetic activity.
- No new product feature or runtime enforcement is proposed.

## Open unknowns

Planning-time: none for the deliverable. All approved assumptions match current repository files.
Implementation-time: exact explanatory wording and temporary verification paths remain local execution details.

## Release verification boundary

The installed release-loop runner reports `claude-hard-budget-unavailable` for its mandatory V1 adapter.
This is a release-tool limitation, not an EC product requirement or permission to fabricate verification receipts.
Complete U1 and its reviews first. Keep Ship blocked until the orchestrator resolves that release-tool requirement with the user.
Do not represent the document checks as the runner's V1 or V2 evidence.
