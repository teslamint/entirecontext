# 0016. Require Resolved Review Conversations Before Main Merges

**Status:** accepted
**Date:** 2026-08-17
**EC Decision:** `9bea7b63-29f1-4feb-9988-8a2c858e33de`

## Context

PR #205 was merged from a review snapshot taken six minutes earlier. A P2 comment
arrived 20 seconds before the merge and was not processed. Re-querying review
threads immediately before a client-initiated merge would reduce this race to one
network round trip, but could not eliminate it.

## Decision

Require all review conversations to be resolved before merging a pull request into
`main`, including merges performed by repository administrators. Enforce this
through the GitHub branch-protection settings
`required_conversation_resolution=true` and `enforce_admins=true` for
`teslamint/entirecontext`.

Do not add a client-side pre-merge re-query. Server-side enforcement evaluates the
current pull request state at merge time instead of narrowing the race to one
network round trip. Preserve the existing required status checks and all other
branch-protection settings.

## Consequences

- Pull requests cannot merge into `main` with an unresolved review conversation,
  including when a new comment arrives after the last client-side review pass.
- Repository administrators are subject to conversation resolution and the
  existing required status checks.
- Maintainers must resolve every review conversation before merging.
- The enforcement state lives in GitHub rather than Git. This ADR and the roadmap
  record the policy; verification must query the live branch-protection API.
