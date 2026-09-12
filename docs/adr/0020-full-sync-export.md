# 0020. Export all supported records on every sync

**Status:** accepted
**Date:** 2026-09-06
**EC Decision:** `ce7c276c-dd27-4ae5-a04a-2ccac02285e9`

## Context

A completion-time export boundary excludes writes made during sync. Start-time boundaries still lose same-second checkpoints and delayed writes.
Session metadata changes can also leave the activity timestamp unchanged.

## Decision

Enumerate all supported records on every sync. Keep the last successful export time for telemetry and automatic-sync debounce only.
The user selected full export. Do not introduce a change-sequence schema for this correction.

## Consequences

The next sync recovers records omitted by an earlier export, including backdated records.
Serialization work grows with the complete dataset. Measure the current recovery export before reporting its cost.
This policy does not promise an atomic remote view of concurrent writes or rewrite historical Git commits.
