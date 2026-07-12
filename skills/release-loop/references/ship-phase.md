# Ship Phase

Push the branch, create a PR, handle CI and review comments, and merge.

## Entry Condition

Review clean (from Review phase): no Critical or Important findings remain.

## Exit Condition

PR merged.

## Gate

- **Default:** USER — present the PR and ask for merge approval
- **`--auto` mode:** AUTO when CI passes + no open Critical review comments → auto-merge

## Protocol

### Step 1: Push to Remote

```bash
git push -u origin <branch-name>
```

If push fails (e.g., no remote, auth issue): escalate to user.

### Step 2: Create PR

Generate PR title and body from the spec and implementation:

```bash
gh pr create --title "<type>(scope): <subject>" --body "$(cat <<'EOF'
## Summary
- [1-3 bullet points from spec]

## Changes
- [Key implementation details]

## Test plan
- [ ] [Test verification steps]

---
Driven by release-loop skill
EOF
)"
```

**PR title:** under 70 characters, conventional commit format.
**PR body:** concise — the spec and plan are linked, not reproduced.

Record the PR number in `.release-loop/progress.md`:
```
PR: 190
```

### Step 3: Monitor CI

```bash
gh pr checks <PR-number> --watch
```

If CI passes: proceed to Step 5.
If CI fails: proceed to Step 4.

### Step 4: CI Failure Auto-Fix

For each CI failure (up to **3 attempts**):

1. Read the failure log:
   ```bash
   gh run view <run-id> --log-failed
   ```

2. Diagnose the root cause:
   - Test failure → read the test, read the code, fix
   - Lint/type error → fix the specific error
   - Build failure → check dependencies and config

3. Dispatch a fix subagent with:
   - The failure log
   - The relevant source files
   - Instructions to fix and re-run locally before committing

4. Push the fix:
   ```bash
   git push
   ```

5. Wait for CI to re-run

**After 3 failed attempts:** escalate to user with a summary of what was tried.

**From v0.13.0 retro — common CI pitfalls:**
- `bool(x)` doesn't narrow `str | None` for mypy — use `x is not None`
- Rich/Typer ANSI escapes in subprocess stdout on CI — strip with `re.compile(r"\x1b\[[0-9;]*m")`
- Always run `mypy --strict` on changed files locally before pushing

### Step 5: Handle Review Comments

Monitor for PR review comments:

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments
```

**Comment handling protocol:**

1. Fetch ALL review comments — never work from a summarized subset
2. Create a 1:1 checklist of comment IDs before editing code
3. For each comment:
   - Assess severity (Critical, Important, Minor, Suggestion)
   - Critical/Important → fix immediately
   - Minor/Suggestion → fix if cheap, otherwise defer with rationale
4. Commit fixes referencing comment IDs:
   ```
   fix(scope): PR #N review round M — #discussion_rXXX, #discussion_rYYY
   ```
5. Push and wait for new comments

**Round cap:** Up to **4 review-comment rounds**. After round 4:
- Batch any remaining unfixed comments with rationale
- List deferred items in the PR body or a comment
- Proceed to merge

**From v0.13.0 retro:** The auto-fix loop worked across 6 rounds (25 comments, 20 fixed), but each fix push triggered new findings on changed code. Cap at 3-4 rounds then batch is the practical sweet spot. Unbounded loops converge but are expensive.

**Verification before claiming "all resolved":**
- Re-fetch the comments list via API
- Verify every comment ID is either addressed or has an explicit deferred rationale
- Never claim resolution from memory or commit-message summary

### Step 6: Merge

**Default gate (USER):**

Present to user:
```
PR #N ready to merge:
- CI: ✅ passing
- Review comments: X fixed, Y deferred
- Deferred items: [list]

Merge?
```

Wait for approval. On approval:

```bash
gh pr merge <number> --squash --delete-branch
```

**Auto gate (`--auto`):**

Auto-merge when:
- CI passes
- No open Critical review comments
- All Important comments addressed or explicitly deferred

```bash
gh pr merge <number> --squash --delete-branch --auto
```

### Step 7: Release Commit + Tag

After merge, create a separate release commit on the base branch:

```bash
git checkout $BASE_BRANCH
git pull origin $BASE_BRANCH

# Version bump
# - pyproject.toml: version = "X.Y.Z"
# - src/<pkg>/__init__.py: __version__ = "X.Y.Z"
# - CHANGELOG.md: rename [Unreleased] section to [X.Y.Z] - YYYY-MM-DD
# - uv.lock (regenerate if needed)

git add pyproject.toml src/<pkg>/__init__.py CHANGELOG.md uv.lock
git commit -m "chore(release): vX.Y.Z — <theme>

Assisted-By: Claude Code <noreply@anthropic.com>"

git tag vX.Y.Z
git push origin $BASE_BRANCH vX.Y.Z
```

**Why separate:** keeps feature work revertable independently from release ceremony; tag always points to a clean release commit; matches PyPI immutability (v0.9.3 lesson).

**From v0.13.1 retro:** including version bump in the feature PR created git history ambiguity and rebase noise. Separate release commit is the project standard since v0.13.0.

### Step 8: Update Progress

```
Phase: ship
PR: <number>
CIAttempts: N
ReviewRounds: M
CommentsFixed: X
CommentsDeferred: Y
Merged: true
Tag: vX.Y.Z
```

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Run unbounded review-fix loops | Cap at 4 rounds, then batch |
| Claim comments resolved from memory | Re-fetch via API and verify |
| Fix one comment per commit | Batch related fixes per round |
| Skip CI failure diagnosis | Read the log, understand the root cause |
| Force-push to fix CI | Regular push with fix commits |
| Auto-merge with Critical comments open | Always require Critical resolution |
| Dismiss review findings as "noise" | Every acted-on comment was a legitimate issue |
