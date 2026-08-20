---
module: release-process
date: "2026-08-21"
problem_type: workflow_issue
component: release-pipeline
severity: medium
applies_when:
  - "Repository has branch protection enabled on the release target branch"
  - "Release process involves pushing a git tag that triggers CI/CD"
  - "Direct pushes to the target branch are blocked"
tags:
  - release
  - branch-protection
  - tag-ordering
  - ci-cd
related_components:
  - docs/RELEASE.md
  - .github/workflows/release.yml
---

# Release tag ordering under branch protection

## Context

This project's release process (`docs/RELEASE.md`) prescribes: all
pre-release checks green, tag push, CI publishes (PyPI + GitHub Release).
The process was designed before branch protection was enabled on `main`
(2026-04-16). After protection was activated, direct pushes to `main` are
rejected with `GH006: Protected branch update failed`, but `RELEASE.md`
was never updated to reflect the new constraint.

During the v0.16.1 patch release, the operator pushed tag `v0.16.1` before
the release commit existed on `origin/main`. CI triggered from the tag ref
and succeeded, but the commit was reachable only via the tag itself until a
follow-up PR landed it on `main`.

## Guidance

Under branch protection, the release commit (version bump + CHANGELOG)
must reach the target branch via a pull request before the tag is pushed.

1. Create a release branch from `main` (e.g. `release/v0.16.1`).
2. Commit version bump (`pyproject.toml`, `__init__.py`) + CHANGELOG entry.
3. Push the release branch and open a PR against `main`.
4. Wait for CI to pass on the PR.
5. Merge the PR (use `--admin` if auto-merge is disabled).
6. Pull the merged `main` locally.
7. Tag the merge commit: `git tag v0.16.1`.
8. Push the tag: `git push origin v0.16.1`.

## Why this matters

Pushing a tag before the tagged commit exists on the target branch creates
three risks:

- **Orphaned tag**: if CI fails when building from the tag ref, the tag
  points to a commit unreachable from any branch. Manual deletion
  (`git push --delete origin v0.16.1`) and re-tagging is required.
- **PyPI immutability**: if the CI release publishes to PyPI before the
  merge fails, the version number is permanently consumed. The next attempt
  requires a version bump (e.g. 0.16.2).
- **Release note confusion**: GitHub's auto-generated release notes compare
  against the previous tag on the default branch. A tag not on `main`
  produces incorrect or empty diffs.

## When to apply

- Any repository with branch protection that blocks direct pushes to the
  release target.
- Any CI/CD pipeline triggered by tag pushes (not branch pushes).
- Especially when the registry (PyPI, npm, etc.) enforces version
  immutability.

## Examples

Before (broken under branch protection):

```bash
git commit -m "chore(release): v0.16.1"   # on main locally
git tag v0.16.1
git push origin main --tags               # FAILS: GH006
# tag is pushed, commit is not on origin/main
```

After (correct flow):

```bash
git checkout -b release/v0.16.1
git commit -m "chore(release): v0.16.1"
git push origin release/v0.16.1
gh pr create --base main --head release/v0.16.1 --title "chore(release): v0.16.1"
# wait for CI, then merge
gh pr merge <N> --merge --delete-branch --admin
git checkout main && git pull --ff-only
git tag v0.16.1
git push origin v0.16.1                   # tag points to a commit ON main
```
