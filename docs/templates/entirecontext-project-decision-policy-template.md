# Optional Project Decision Policy Template

Use this template to define your project's decision records and implementation requirements.
Adoption is optional. Your project owns the policy and chooses enforcement through agents, reviewers, or continuous integration (CI).
EntireContext (EC) stores and retrieves decisions; it does not enforce this policy or require particular decision fields.
EC maintainer rules do not apply automatically to consuming projects.

The [user reuse template](entirecontext-user-decision-reuse-template.md) describes how agents consult prior decisions and lessons.
This complementary template defines what your project records and when supporting plans or evidence are needed.
Neither template requires a particular development tool.

## Adapt before copying

Replace every `{{...}}` placeholder with your project's choice.
Choose one canonical location: the authoritative copy of this policy in your repository.
Remove the optional approval and exception sections if your project does not need them.
Keep any existing approval or exception rules that apply elsewhere.
Copy only the following block into your chosen location.

## Copyable policy

```md
# Project Decision Policy

## Scope and records

Record decisions about {{project choice: topics or change types worth preserving}}.
Store records at {{project choice: decision record location or system}}.

A rationale record explains an existing choice without requesting a behavior change.
An implementation decision records a proposed change and its authorization under existing project rules.
Label these records using {{project choice: how to distinguish rationale from implementation decisions}}.
Creating a decision record neither grants nor restricts permission to change code.
Existing project instructions and contribution rules govern that permission.

## Canonical authority and references

The authoritative policy is {{project choice: canonical repository path and revision reference convention}}.
Maintain it under {{project choice: policy owner and revision process}}.
Reference the applicable policy from each decision using {{project choice: repository path or evidence-link convention}}.
Enforce the adopted requirements through {{project choice: agents, reviewers, CI, or another existing process}}.

## Implementation criteria

For rationale records, use {{project choice: supporting context and whether a companion plan is needed}}.
For implementation decisions, require a plan when {{project choice: conditions that require a plan}}.
Use {{project choice: plan location and reference convention}} for those plans.
Require measurable success criteria when {{project choice: conditions and how to state the target}}.
Require verification evidence when {{project choice: conditions and evidence location or reference convention}}.
Describe what verification proves and any remaining gaps.

## Approvals (optional; remove if unused)

Obtain approval for {{project choice: changes that require approval}} from {{project choice: authorized project roles}}.
Record that approval using {{project choice: approval reference convention}}.
The project's authorized approval grants authority; a decision record documents it.

## Exceptions (optional; remove if unused)

Permit exceptions for {{project choice: eligible circumstances}} through {{project choice: existing exception authority or process}}.
Record {{project choice: required reason, scope, expiry, and follow-up references}}.

## Maintenance and supersession

Review decisions when {{project choice: review triggers or cadence}}.
Assign review to {{project choice: responsible project role}}.
Revise outdated decisions using {{project choice: revision process}}.
When a new decision replaces an old one, preserve the old rationale.
Link both records using {{project choice: replacement reference and superseded-status convention}}.
```

## Two hypothetical examples

Both examples use one hypothetical project's choices, not EC requirements.
This project records parser rationale without a plan.
It requires maintainer approval, a short plan, a measurable criterion, and verification evidence for retry behavior changes.
All paths below are illustrative references; they are not files or verification evidence from this repository.

### Example 1: Keep the existing parser

- Decision: Keep the existing parser because it handles the project's supported input formats.
- Kind: Rationale for existing behavior; no implementation change or companion plan.
- Policy reference: `docs/decision-policy.md` at the project's recorded revision.
- Context reference: `docs/decisions/parser-rationale.md` describes the supported formats and alternatives considered.

The record preserves the reason for the current parser. It grants no code-change permission.

### Example 2: Bound retry attempts

- Decision: Limit each operation to three total attempts, including the initial attempt.
- Kind: Implementation decision approved by the project's maintainer under its existing authority.
- Policy reference: `docs/decision-policy.md` at the project's recorded revision.
- Approval reference: `docs/decisions/retry-limit.md`, in its maintainer approval section.
- Short plan reference: `docs/plans/retry-limit.md` covers the attempt bound and verification for persistent failure.
- Success criterion: An operation with persistent failures makes exactly three attempts, then returns failure without a fourth attempt.
- Verification reference: `docs/evidence/retry-limit-check.md` would record the executed check, observed attempt count, result, and remaining gaps.

These references illustrate the project's chosen supporting records. They do not claim that a check ran or passed.
The maintainer's project approval authorizes the change; EC preserves that decision and its rationale.

## If you do not adopt this policy

You can still use EC and make the same retry change through your existing project workflow.
For example, a maintainer can request the change under the project's existing instructions and contribution rules.
Follow any approvals, plans, tests, or evidence requirements those rules already impose.
Declining this template neither prohibits the change nor waives those requirements.
EC can record and retrieve the decision without this policy; creating that record does not grant permission.
