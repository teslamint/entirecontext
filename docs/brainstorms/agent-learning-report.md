# Agent Learning Report (After-Action Digest)

_Draft brainstorm. Created 2026-04-27. Milestone: v0.7.0. Confidence: 90%._

## Intent

`SessionEnd` emits a structured after-action report (AAR) covering: new decision candidates extracted, decisions surfaced during the session, `ec_context_apply` acceptances recorded, and inferences marked as ignored. The report is written as a Markdown artifact by a detached background subprocess so the 5-second `SessionEnd` budget is never in jeopardy.

User-visible outcomes:

- Each completed session produces `.entirecontext/session-report-<session_id>.md` summarizing what the agent learned and what decisions it acted on.
- Operators can audit learning quality per-session without querying the DB.
- The report is a diagnostic artifact, not a narrative: structured counts and lists, not LLM prose.

## Scope

### In

- `.entirecontext/session-report-<session_id>.md` artifact: four sections — (1) decisions extracted (new candidates), (2) decisions surfaced (presented to agent), (3) `ec_context_apply` acceptances, (4) ignored inferences.
- Report writer launched via `core/async_worker.py:launch_worker` as a detached subprocess; zero synchronous DB reads in the `SessionEnd` handler itself.
- Config gate: `[decisions] emit_learning_report = false` (default `false`; opt-in for v0.7.0 while format stabilizes).
- Report content sourced entirely from fast aggregate queries against existing tables: `decision_candidates`, `decisions`, `events`, `sessions.metadata`.
- Unit tests for report assembly logic and subprocess launch path.

### Out

- LLM-generated narrative or explanations in the report.
- Cross-session trend analysis or comparison (deferred; requires aggregation across sessions).
- Any new schema columns or tables.
- Changes to existing `on_session_end` fast path (structured data collection, hook exit, checkpoint commit).

## SessionEnd Budget Contract

The `SessionEnd` handler must exit within 5 seconds. The report writer path must not violate this:

| Step | Handler (sync) | Worker (detached subprocess) |
|---|---|---|
| Aggregate session metadata | Read from `sessions.metadata` — O(1) | — |
| Count new candidates | `SELECT COUNT(*) FROM decision_candidates WHERE session_id = ?` — O(1) | — |
| Launch worker | `launch_worker(report_writer, session_id)` — non-blocking | Runs after handler exits |
| Write `.md` artifact | — | Worker does all file I/O |

The synchronous handler collects only the metadata needed to pass to the worker; all DB reads that require row-level data happen in the subprocess.

## Data Source Mapping

| Report section | Data source | Notes |
|---|---|---|
| Decisions extracted | `decision_candidates` WHERE `session_id = ?` | Counts only; new rows this session |
| Decisions surfaced | `sessions.metadata.surfaced_decisions` OR `events` WHERE `event_type = 'retrieval'` | Source completeness must be verified — see Review Questions |
| `ec_context_apply` acceptances | `decision_outcomes` WHERE `outcome_type = 'accepted'` AND `session_id = ?` | Already recorded by F3/E5 path |
| Ignored inferences | `decision_outcomes` WHERE `outcome_type = 'ignored'` AND `session_id = ?` | Recorded by SessionEnd ignored-inference gate |

## Proposed Action Items

### v0.7.0 Core

[ ] Verify whether `sessions.metadata.surfaced_decisions` captures decisions surfaced across all hook types (SessionStart, UserPromptSubmit, PostToolUse). If not, enumerate gap and define the canonical retrieval-event source before implementing the report.

[ ] Define the report Markdown schema: four required sections with counts and decision ID lists; no prose generation.

[ ] Implement report assembly function in `core/decisions.py` or `core/report.py`: takes session ID, queries aggregates, returns structured dict.

[ ] Add report writer entry point compatible with `launch_worker` subprocess protocol.

[ ] Wire `launch_worker(report_writer, session_id)` into `hooks/handler.py:on_session_end`, gated by `[decisions] emit_learning_report`.

[ ] Add config key `emit_learning_report` under `[decisions]` section (default `false`).

[ ] Add unit tests for report assembly (mock DB, verify section counts), subprocess launch (verify non-blocking), and empty-session edge case (zero extractions, zero surfaced).

[ ] Document `.entirecontext/session-report-<session_id>.md` artifact format in README.

[ ] Update CHANGELOG and ROADMAP.

## Risks

- Data source incompleteness: if `surfaced_decisions` in `sessions.metadata` does not track all hook types, the "decisions surfaced" count will be wrong. This must be audited before implementation.
- File accumulation: every session produces a `.md` file; without a retention policy, `.entirecontext/` will accumulate stale reports. Define a max-age or max-count default.
- Worker failure silent: if `launch_worker` subprocess fails (crash, DB locked), the session produces no report but the handler already exited successfully. Failure mode must be logged to a known location.
- Format instability: if report format changes between versions, older reports will be misread by tooling that parses them.
- Opt-in default masks value: setting `emit_learning_report = false` by default means most users never see the report. Reconsider default for v0.7.1 once format is validated.

## Review Questions

- Is `sessions.metadata.surfaced_decisions` a complete and reliable source for all hook types that surface decisions, or does "surfaced" need to be reconstructed from `events` WHERE `event_type = 'retrieval'`?
- Should the report include decision IDs and titles, or counts only? Title inclusion makes the report human-readable but adds DB reads in the worker.
- What is the retention policy for `.entirecontext/session-report-*.md` files — should there be a max count, max age, or should cleanup be a separate `ec tidy` subcommand?
- Should `emit_learning_report` default to `true` at v0.7.0 or remain opt-in until the format is validated in v0.7.1?
- How should the worker signal failure — write a `.error` file alongside the `.md` path, log to stderr captured by `launch_worker`, or silently discard?
