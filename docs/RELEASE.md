# Release Rules
<!-- last-analyzed: 2026-07-07T10:00:00Z -->

## Version Sources
- `pyproject.toml` line 3: `version = "X.Y.Z"`
- `src/entirecontext/__init__.py`: `__version__ = "X.Y.Z"`
- Both MUST match the tag being pushed. (v0.9.3 lesson: `__init__.py` was stuck at 0.7.1 for 5 releases.)

## Release Trigger
- Tag push matching `v*` → triggers `.github/workflows/release.yml`

## Test Gate
- `uv run ruff check .` (lint)
- `uv run pytest` (test)
- Both must pass before build/publish

## Registry / Distribution
- PyPI via `pypa/gh-action-pypi-publish` (OIDC, no token needed)
- GitHub Release created with `softprops/action-gh-release@v2` + `generate_release_notes: true`
- CI pipeline: lint → test → build → publish → release → close-release-issues
- PyPI uploads are irreversible — review before tagging, not after (v0.9.3 lesson)

## Release Notes Strategy
- `CHANGELOG.md` (Keep a Changelog format)
- GitHub release body auto-generated from PR titles
- CHANGELOG section `[X.Y.Z] - YYYY-MM-DD` must exist before tagging

## CI Workflow Files
- `.github/workflows/release.yml`

## Pre-Release Checklist

Work through in order. Items marked [auto] can be CI-enforced; [manual] require human judgment.

### 1. Planning (before implementation)
- [ ] [manual] ROADMAP section `## vX.Y.Z — Theme` exists with scope items
- [ ] [manual] Previous retro carry-forward items reviewed — each is addressed, deferred with rationale, or won't-fixed

### 2. Implementation
- [ ] [auto] `uv run ruff check .` passes
- [ ] [auto] `uv run pytest` passes
- [ ] [manual] Codex review completed on release branch — fix all findings before proceeding

### 3. Pre-Tag Verification
- [ ] [auto] Version sync: `pyproject.toml` == `__init__.py` == tag (`vX.Y.Z`)
- [ ] [auto] CHANGELOG section `[X.Y.Z] - YYYY-MM-DD` exists
- [ ] [manual] `uv run ec dashboard` — record maturity score in retro/CHANGELOG
- [ ] [manual] Check known measurement health: lesson_reuse_rate, applied_context_rate, experiment status

### 4. Tag & Publish
- [ ] Ordering: all above green → tag push → CI publish
- [ ] Never re-tag after PyPI publish — bump version number instead
- [ ] Docs-only changes (zero code diff) do not warrant a standalone tag — bundle into the next feature release

### 5. Post-Release
- [ ] [manual] Retro conducted — findings become carry-forward or won't-fix
- [ ] [manual] Carry-forward items registered in ROADMAP or explicitly closed

## First-Time Setup Gaps
- none
