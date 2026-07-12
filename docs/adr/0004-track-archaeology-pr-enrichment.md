# 0004. Track Archaeology PR Enrichment Separately

**Status:** proposed
**Date:** 2026-07-12
**EC Decision:** none (no relevant stored decision found)

## Context

`ec archaeologize --pr-bodies` currently warns and continues with commit-message and patch extraction when GitHub credentials are unavailable. Those commits are then recorded in `archaeology_processed`, so a later credentialed run skips them and can never add the explicitly requested PR rationale without manual database edits. Aborting the first run would preserve retryability but discard useful partial extraction.

## Decision

Schema v17 adds `archaeology_processed.pr_body_processed INTEGER NOT NULL DEFAULT 0`. Row existence continues to represent completed patch extraction; the new flag independently represents a conclusive PR-body enrichment attempt.

An explicitly requested tokenless run may continue patch extraction while leaving PR enrichment incomplete. A later credentialed run revisits incomplete rows and extracts only newly available PR-body evidence. A found body or a conclusive no-PR/empty-body response completes enrichment; hard API failures leave it retryable. Existing v16 rows migrate with the default incomplete state and are revisited only when users explicitly request `--pr-bodies`.

## Consequences

- Partial patch extraction remains useful and durable even when credentials are missing.
- Credential setup can be repaired later without replaying commit patches or manually editing SQLite state.
- The database gains a second processing-state dimension and requires a v17 migration.
- PR fetching must return explicit found/empty/failure states rather than overloading `None` and an empty string.
- Users with existing archaeology rows may opt into a one-time PR enrichment pass; ordinary patch-only reruns are unaffected.
