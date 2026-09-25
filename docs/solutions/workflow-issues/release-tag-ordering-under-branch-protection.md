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

The release process in `docs/RELEASE.md` requires all pre-release checks to pass before an operator pushes a tag.
Continuous integration (CI) then publishes to the Python Package Index (PyPI) and GitHub Release.
Branch protection became active on `main` on 2026-04-16.
After branch protection became active, it rejected direct pushes to `main` with `GH006: Protected branch update failed`.
`RELEASE.md` did not reflect this constraint.

During the v0.16.1 patch release, the operator pushed tag `v0.16.1` before the release commit existed on `origin/main`.
CI ran from the tag ref and succeeded.
The commit was reachable only through the tag until a follow-up pull request (PR) landed it on `main`.

## Guidance

Under branch protection, merge the release commit into the target branch through a pull request. The commit includes a version bump and a CHANGELOG entry. Push the tag only after the pull request merges.

1. Create a release branch from `main` (for example, `release/v0.16.1`).
2. Commit the version bump (`pyproject.toml`, `__init__.py`) and the CHANGELOG entry.
3. Push the release branch. Open a pull request (PR) against `main`.
4. Wait for CI to pass on the PR.
5. Merge the PR (use `--admin` if auto-merge is disabled).
6. Pull the merged `main` branch locally.
7. Tag the merge commit: `git tag v0.16.1`.
8. Push the tag: `git push origin v0.16.1`.

## Why this matters

A tag creates three risks when its commit does not exist on the target branch:

- **Orphaned tag**: If CI fails during a build from the tag ref, the tag points to a commit that no branch can reach. Delete the tag manually with `git push --delete origin v0.16.1`. Create the tag again.
- **PyPI immutability**: If CI publishes the release to PyPI before the merge fails, the version number is permanently consumed. The next attempt requires a version bump (for example, 0.16.2).
- **Release note confusion**: GitHub's auto-generated release notes compare against the previous tag on the default branch. A tag that is not on `main` produces incorrect or empty diffs.

## When to apply

- Any repository with branch protection that blocks direct pushes to the
  release target.
- Any continuous integration and continuous delivery (CI/CD) pipeline triggered by tag pushes (not branch pushes).
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
