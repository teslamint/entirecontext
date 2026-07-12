# Implement Phase

Execute the plan by dispatching a fresh subagent per task, reviewing after each, then running a final branch review.

## Entry Condition

Plan file committed (from Plan phase, or provided via `--skip-plan --plan <path>`).

## Exit Condition

All tasks complete. For code tasks: full test suite passes.

## Gate

AUTO — advances to Review phase when all tasks pass their reviews.

## Core Principle

Fresh subagent per task + per-task review (spec + quality) + final branch review = high quality, fast iteration.

**Why subagents:** Each task gets an agent with isolated context. You (the orchestrator) construct exactly what they need — task brief, interfaces, constraints. They never inherit session history. This keeps them focused and preserves your context for coordination.

**Continuous execution:** Do not pause between tasks. Execute all tasks without stopping. The only reasons to stop: BLOCKED status you cannot resolve, ambiguity that prevents progress, or all tasks complete.

## Protocol

### Step 1: Pre-Flight

1. Read the plan file once
2. Note global constraints and deliverable type (code vs non-code)
3. Check for existing progress in `.release-loop/progress.md`
4. If resuming: skip completed tasks (trust the progress file + `git log`)
5. Create or verify feature branch

**Pre-flight plan review:** Before Task 1, scan the plan for:
- Tasks that contradict each other or global constraints
- Requirements the review rubric would treat as defects

Present all conflicts as one batched question. If clean, proceed silently.

### Step 2: Per-Task Execution

For each task in the plan:

#### 2a. Prepare the Brief

Write the task's requirements to a file:

```
.release-loop/briefs/task-N-brief.md
```

The brief contains:
- The task's full text from the plan (exact values, signatures, test cases)
- Global constraints that bind this task
- Interfaces from earlier completed tasks (exact signatures, not summaries)

#### 2b. Dispatch Implementer

Spawn a fresh subagent with:

1. One line on where this task fits in the project
2. The brief file path ("read this first — it is your requirements")
3. Interfaces and decisions from earlier tasks the brief cannot know
4. Resolution of any ambiguity you noticed
5. The report file path (`.release-loop/reports/task-N-report.md`)

**Code tasks — implementer contract:**
- Follow TDD: failing test → implement → verify → commit
- Run the test suite for changed modules before committing
- Self-review the diff before reporting
- Write the report file with: status, commits, test summary, concerns
- Return only: status line + one-line test summary + concerns

**Non-code tasks — implementer contract:**
- Write the deliverable
- Self-review against the spec (coverage, placeholders, consistency)
- Commit the deliverable
- Write the report file with: status, commits, review notes
- Return only: status line + concerns

#### 2c. Handle Implementer Status

| Status | Action |
|--------|--------|
| DONE | Proceed to task review |
| DONE_WITH_CONCERNS | Read concerns. Correctness/scope issues → address before review. Observations → note and proceed. |
| NEEDS_CONTEXT | Provide missing context, re-dispatch |
| BLOCKED | Assess: context problem → re-dispatch with context; reasoning limit → re-dispatch with more capable model; task too large → break into sub-tasks; plan wrong → escalate to user |

**Never** force the same model to retry without changes.

#### 2d. Task Review

Generate a review package (the diff from before this task to after):

```bash
git diff <base-before-task>..<HEAD> > .release-loop/reviews/task-N-diff.txt
```

Dispatch a task reviewer subagent with:
- The brief file path
- The report file path
- The diff file path
- Global constraints (verbatim from plan)

The reviewer produces two verdicts:

1. **Spec compliance** — does the implementation match the task requirements?
2. **Code/deliverable quality** — is the implementation well-built?

Both verdicts required. Missing either = review incomplete.

#### 2e. Handle Review Results

**Spec ✅ + Quality approved:**
- Mark task complete in progress file
- Record in progress ledger
- Proceed to next task

**Spec ❌ or Quality issues (Critical/Important):**
- Dispatch a fix subagent with all findings
- Fix subagent re-runs covering tests and reports results
- Re-dispatch the reviewer
- Max 3 review-fix rounds per task → escalate to user

**Minor findings:**
- Record in `.release-loop/progress.md` under `MinorFindings:`
- Do NOT dispatch fixes for Minor findings during task review
- The final branch review triages which Minor findings must be fixed before merge

