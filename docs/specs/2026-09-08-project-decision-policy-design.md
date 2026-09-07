---
title: Optional Project Decision Policy Guidance
status: draft
date: 2026-09-08
schema: spec/v1
---

# Optional Project Decision Policy Guidance

## Overview

Help projects choose which decisions to record and when implementation needs a plan or verification evidence.
Provide an optional policy template that each project owns after adoption.
This documentation fulfills [issue #250](https://github.com/teslamint/entirecontext/issues/250).

## User Scenarios

### S1: Adopt a project policy

A maintainer finds the template through the README, copies its policy block, and chooses a canonical location in their repository.
They complete the project choices and remove unused optional sections.
They choose whether agents, reviewers, or CI enforce their policy.

### S2: Record lightweight rationale

A developer records why an existing parser remains in use.
The example project allows this rationale record without a companion implementation plan.
The record itself does not grant permission to change code.

### S3: Authorize an implementation

A maintainer approves a retry-behavior change under their chosen project policy.
The example links the decision to a short plan, a measurable retry bound, and verification evidence.
Those requirements belong to the example project and are not EC decision fields.

## Scope

### In

- Add a README recommendation and a link to the optional policy template.
- Add `docs/templates/entirecontext-project-decision-policy-template.md` with one copyable policy block.
- Cover recording scope, canonical authority, implementation criteria, optional approvals and exceptions, and decision review or replacement.
- Label every project choice and optional section explicitly.
- Include the contrasting S2 and S3 examples as examples, outside the copyable policy block.
- Explain how this template complements the existing decision and lesson reuse template.
- Clarify adoption in the existing user template without changing its copied workflow requirements.

### Out

- Runtime, schema, CLI, MCP, dependency, or mandatory decision-field changes.
- Rejecting decisions because a policy, approval, or plan is absent.
- Universal compound-loop gates or automatic installation of policy text.
- Changes to EntireContext's own development requirements or historical evidence.
- A general documentation validator, new test framework, release version, or package publication.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The README already links separate user and maintainer reuse templates. | `sed -n '216,222p' README.md` | 2026-09-07T15:30:16Z | Both template links appear in Agent Setup Templates. | README.md at base commit `2d79a573ceb96bde1e5e799a1444740cd8acbaaf` |
| Existing user guidance contains requirements that need adoption context. | `rg -n 'Required workflow' docs/templates/entirecontext-user-decision-reuse-template.md` | 2026-09-07T15:30:16Z | A Required workflow section exists inside the suggested insertion. | User template at the same base commit |
| Policy enforcement is outside EC's product scope. | `rg -n 'Policy enforcement / governance' ROADMAP.md` | 2026-09-07T15:30:16Z | The non-goals assign enforcement to CI, linters, and review bots. | ROADMAP.md at the same base commit |

## Architecture

This is documentation-only work. README guidance introduces the project-owned policy and distinguishes EC maintainer rules from consumer guidance.
The new template contains adoption instructions, a self-contained policy block, and two short examples.
The existing user template links to it and explains that copied requirements apply after project adoption.
No new ADR is needed: this change explains the existing enforcement boundary without establishing an EC-wide development rule.

## Policy Contract

The project chooses the policy's canonical location and how decision records reference it.
Plain repository paths or existing decision evidence links suffice; the template must not invent a policy-registration command.
The copyable block defines rationale records and implementation-authorizing decisions without assuming either requires a particular tool.
It asks the project to select plan, success-criteria, and evidence requirements based on the change.
Approval roles and exception handling are optional project choices.
The project chooses how to review decisions, revise them, and preserve links to replacements.
Adoption and enforcement remain project responsibilities; EC does not enforce this template.

## Testing

- T1: Resolve every new or changed Markdown link in the deliverable documents relative to its containing document.
  Require local destinations to exist as files; inspect anchors when present.
- T2: Extract the policy block into a temporary consumer repository and complete every project choice for an example project.
  Remove optional sections, then verify the policy still explains recording scope, canonical authority, implementation criteria, and decision maintenance.
  Require no unresolved placeholders, broken local links, EC-internal file dependencies, or compound-loop dependency in the adopted policy.
- T3: Review both examples against the policy contract and all six issue acceptance criteria.
  Reject mandatory EC fields, universal approval gates, or wording that treats decision creation as implementation permission.
- T4: Check the final diff excludes source, schema, dependency, and existing workflow-rule changes.
  Run `git diff --check`; retain the baseline and relevant existing verification results separately.

The repository's measure-first infrastructure requirement is skipped because this change contains only documentation.
These checks measure document correctness; they do not establish runtime behavior or prove that consumers adopted the policy.
Use the existing Markdown parser if an executable check needs parsing; do not add dependencies or a general validator.

## Risks

- Copied examples could imply universal requirements. Label them as one project's choices and keep them outside the policy block.
- Relative links could break after copying. Keep EC cross-links outside the policy block and test the adopted document independently.
- Existing mandatory wording could obscure optional adoption. Clarify this boundary in both README guidance and the user template introduction.

## Success Criteria

1. A README reader can discover the project-policy recommendation and its reusable template.
   - Measured by T1 and a review of the README recommendation.
2. Every policy topic clearly identifies the project's choice or an optional section.
   - Measured by T3: all requested topics are present, with no implicit EC requirement.
3. The rationale and implementation examples show distinct treatment under one explicit example policy.
   - Measured by T3: rationale needs no plan; implementation includes a plan, success criterion, and evidence reference.
4. Consumers can distinguish EC development rules from their own adoption and enforcement choices.
   - Measured by T3: README and both user-facing templates state the boundary consistently.
5. An adopted policy stands alone in a consumer repository.
   - Measured by T2: zero unresolved choices, broken local links, or required EC-internal dependencies after adaptation.
6. The change introduces no runtime or mandatory workflow changes.
   - Measured by T4 and direct comparison of the existing template's copied workflow block.

## Open Decisions

None. The issue fixes product scope; planning owns exact document wording and the bounded verification commands.

## References

- [Existing user reuse template](../templates/entirecontext-user-decision-reuse-template.md)
- [EC maintainer template](../templates/entirecontext-maintainer-decision-reuse-template.md)
- [Roadmap non-goals](../../ROADMAP.md#non-goals)
- [Cogvault retrospective](https://github.com/teslamint/cogvault/blob/c7a5dfc/docs/retros/2026-08-25-wiki-git-safety-net-retro.md)
- EC decision `a62294a8-da6a-4e9f-bb76-92a388dc8631`: keep reuse policy separate from style, testing, and review rules.
