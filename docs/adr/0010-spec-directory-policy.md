# 0010. Use `docs/specs/` as the Active Specification Directory

**Status:** accepted
**Date:** 2026-08-16
**EC Decision:** `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`

## Context

`AGENTS.md` declared `docs/superpowers/specs/` as the governing Specification directory, while the five most recent Specifications and their current Plans were written under `docs/specs/`. Moving only the recent files would leave older traceability records pointing at their original locations and would create unnecessary historical churn. Allowing both directories as active locations would preserve the ambiguity that caused the drift.

## Decision

Adopt `docs/specs/` as the sole active Specification directory. New Specifications and current traceability references MUST use this path. Existing Specification files are not moved or renamed. Specifications that genuinely remain under `docs/superpowers/specs/` retain their paths, and `.release-loop/archive/` evidence is preserved as historical record.

The policy source is `AGENTS.md`; the roadmap entry records the closure; this ADR records why the repository chose alignment with current practice rather than a mass move or a dual-path policy.

## Consequences

- Contributors have one unambiguous location for new Specifications.
- Active Plans, ADRs, and deviations can be checked against one official path.
- Historical documents may contain both directory names because they preserve the paths valid at the time they were written.
- A future repository-wide reference check must distinguish active documents from historical archive evidence.
- A later migration of the older `docs/superpowers/specs/` files remains possible, but it is not implied by this decision and requires a separate decision.

## References

- Spec: [`docs/specs/2026-08-16-spec-directory-policy-design.md`](../specs/2026-08-16-spec-directory-policy-design.md)
- Plan: [`docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md`](../superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
