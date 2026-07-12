# Plan Phase

Turn an approved spec into a task-by-task implementation plan with exact file paths, code, and test commands.

## Entry Condition

Spec file committed and user-approved (from Design phase, or provided via `--skip-design --spec <path>`).

## Exit Condition

Plan file committed to git.

## Gate

AUTO — plan commits automatically after self-review passes.

## Protocol

### Step 1: Deliverable Type Detection

Read the spec and classify:

- **Code**: source code changes, new modules, API changes, schema migrations, CLI commands
- **Non-code**: documentation, skill files, config files, markdown-only deliverables

Record the type in `.release-loop/progress.md` as `DeliverableType: code|non-code`.

This determines task structure in Step 4.

### Step 2: File Structure

Before defining tasks, map out which files will be created or modified:

```markdown
## File Structure

**Create:**
- `src/module/new_file.py` — [responsibility]
- `tests/test_new_file.py` — [what it tests]

**Modify:**
- `src/module/existing.py` — [what changes and why]
- `src/db/schema.py` — [schema version bump]
```

Design rules:
- Each file has one clear responsibility
- Files that change together live together
- Split by responsibility, not by technical layer
- Follow existing codebase patterns
- Prefer smaller, focused files over large monoliths

### Step 3: Task Decomposition

Break the work into tasks. Each task is the smallest unit that:
- Carries its own test cycle (code) or review cycle (non-code)
- Produces an independently verifiable deliverable
- Is worth a fresh reviewer's gate

**Right-sizing rules:**
- Fold setup/scaffolding into the task that needs it
- Split only where a reviewer could meaningfully reject one task while approving its neighbor
- Each task ends with a commit
- **Version bump and CHANGELOG finalization do NOT belong in the PR** — they are post-merge Ship phase work (release commit + tag). Do not create a "version bump" task in the plan.

**Task count guidance:**
- 3-7 tasks is typical for a medium feature
- More than 10 tasks suggests the feature needs decomposition
- Fewer than 3 tasks suggests the tasks are too coarse

### Step 4: Task Structure

#### Code Tasks (TDD)

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: [exact signatures from earlier tasks]
- Produces: [exact function names, parameter and return types for later tasks]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat(scope): add specific feature"
```
````

#### Non-Code Tasks (Write-Review-Commit)

````markdown
### Task N: [Deliverable Name]

**Files:**
- Create: `exact/path/to/file.md`
- Modify: `exact/path/to/existing.md`

**Interfaces:**
- Depends on: [earlier tasks that produce content this task references]
- Referenced by: [later tasks that read this deliverable]

- [ ] **Step 1: Write deliverable**

[Exact content or content structure with examples]

- [ ] **Step 2: Self-review against spec**

Check:
- [ ] All spec requirements covered
- [ ] No placeholders or TODOs
- [ ] Internal consistency with other deliverables
- [ ] Correct file paths and cross-references

- [ ] **Step 3: Commit**

```bash
git add exact/path/to/file.md
git commit -m "docs(scope): add deliverable description"
```
````

### Step 5: Plan Document Header

Every plan starts with:

```markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

**Deliverable Type:** code | non-code

## Global Constraints

[Project-wide requirements — version floors, dependency limits,
naming rules, platform requirements. One line each, exact values
copied verbatim from the spec.]

---
```

### Step 6: No Placeholders

Every step must contain the actual content. These are plan failures:

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the content)
- Steps that describe what to do without showing how
- References to types, functions, or methods not defined in any task

### Step 7: Self-Review

After writing the complete plan:

1. **Spec coverage** — skim each spec requirement, point to the task that implements it. List gaps.
2. **Placeholder scan** — search for red flags from Step 6. Fix them.
3. **Type consistency** — do types, signatures, property names match across tasks?
4. **Callers + invariants** — for code tasks: who calls the functions you're changing? What invariants must hold? (From v0.13.0 retro: plans must include callers and invariants check.)
5. **Prior retro carryover** — are there carry-forward items from the last retrospective that this plan should address?

Fix issues inline. No separate review pass.

### Step 8: Independent Review

Get a review of the plan before committing:

- Dispatch a reviewer subagent or use `advisor` if available
- Focus: spec coverage, placeholder detection, type consistency, missing edge cases

**From v0.13.0 retro:** Advisor caught a `_stream_commits` parsing bug and a `schema.py` TABLES gap in the plan. Plan review prevents implementation rework.

### Step 9: Save and Commit

Save to: `docs/plans/YYYY-MM-DD-<feature-name>.md`

(Or the project's preferred plan location.)

```bash
git add docs/plans/YYYY-MM-DD-<feature-name>.md
git commit -m "docs(plan): <feature-name> implementation plan"
```

Update `.release-loop/progress.md`:
```
Plan: docs/plans/YYYY-MM-DD-<feature-name>.md
```

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Write vague steps ("handle edge cases") | Show exact code for every step |
| Reference "see Task N" for repeated logic | Repeat the code — reader may see tasks out of order |
| Create one mega-task | Split into 3-7 independently testable tasks |
| Skip the Interfaces block | Every task declares what it consumes and produces |
| Assume the implementer knows the codebase | Provide exact file paths, line ranges, signatures |
| Skip plan review | Advisor/reviewer catches type mismatches and missing cases |
