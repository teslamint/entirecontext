# Review Phase

Final quality gate before shipping — a broad branch review with the most capable model.

## Entry Condition

All implementation tasks complete (from Implement phase).

## Exit Condition

Review clean: no Critical or Important findings remain.

## Gate

AUTO — advances to Ship phase when review passes.

## Relationship to Implement Phase

The Implement phase already runs a final branch review as its last step. The Review phase exists as a separate checkpoint to:

1. Catch issues that emerge after all fix rounds in Implement
2. Provide a clean gate between "code complete" and "ready to ship"
3. Allow the user to request additional review passes

If the Implement phase's final review came back clean, the Review phase can verify that state and advance immediately.

## Protocol

### Step 1: Generate Branch Diff

```bash
MERGE_BASE=$(git merge-base $BASE_BRANCH HEAD)
git log --oneline $MERGE_BASE..HEAD > .release-loop/reviews/final-log.txt
git diff --stat $MERGE_BASE..HEAD >> .release-loop/reviews/final-log.txt
git diff -U10 $MERGE_BASE..HEAD >> .release-loop/reviews/final-log.txt
```

### Step 2: Dispatch Reviewer

Use the **most capable model available**. Provide:

- The full diff file path (`.release-loop/reviews/final-log.txt`)
- The spec file path
- The plan file path
- Any Minor findings accumulated during Implement phase
- Project-specific review guidelines (from AGENTS.md, CLAUDE.md, or equivalent)

**Reviewer focus areas:**

1. **Correctness** — does the implementation match the spec?
2. **Integration** — do the pieces work together?
3. **Edge cases** — empty states, error paths, boundary conditions
4. **Contract consistency** — do docs/comments/specs match code behavior?
5. **Security** — no injection, no secret leakage, proper input validation
6. **Test coverage** — are the important paths tested?

**Reviewer should NOT flag:**
- Pre-existing issues unrelated to the change
- Issues that linting/testing tools already enforce
- Style preferences not codified in the project's rules
- Intentional behavior changes that align with the spec

### Step 3: Triage Findings

Categorize each finding:

| Severity | Action |
|----------|--------|
| Critical (correctness bug, data loss, security) | Must fix before merge |
| Important (missing error handling, contract mismatch) | Should fix before merge |
| Minor (readability, naming, minor optimization) | Record, fix if cheap, OK to defer |

### Step 4: Fix Dispatch

For Critical and Important findings:

1. Dispatch ONE fix subagent with the complete findings list
2. Fix subagent re-runs covering tests for each fix
3. Fix subagent reports: what was fixed, tests run, results

Do not dispatch one fixer per finding — that rebuilds context and re-runs suites redundantly.

### Step 5: Re-Review

After fixes:

1. Generate a new diff (just the fix commits)
2. Re-dispatch the reviewer with:
   - The fix diff
   - The original findings list (to verify each was addressed)
   - Any new context from the fix process

3. Repeat up to **3 rounds** total (review → fix → re-review)
4. After 3 rounds: if only Minor findings remain, advance to Ship
5. After 3 rounds with Critical/Important: escalate to user

### Step 6: Update Progress

```
Phase: review
ReviewRounds: N
FindingsFixed: X
FindingsDeferred: Y
```

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Use a cheap model for the final review | Most capable model — always |
| Dispatch one fixer per finding | ONE fixer with complete list |
| Skip re-review after fixes | Verify fixes actually work |
| Run unbounded review-fix rounds | Cap at 3 rounds |
| Flag pre-existing issues | Only review changes on this branch |
| Ignore Minor findings | Record them — Ship phase or retro tracks them |
