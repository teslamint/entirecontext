# GitHub Release Asset Automation

- Date: 2026-04-15
- Topic: Attach built package artifacts to GitHub Releases after PyPI publish

## Summary

EntireContext already builds validated package artifacts (`dist/*.whl`, `dist/*.tar.gz`) in the release workflow before publishing to PyPI. The missing piece was exposing the same artifacts on GitHub Releases so users can download the exact built wheel/sdist from the release page.

## Decision

Use a dedicated `release` job after `publish` and publish assets with `softprops/action-gh-release@v2`.

Why this shape:

- Reuses the already-tested `dist/` artifacts instead of rebuilding.
- Keeps PyPI publish and GitHub Release asset upload as separate responsibilities.
- Supports idempotent release updates for existing tags via file overwrite behavior.

## Source Notes

Primary source checked:

- GitHub Marketplace snippet for `softprops/action-gh-release@v2`
  - URL: https://github.com/marketplace/actions/generate-github-release-notes
  - Relevant note: GitHub Marketplace explicitly recommends `softprops/action-gh-release@v2` and documents `generate_release_notes` behavior. The project release history also shows an `overwrite_files` input was added in the v2 line.

## Applied in EntireContext

- Workflow adds a dedicated `release` job after `publish`
- Upload scope is limited to:
  - `dist/*.whl`
  - `dist/*.tar.gz`
- Existing release assets can be safely re-uploaded with overwrite enabled
