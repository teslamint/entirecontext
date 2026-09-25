# Release Rules
<!-- last-analyzed: 2026-07-07T10:00:00Z -->

## Version Sources
- `pyproject.toml` line 3: `version = "X.Y.Z"`
- `src/entirecontext/__init__.py`: `__version__ = "X.Y.Z"`
- Both files MUST match the tag being pushed. In the v0.9.3 lesson, `__init__.py` stayed at 0.7.1 for 5 releases.

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

Work through in order. CI can enforce the [auto] items. The [manual] items require human judgment.

### 1. Planning (before implementation)
- [ ] [manual] ROADMAP section `## vX.Y.Z — Theme` exists with scope items
- [ ] [manual] Review the previous retro carry-forward items. Address each, defer it with a rationale, or mark it won't-fix.

### 2. Implementation
- [ ] [auto] `uv run ruff check .` passes
- [ ] [auto] `uv run pytest` passes
- [ ] [manual] Complete a Codex review on the release branch. Fix all findings before you proceed.

### 3. Pre-Tag Verification
- [ ] [auto] Version sync: `pyproject.toml` == `__init__.py` == tag (`vX.Y.Z`)
- [ ] [auto] CHANGELOG section `[X.Y.Z] - YYYY-MM-DD` exists
- [ ] [auto] Run `uv run ec decision verify-docs` to confirm that all doc decision UUIDs resolve. If you release from a worktree, supply `--promote-from <worktree>/.entirecontext/db/local.db` first.
- [ ] [manual] Run `uv run ec dashboard`. Record the maturity score in retro/CHANGELOG.
- [ ] [manual] Check the status of these known measurements: lesson_reuse_rate, applied_context_rate, and experiment status

### 4. Tag & Publish
- [ ] Ordering: all above green → tag push → CI publish
- [ ] Never re-tag after PyPI publish. Bump the version number instead.
- [ ] Docs-only changes (zero code diff) do not warrant a standalone tag. Bundle them into the next feature release.

### 5. Post-Release
- [ ] [manual] Conduct a retro. Register each finding as a carry-forward item or mark it won't-fix.
- [ ] [manual] Register carry-forward items in ROADMAP or close them explicitly.

## First-Time Setup Gaps
- none
