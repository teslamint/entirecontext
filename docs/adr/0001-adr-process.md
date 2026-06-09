# 0001. Use ADRs for Cross-Cutting Decisions

**Status:** accepted
**Date:** 2026-06-09

## Context

The project uses EntireContext's decision memory for tracking implementation decisions.
However, durable cross-cutting policies (coding conventions, CI gates, architectural boundaries)
need a format that is version-controlled, discoverable without tooling, and readable in plain text.

## Decision

Adopt Architecture Decision Records in `docs/adr/` for cross-cutting decisions.
Lightweight implementation decisions remain as EC decision records.
ADRs reference EC decision IDs when both exist.

## Consequences

- Contributors can discover project policies by browsing `docs/adr/`.
- The ADR ↔ EC decision bridge avoids duplicate record-keeping.
- New ADRs require a PR, adding review friction (intentional for durable decisions).
