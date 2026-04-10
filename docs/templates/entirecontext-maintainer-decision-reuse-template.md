# EntireContext Maintainer Template: Decision and Lesson Reuse Policy

Use this template in `AGENTS.md` for work inside the `entirecontext` repository itself.

It is process-neutral by design. It does not assume TDD, PR review, trunk-based development, or any specific release workflow. It only requires agents to treat stored decisions as a mandatory input for non-trivial work.

## Suggested Insertion

```md
## Decision and Lesson Reuse Policy

This repository is building decision and lesson memory for coding agents. Agents working in this repository must use stored decisions and lessons as part of the development workflow instead of treating them as optional background context.

### When to check decisions and lessons
Check for relevant prior decisions and lessons before non-trivial analysis or implementation when the task:
- changes behavior, policy, schema, or interfaces
- touches retrieval, ranking, sync, session lifecycle, hooks, dashboard, assessments, telemetry, or decision memory
- implements or reinterprets a roadmap item
- revisits an area with repeated bugs, repeated refactors, or prior design discussion
- asks why something was implemented a certain way
- involves debugging a regression, repeated failure, or issue structurally similar to a previously assessed change

### Required workflow
1. Retrieve relevant decisions before implementation.
2. Read the selected decisions before proposing or applying changes.
3. Scan lessons for applicable guidance from past assessed changes, especially when the task involves debugging, regressions, repeated subsystem work, or areas with prior narrow verdicts.
4. Prefer fresh decisions by default.
5. Do not silently apply stale, contradicted, or superseded decisions.
6. If decisions conflict, surface the conflict explicitly.
7. If no relevant decision exists, say that clearly before proceeding.
8. If a decision materially informed the work, record that usage.
9. After the work completes, record whether the result confirmed, contradicted, refined, or replaced the decision.
10. If the work creates a stable new policy or architectural judgment, create or update a decision record.
11. If the completed work was previously assessed, provide agree/disagree feedback with a reason so lessons can accumulate.

### Repository-specific retrieval path
Prefer the strongest decision-aware path available in the current environment:
- MCP: `ec_decision_related`, `ec_decision_get`, `ec_decision_list`
- CLI fallback: `ec decision list`, `ec decision show`, plus targeted `ec search` if needed

When prior guidance materially affects the task, also record usage through the available context-application path:
- MCP: `ec_context_apply(...)`
- CLI fallback: use the corresponding `ec context ...` commands if available in the current installed version

When the task outcome validates or invalidates a decision, record a decision outcome through the available interface:
- MCP: `ec_decision_outcome(...)`
- CLI fallback: use the corresponding decision outcome command if available in the current installed version

### Lesson retrieval path
Scan lessons before non-trivial work, especially when debugging regressions, working in areas with prior narrow verdicts, making structurally similar changes to previously assessed work, or revisiting a subsystem with existing assessment feedback.
- MCP: `ec_lessons`
- CLI fallback: `ec futures lessons`

Lesson retrieval is a quick scan, not a targeted lookup. Review recent lessons for relevance and proceed if none apply.

When providing assessment feedback after assessed work completes:
- MCP: `ec_feedback(assessment_id, feedback, reason)`
- CLI fallback: `ec futures feedback ASSESSMENT_ID FEEDBACK --reason REASON`

### Minimum behavior
For non-trivial tasks, do not move directly from request to implementation without a decision and lesson check unless the user explicitly asks to skip it.

If the agent skips the decision and lesson check, it must state that it skipped it and why.

### Final reporting
When decisions or lessons were relevant, the final response must include:
- which decisions were considered
- which decision was applied, if any
- which decisions were rejected or treated as stale, if any
- whether the completed work confirmed, contradicted, superseded, or extended prior guidance
- which lessons were reviewed, if any, and whether any influenced the approach
- which assessments received feedback during this task, if any

### Interpretation rule
Stored decisions are inputs to judgment, not blind rules. Follow relevant fresh decisions by default, but still verify fit against the current code, current task, and current user intent.
```

## Notes

- This version is intentionally specific to the `entirecontext` repository and names the local decision tools directly.
- Keep this policy separate from style rules, testing rules, or review process rules. Its role is to force prior engineering judgment into the work loop.
