# Retro Phase

Collect release data, derive findings, register carry-forward items, and commit a retrospective document.

## Entry Condition

PR merged (from Ship phase).

## Exit Condition

Retro document committed to git.

## Gate

AUTO — advances to Done after retro is committed.

## Protocol

### Step 1: Collect Release Data

Gather quantitative data from git and the PR:

```bash
# Code delta
git diff --stat $(git merge-base $BASE_BRANCH HEAD~1)..HEAD~1

# Commit count
git log --oneline $(git merge-base $BASE_BRANCH HEAD~1)..HEAD~1 | wc -l

# PR data
gh pr view <number> --json title,body,additions,deletions,changedFiles,reviews,comments
```

**Data to collect:**

| Metric | How |
|--------|-----|
| Code delta (product / test / docs split) | `git diff --stat` + classify by path |
| Test count (new + total) | grep test functions in diff + run test suite |
| Review rounds | count review-comment fix commits |
| Comment count (fixed / deferred) | from Ship phase progress data |
| CI failure count | from Ship phase progress data |
| Time from start to merge | first spec commit to merge timestamp |
| Task count | from plan + progress data |

**Split code delta into categories:**
- **Product code**: `src/` excluding tests
- **Test code**: `tests/` and test files
- **Docs/config**: `docs/`, `*.md`, config files, plans, specs

### Step 2: Check Carry-Forward Items

Read the previous retro document (if it exists) and check each carry-forward item:

```
| Item | Status |
|------|--------|
| <item from previous retro> | ✅ Done / ⏳ In progress / ❌ Not started |
```

For each item, cite the evidence (commit, PR, file) that confirms its status.

**From v0.13.0 retro:** All 8 v0.11.0 carry-forward items were closed via v0.12.0 graduation. Tracking carry-forward items across releases prevents silent drops.

### Step 3: Derive Findings

Each finding has three parts:

1. **What happened** — the observation
2. **Why** — the root cause or contributing factor
3. **How to apply** — actionable guidance for the next release

Organize findings into:

#### What Worked Well

Things to keep doing. Look for:
- Process steps that caught real issues
- Tools or patterns that saved time
- Decisions that paid off

#### What to Improve

Things to change. Look for:
- Steps that were skipped or felt wasteful
- Issues that slipped through to late stages
- Repeated problems from previous retros (patterns)

#### Process Observations

Meta-observations about the release process itself. Look for:
- How well the release-loop skill worked
- Phase transition friction
- Tool/automation gaps

**Finding quality bar:**
- Every finding must be specific (cite the PR comment, the CI failure, the review round)
- "Tests caught bugs" is too vague; "Final branch review caught the commit-message threading bug (Critical) that 5 task reviewers missed" is specific
- Never frame resolved review findings as "noise" or "trivial"

### Step 4: Register Carry-Forward Items

Items that were deferred, discovered but not addressed, or need follow-up:

```markdown
## Carry-Forward to Next Release

| Item | Type | Priority |
|------|------|----------|
| <description> | architecture / performance / feature / edge case / process | P1-P4 |
```

**Priority guide:**
- P1: blocks next feature or causes user-facing issues
- P2: architecture improvement needed before scope grows
- P3: nice-to-have, do when touching adjacent code
- P4: extreme edge case, track but don't prioritize

**From v0.13.0 retro:** Deferred items must go to ROADMAP or an equivalent tracking system, not just PR comments. PR comments get lost after merge.

### Step 5: Record Lessons

Distill the most important learnings into quotable lessons:

```markdown
## Lessons

**"<lesson title>"** — <one-sentence explanation with specific evidence>
```

Good lessons are:
- Specific to what happened (not generic advice)
- Backed by evidence from this release
- Actionable for the next release
- Surprising or non-obvious (not "testing is good")

**From v0.13.0 retro lessons (examples of good form):**
- "Two-level review (task + branch) catches integration bugs that single-level misses"
- "Advisor before implementation prevents architecture-level rework"
- "Auto-fix loops converge but need round caps"
- "Maturity improvement requires usage, not infrastructure"

### Step 6: Write Retro Document

Save to: `docs/retros/YYYY-MM-DD-<feature-name>-retro.md`

(Or the project's preferred retro location.)

Structure:

```markdown
# <Feature Name> Retrospective

_Released YYYY-MM-DD (PR #N)._

## Scope & Delivery

| Item | Result |
|------|--------|
| <deliverable> | Shipped / Partial / Deferred |
| Code delta | +X/-Y lines (product Z%, test W%, docs V%) |
| Tests | N new, M total |
| PR #N | R review rounds, C comments (F fixed / D deferred) |
| CI failures | N |
| Duration | start to merge |

## Previous Carry-Forward Status

[from Step 2]

## Key Findings

### 1. [Finding title]

[observation]

**Why:** [root cause]

**How to apply:** [actionable guidance]

### 2. [Finding title]
...

## Carry-Forward to Next Release

[from Step 4]

## Lessons

[from Step 5]
```

### Step 7: Commit and Advance

```bash
git add docs/retros/YYYY-MM-DD-<feature-name>-retro.md
git commit -m "docs(retro): <feature-name> retrospective"
git push
```

Update `.release-loop/progress.md`:
```
Phase: done
```

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Write vague findings ("things went well") | Cite specific PR comments, CI failures, review rounds |
| Skip carry-forward tracking | Every deferred item gets registered |
| Leave carry-forward items only in PR comments | Register in retro doc + project tracking system |
| Write generic lessons ("testing is important") | Specific, evidence-backed, surprising lessons |
| Skip previous carry-forward status check | Verify each item from the last retro |
| Frame review findings as "noise" | Every acted-on comment was legitimate |
| Omit the Why/How to apply | Findings without context can't improve the next release |
