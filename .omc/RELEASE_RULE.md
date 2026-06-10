# Release Rules
<!-- last-analyzed: 2026-05-20T09:35:00Z -->

## Version Sources
- `pyproject.toml` line 3: `version = "X.Y.Z"`

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

## Release Notes Strategy
- `CHANGELOG.md` (Keep a Changelog format)
- GitHub release body auto-generated from PR titles
- CHANGELOG section `[X.Y.Z] - YYYY-MM-DD` must exist before tagging

## CI Workflow Files
- `.github/workflows/release.yml`

## Pre-Release Review Gate
- Run Codex review (`codex --approval-policy on-failure`) on the release branch BEFORE tagging
- Fix all Codex findings before proceeding to tag push
- Ordering: Codex review → fix → tag push → CI publish
- [ ] Codex review completed (shift-left checklist item — 3 consecutive releases missed this)

## First-Time Setup Gaps
- none
