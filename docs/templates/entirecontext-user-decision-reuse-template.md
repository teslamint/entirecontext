# EntireContext User Template: AGENTS.md Decision and Lesson Reuse Policy

Use this template in projects that have installed and enabled EntireContext and want coding agents to reuse stored decisions and lessons consistently.

It is intentionally workflow-neutral. It works for solo repositories, small teams, PR-based workflows, direct-to-main workflows, TDD, and non-TDD processes.

## Suggested Insertion

```md
## Decision and Lesson Reuse Policy

This project uses EntireContext to preserve engineering decisions and lessons over time. Agents must check for relevant prior decisions and lessons before making non-trivial changes so the project does not repeatedly rediscover the same judgment or repeat the same mistakes.

### When this policy applies
Use this workflow when the task materially affects behavior, architecture, policy, interfaces, data shape, or long-term maintenance cost.

Common examples:
- behavior changes
- schema or API changes
- architectural refactors
- retry, state, lifecycle, sync, ranking, or workflow changes
- repeated work in the same subsystem
- roadmap-driven work
- tasks where the user asks why something was done a certain way
- debugging a regression, repeated failure, or issue similar to a previously assessed change

### Required workflow
1. Before implementation, check whether relevant prior decisions already exist.
2. Read relevant decisions before making or proposing non-trivial changes.
3. Scan lessons for applicable guidance from past assessed changes, especially when the task involves debugging, regressions, repeated subsystem work, or areas with prior narrow verdicts.
4. Prefer fresh decisions by default.
5. Do not silently apply stale, contradicted, or superseded decisions.
6. If multiple decisions conflict, surface that conflict explicitly.
7. If no relevant decision exists, say so before proceeding with new reasoning.
8. If a prior decision materially informed the work, record that it was applied.
9. After completing the task, record whether the result confirmed, contradicted, refined, or replaced prior guidance.
10. If the task produces a stable new rule, policy, or architectural judgment, create or update a decision record.
11. If the completed work was previously assessed, provide agree/disagree feedback with a reason so lessons can accumulate.

### Retrieval path
Prefer decision-specific retrieval first, then broader history search only if needed.

Recommended order:
- decision-specific lookup
- file- or subsystem-scoped decision listing
- broader search across prior sessions or assessments

### Lesson retrieval
Scan lessons before non-trivial work, especially when debugging regressions, working in areas with prior narrow verdicts, making structurally similar changes to previously assessed work, or revisiting a subsystem with existing assessment feedback.

Lesson retrieval is a quick scan, not a targeted lookup. Review recent lessons for relevance to the current task. If no lessons exist or none are relevant, proceed without further delay.

### Minimum behavior
For non-trivial tasks, do not jump directly from user request to implementation without first checking for relevant decisions and lessons unless the user explicitly asks to skip that step.

If the agent skips the decision and lesson check, it must state that it skipped it and why.

### Final reporting
When decisions or lessons were relevant, final reporting must include:
- which decisions were considered
- which decision was applied, if any
- which decisions were rejected or treated as stale, if any
- whether the completed work confirmed, contradicted, superseded, or extended prior guidance
- which lessons were reviewed, if any, and whether any influenced the approach
- which assessments received feedback during this task, if any

### Interpretation rule
Stored decisions are inputs to judgment, not blind rules. Agents should follow relevant fresh decisions by default, while still checking that they fit the current code, current task, and current user intent.
```

## Customization Checklist

Teams adopting this template should adjust:

- Which subsystems are considered high-risk or decision-sensitive
- Which command or MCP path is preferred in their environment
- Whether decision usage is required for medium-risk tasks or only high-risk tasks
- Whether final reporting must always mention decision checks or only when decisions were found
- Whether lesson checks are expected for medium-risk tasks or only high-risk tasks

## Minimal Adoption Guidance

If a team wants the lowest-friction version, keep the policy text as-is and only add one short line listing the project's highest-risk areas.
