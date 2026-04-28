# Alive Session Memory (Rolling WAL Capture)

_Draft brainstorm. Created 2026-04-27. Milestone: v0.8.0. Confidence: 83%._

## Intent

`PostToolUse` hook appends a JSONL record to `.entirecontext/wal/<session_id>.jsonl` immediately after each tool call, within the 3-second hook budget. A background consolidator reads the WAL every 30 seconds and writes completed turn records into `turns` and `turn_content`. If the session crashes before `SessionEnd`, the WAL provides a recovery path.

Without this feature, a Claude Code session that crashes mid-run loses all turn data for that session. CI pipelines and long-running agentic tasks are the highest-risk cases.

User-visible outcomes:

- Session data survives agent crashes, OOM kills, and CI runner timeouts.
- Turn content is available for search within ~30 seconds of each tool call.
- Crash recovery on next `SessionStart` automatically consolidates any orphaned WAL file.

## Scope

### In

- `PostToolUse` hook handler: append-only `open(append) + write + close` on `.entirecontext/wal/<session_id>.jsonl`; no DB access in the hot path.
- WAL record schema: `{turn_id, tool_name, files_touched, timestamp, tool_result_summary}`.
- Background consolidator: reads WAL JSONL, writes to `turns` / `turn_content` tables, truncates consumed records.
- Recovery path: `SessionStart` checks for orphaned WAL files from prior sessions and triggers consolidation before proceeding.
- Config: `[capture] rolling_wal = false` (opt-in), `consolidation_interval_seconds = 30`.
- Integration test: write N WAL records, crash the session process, verify consolidator recovers all N turns on next `SessionStart`.

### Out

- Full prompt/response capture in WAL (WAL stores tool metadata only, not full turn content — that remains in `turn_content` files via existing path).
- Cross-repo WAL sync (local only).
- Any change to the existing `on_stop` / `_save_content_file` path in `hooks/turn_capture.py`.

## Hard Constraint: 3-Second PostToolUse Budget

`PostToolUse` must complete within 3 seconds. The WAL flush path must be:

```python
with open(wal_path, "a") as f:
    f.write(json.dumps(record) + "\n")
```

No DB reads, no DB writes, no subprocess launch, no network calls. The only I/O is a single file append. This must be enforced by a dedicated latency test.

## Background Consolidator Design

| Approach | Mechanism | Pros | Cons |
|---|---|---|---|
| Named `launch_worker` subprocess | Detached subprocess from `core/async_worker.py`, re-spawned every 30s by a `SessionStart`-created timer | Consistent with existing worker model; crash-isolated | Re-spawning overhead; no long-lived daemon |
| Long-lived background thread in hook process | Thread spawned at `SessionStart`, runs until `SessionEnd` | Simple lifecycle; no respawn overhead | Thread crash kills silently; Python GIL may affect timing |

**Recommended:** `launch_worker` subprocess approach for consistency with the existing async worker model. The subprocess is spawned once at `SessionStart` and runs until the WAL is empty and the session is inactive. If the consolidator crashes, `SessionStart` recovery handles the orphan.

This choice must be confirmed before implementation starts.

## WAL Record Schema

```json
{
  "turn_id": "<uuid>",
  "session_id": "<session_id>",
  "tool_name": "Bash",
  "files_touched": ["src/foo.py", "src/bar.py"],
  "timestamp": "2026-04-27T12:34:56Z",
  "tool_result_summary": "exit_code=0, stdout_lines=12"
}
```

`tool_result_summary` is a short string (max 200 chars) derived from the tool result, not the full result. Full result capture remains in existing `turn_content` file path.

## Recovery Protocol

```
SessionStart:
  1. Scan .entirecontext/wal/ for *.jsonl files from prior sessions
  2. For each orphaned WAL file (session_id not in active sessions):
     a. Run consolidator synchronously (within SessionStart budget — or via launch_worker)
     b. Mark WAL file as consumed (rename to .processed or delete)
  3. Proceed with normal SessionStart flow
```

The recovery scan must be fast (O(N files) not O(N records)) to stay within the `SessionStart` budget.

## Proposed Action Items

### v0.8.0 Core

[ ] Confirm consolidator design (long-lived `launch_worker` vs background thread) before implementation.

[ ] Add `[capture] rolling_wal` and `consolidation_interval_seconds` config keys.

[ ] Implement WAL flush in `hooks/turn_capture.py:on_post_tool_use`: append-only file write, gated by `rolling_wal = true`. Add latency assertion test.

[ ] Define WAL record schema (finalize `tool_result_summary` derivation rules — what qualifies as a summary for each tool type).

[ ] Implement consolidator: reads JSONL, writes `turns` / `turn_content`, truncates consumed lines. Handle partial records (incomplete JSON from crash mid-write).

[ ] Wire consolidator launch at `SessionStart` (as subprocess or thread per confirmed design).

[ ] Implement orphan recovery scan in `SessionStart` handler: find `.entirecontext/wal/*.jsonl` from inactive sessions, consolidate each.

[ ] Add `.entirecontext/wal/` to `.gitignore` template.

[ ] Integration test: simulate crash (kill consolidator mid-session), verify recovery on next `SessionStart` produces all expected `turns` rows.

[ ] Update CHANGELOG and ROADMAP.

## Risks

- Partial WAL records: if the process crashes mid-write (e.g., during `f.write`), the last JSONL line may be truncated. The consolidator must handle invalid JSON in the last line without losing prior valid records.
- WAL file accumulation: if `SessionEnd` cleanup fails and the WAL is never consumed, `.entirecontext/wal/` accumulates unbounded files. The recovery scan must also enforce a max-age cleanup policy.
- Consolidation lag: with a 30-second interval, turn content is not immediately searchable. This is acceptable for crash-safety but may surprise operators who expect instant search.
- Concurrent consolidator instances: if two `SessionStart` events trigger consolidation of the same WAL file (e.g., parallel CI jobs sharing a repo), both may try to write the same turns. Must use file locking or atomic rename on WAL consumption.
- `PostToolUse` budget regression: any change to the flush path (adding error handling, logging, etc.) risks exceeding the 3-second budget. The latency test must be part of CI, not just run manually.

## Review Questions

- Long-lived `launch_worker` subprocess vs background thread for the consolidator — which is preferred given the existing async worker model?
- Should the WAL append path include a try/except to silently suppress file I/O errors (e.g., disk full), or should errors propagate and block the hook? Blocking is safer for data integrity but may break tool use.
- How should partial JSON records (from mid-write crash) be handled — skip the last line, attempt JSON repair, or write a sentinel record at the start of each flush to enable position recovery?
- Should `consolidation_interval_seconds = 30` be configurable per-session or only globally? CI jobs may want a faster interval (5s) while interactive sessions are fine with 30s.
- Should `.entirecontext/wal/` be added to `.gitignore` automatically on `ec init`, or should it be documented as user-managed?
