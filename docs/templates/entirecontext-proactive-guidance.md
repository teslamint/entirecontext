# Proactive EntireContext Guidance for AGENTS.md

Add this block to your `AGENTS.md` to have agents proactively check broader EntireContext memory — not only decisions, but also assessments, lessons, checkpoints, attribution, sessions, and turns.

## Recommended Placement

- Near other agent workflow rules or memory lookup rules
- Immediately after any OneContext/Aline history-search block if you already have one
- Keep the `<!-- ENTIRECONTEXT:START -->` and `<!-- ENTIRECONTEXT:END -->` markers so the block is easy to find and update later

## Example Block

```md
<!-- ENTIRECONTEXT:START -->
## EntireContext - Proactive Memory Reuse

When the repository has EntireContext available, **proactively** use EntireContext
before answering questions about existing code, prior decisions, debugging context,
historical implementation details, repeated regressions, or earlier agent work.
Do not wait for the user to explicitly ask for a memory lookup.

Prefer EntireContext first for repository-scoped memory such as decisions,
assessments, lessons, checkpoints, attribution, sessions, and turns.
Use OneContext/Aline as a fallback when the user explicitly asks for Aline history
or when EntireContext does not contain the needed context.

Scenarios to proactively use EntireContext:
- User asks "why was X implemented this way?" or asks for prior rationale
- User is debugging behavior that may have previous fixes, regressions, or lessons
- User references a function, file, subsystem, checkpoint, session, or decision that may already exist in memory
- The task changes behavior, policy, schema, interface, lifecycle, sync, ranking, hooks, telemetry, or other long-lived system behavior
- You need prior assessments, lessons, attribution, or related turns before proposing non-trivial changes

Preferred retrieval order:
1. **One-call proactive retrieval** — `ec_decision_context()` is the preferred starting point when you begin a task or shift to a new area of the code. It auto-assembles signals from the current session (files from recent turns, uncommitted diff, latest checkpoint) and returns ranked decisions with per-result `selection_id`. If `signal_summary.active_session` is `false`, the tool fell back to git-diff-only signals and you should treat the results as best-effort.
2. Explicit decision queries (`ec_decision_related` with explicit files/diff/assessments, `ec_decision_list`, `ec_decision_get`) when you need to target a specific context that `ec_decision_context` can't infer.
3. Broader repo memory lookup (`ec_related`, `ec_search`, `ec_session_context`)
4. Lesson retrieval (`ec_lessons`) — especially when debugging regressions, working in areas with prior narrow verdicts, or making structurally similar changes to previously assessed work
5. Deep inspection (`ec_turn_content`, `ec_checkpoint_list`, `ec_attribution`, `ec_assess_trends`)

**Mid-session decision surfacing** — when `decisions.surface_on_tool_use` is enabled (see README § Proactive Retrieval), decisions linked to files you just edited appear as a `## Related Decisions (current edit)` block after tool results, and are also written to `.entirecontext/decisions-context.md`. Read that file whenever you edit decision-linked code. The hook deduplicates per-turn and session-wide, so the same decision will not be re-surfaced during a single session — if you need to re-check it, call `ec_decision_get` explicitly.

If no relevant EntireContext records exist, state that explicitly before proceeding
with new reasoning.

### Decision Capture — Recording What Was Decided

Retrieval alone loses decisions that were never recorded. Proactively **create**
decision records during the session, not only at the end.

When to record a decision (`ec_decision_create`):
- You compared alternatives and chose one (record what was rejected and why)
- You changed architecture, module boundaries, data flow, or public interfaces
- You established a convention, policy, or constraint that future work should follow
- A debugging session revealed a root cause that changes how the system should behave

When to record a decision outcome (`ec_decision_outcome`):
- Completed work confirmed, contradicted, refined, or replaced a prior decision
- A decision was applied and the result validated or invalidated its rationale

Capture timing:
- Record **during** the session as decisions happen — do not defer to SessionEnd
- SessionEnd auto-extraction (`maybe_extract_decisions`) is a fallback, not the primary path
- If you realize a past session made an unrecorded decision, record it retroactively

### Lesson Feedback — Building Lessons from Assessed Work

Lessons accumulate from assessment feedback. Proactively provide feedback on
assessed changes so the lesson pipeline has material to distill.

When to provide feedback (`ec_feedback`):
- Completed work was previously assessed and you can confirm or dispute the verdict
- You observe that a past assessment's prediction was correct or incorrect
- A debugging session reveals that a prior assessed change caused the issue

Feedback timing:
- Provide feedback as soon as you have evidence — do not defer to session end
- Include a reason so the distilled lesson captures the context
<!-- ENTIRECONTEXT:END -->
```
