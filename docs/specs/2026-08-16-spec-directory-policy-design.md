---
title: Spec Directory Policy
status: approved
date: 2026-08-16
schema: spec/v1
---

# Spec Directory Policy Design

_Created 2026-08-16._

## Overview

Make `docs/specs/` the repository's single official location for active design Specifications. Align the repository policy and current traceability references with the directory already used by the five most recent Specifications, while preserving historical archive paths as evidence of where those artifacts were created.

## User Scenarios

### S1: Author a new Specification

A contributor creating a new design document uses `docs/specs/YYYY-MM-DD-<topic>-design.md`. Repository guidance points to this location, so the author does not need to choose between two competing paths.

### S2: Trace a current Plan to its Specification

A reviewer follows a Plan's `origin:` field to a file under `docs/specs/`. The referenced file exists, and the path matches the repository's declared policy.

### S3: Read historical release evidence

A contributor opens an archived progress, ADR, Plan, or Retro that refers to a Specification created under `docs/specs/`. The historical path remains unchanged, so the record continues to describe the repository state at that time.

### S4: Review policy compliance

A maintainer searches active policy and traceability documents for `docs/superpowers/specs/` and finds no current-policy reference requiring that path. The old path may remain only in historical evidence or references to older artifacts that genuinely live there.

## Scope

### In

- Update `AGENTS.md` to declare `docs/specs/` as the governing Specification path.
- Update active ADR, Plan, deviation, and other current traceability references that point to the wrong path when their referenced Specification is under `docs/specs/`.
- Preserve existing Specification files in their current directories.
- Mark the corresponding `ROADMAP.md` drift item complete with the chosen policy and migration boundary.
- Verify every active `origin:`, `Spec:`, and equivalent traceability pointer resolves to an existing file.

### Out

- Moving or renaming existing Specification files.
- Rewriting historical `.release-loop/archive/` evidence solely to normalize paths.
- Changing the release-loop progress schema or archive procedure.
- Changing Specification content, approval status, or implementation behavior.
- Allowing both directories as interchangeable locations for new Specifications.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The repository has five active Specifications under `docs/specs/`. | `git ls-files 'docs/specs/*.md' | wc -l` | 2026-08-16T08:12:56Z | Isolated worktree at `71a1383` | 5 files |
| The repository policy currently names the competing path. | `grep -n 'docs/superpowers/specs/' AGENTS.md` | 2026-08-16T08:12:56Z | Isolated worktree at `71a1383` | `AGENTS.md:20` |
| Current ADR and traceability documents contain references to `docs/specs/`. | `git ls-files '*.md' | xargs grep -nE 'docs/(superpowers/)?specs/'` | 2026-08-16T08:12:56Z | Isolated worktree at `71a1383` | Active and archived references enumerated by command | 

## Architecture

The repository has one policy source for Specification placement: `AGENTS.md`, with the rationale recorded in ADR 0010 and EC decision `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`. Active artifacts use repository-relative paths and must resolve against the checkout. Historical artifacts remain immutable evidence and are not rewritten as part of this change.

The resulting traceability chain is:

`docs/specs/` → `docs/adr/` → `docs/superpowers/plans/` or `docs/plans/` → implementation → `docs/retros/`

No runtime module, database table, CLI command, or public API changes.

## Traceability Rules

- New Specifications MUST be created under `docs/specs/`.
- Active documents MUST use the path of the Specification that actually exists.
- Historical archive documents MAY retain their original paths.
- A reference is considered broken when its target path does not exist in the current checkout and the reference is not explicitly historical evidence.
- The policy MUST NOT describe `docs/specs/` and `docs/superpowers/specs/` as equivalent active locations.

## Testing

Validation is repository-text validation rather than runtime testing:

1. Search active policy and traceability files for the competing path.
2. Enumerate every active `origin:`/`Spec:`/`spec:` pointer and verify its target exists.
3. Confirm no Specification file was moved or renamed.
4. Run the repository's documentation and metadata checks, if configured.

## Risks

- **Historical link churn:** rewriting archived evidence would obscure the path used at the time. Mitigation: leave archive content unchanged.
- **Partial reference migration:** updating `AGENTS.md` but missing an ADR or Plan pointer would leave the traceability chain inconsistent. Mitigation: package-wide search plus target-existence check.
- **Future dual-path drift:** contributors may continue using the old directory if guidance remains ambiguous. Mitigation: make `docs/specs/` the only active path and explicitly state the old path is not an alternative.

## Success Criteria

1. `AGENTS.md` names `docs/specs/` as the sole governing active Specification path.  
   - **Measured by**: `grep -n 'docs/specs/' AGENTS.md` returns the policy line and `grep -n 'docs/superpowers/specs/' AGENTS.md` returns no match.
2. Every active Specification traceability pointer resolves to an existing file.  
   - **Measured by**: a repository script enumerates active `origin:`/`Spec:`/`spec:` paths and exits 0 after checking each target.
3. Existing Specification files are not moved or renamed.  
   - **Measured by**: `git diff --name-status -- docs/specs docs/superpowers/specs` contains no rename or delete entries.
4. The roadmap drift item records the selected policy and is closed.  
   - **Measured by**: `ROADMAP.md` contains a checked entry documenting `docs/specs/` as the official path and historical archive preservation.
5. Historical release evidence remains readable without path rewriting.  
   - **Measured by**: archived progress, ADR, Plan, and Retro files retain their original paths and their referenced historical Specification files remain present.

## Open Decisions

None. The user approved the `docs/specs/`-official policy on 2026-08-16. Implementation may choose the narrowest active-reference set that satisfies the success criteria without rewriting historical evidence.