**⚠️ "Cannot verify from diff" items:**
- The reviewer may flag requirements that live in unchanged code
- You (the orchestrator) hold cross-task context the reviewer lacks
- Resolve each item yourself before marking the task complete
- If a gap is real, send it back to the implementer

**Plan-mandated findings:**
- A finding that conflicts with what the plan requires is the user's decision
- Present the finding and the plan text, ask which governs
- Do not dismiss findings because "the plan says so"

### Step 3: Progress Tracking

Track progress durably — conversation memory does not survive compaction.

**Progress ledger** in `.release-loop/progress.md`:

After each task's review passes, append:
```
Task N: complete (commits abc1234..def5678, review clean)
```

On resume, trust the ledger and `git log` over conversation memory. Tasks listed as complete are DONE — do not re-dispatch them.

**Commit progress updates** alongside task work (not separate commits).

### Step 4: Final Branch Review

After all tasks complete:

1. Generate the full branch diff:

```bash
git diff $(git merge-base $BASE_BRANCH HEAD)..HEAD > .release-loop/reviews/branch-diff.txt
```

2. Dispatch a final reviewer subagent with the **most capable model available**:
   - The branch diff file path
   - The spec file path
   - The accumulated Minor findings list
   - Global constraints

3. The final reviewer checks:
   - Cross-task integration (the main value — task reviewers only see their own diff)
   - Spec coverage across all tasks
   - Which Minor findings from task reviews need fixing
   - Any new issues visible only from the full branch diff

**From v0.13.0 retro:** The final branch review caught 1 Critical + 2 Important that all 5 task reviewers missed. The Critical was a commit message variable parsed but never threaded to the signal bundle — invisible to each task reviewer but obvious from the branch diff. Two-level review (task + branch) catches integration bugs that single-level misses.

4. Handle final review findings:
   - Dispatch ONE fix subagent with the complete findings list (not one fixer per finding)
   - Re-review after fixes (max 3 rounds)
   - If clean or only Minor remain: advance to Review phase

## Model Selection

| Task type | Model tier |
|-----------|-----------|
| Mechanical (clear spec, 1-2 files, complete code in plan) | cheapest |
| Integration (multi-file, pattern matching) | standard |
| Architecture/design judgment | most capable |
| Task review (small mechanical diff) | standard |
| Task review (complex/risky diff) | most capable |
| Final branch review | most capable (always) |
| Fix subagent | same tier as the original implementer |

Use the most specific agent role the harness provides. In Codex/OMX, always set `agent_type` and normally inherit the configured role model; override the model only for a concrete task-specific reason. In other harnesses, select the equivalent role and model tier explicitly when supported.

**Turn count beats token price.** Cheapest models often take 2-3× the turns on multi-step work, costing more overall. Use standard as the floor for reviewers and for implementers working from prose descriptions. Use cheapest only when the plan contains the complete code to write (transcription + testing).

## File Handoffs

Everything pasted into a dispatch prompt stays in your context for the rest of the session. Hand artifacts over as files:

| Artifact | File path |
|----------|-----------|
| Task brief | `.release-loop/briefs/task-N-brief.md` |
| Task report | `.release-loop/reports/task-N-report.md` |
| Task diff | `.release-loop/reviews/task-N-diff.txt` |
| Branch diff | `.release-loop/reviews/branch-diff.txt` |

A dispatch prompt describes one task, not the session's history. Do not paste accumulated prior-task summaries into later dispatches.

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Skip task review | Every task gets spec + quality review |
| Accept a review missing either verdict | Both spec compliance AND quality required |
| Dispatch multiple implementers in parallel | One at a time (conflicts) |
| Make a subagent read the whole plan | Hand it only its task brief |
| Ignore subagent questions | Answer before letting them proceed |
| Accept "close enough" on spec compliance | Spec issues = not done |
| Paste prior-task summaries into dispatch | Fresh context per subagent |
| Dispatch one fix subagent per final-review finding | ONE fixer with complete findings list |
| Skip progress ledger updates | Ledger is recovery map after compaction |
| Re-dispatch completed tasks after context loss | Trust ledger + git log |

## Graceful Interruption

If the session ends mid-implementation:

1. Progress file records which tasks are complete
2. Each completed task has commits in git
3. `git log` confirms actual state
4. Resume picks up at the first incomplete task

The ledger + git history are the recovery map. Conversation memory is ephemeral.
