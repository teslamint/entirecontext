---
module: dogfooding-environment
date: 2026-08-12
problem_type: developer_experience
component: cli-tool-install
severity: high
applies_when:
  - "A repository dogfoods its own CLI by invoking it from git or agent hooks"
  - "The CLI is installed globally (uv tool, pipx, npm -g) rather than run from the checkout"
  - "A merged fix appears to revert itself in a generated or hook-written file"
  - "Two copies of the same package report the same version string"
tags:
  - dogfooding
  - install-provenance
  - hooks
  - generated-files
  - uv-tool
  - same-version-drift
---

# The installed tool is a second copy of the code

## Context

Pull request (PR) #214 fixed MD024 duplicate headings in `LESSONS.md`.
The fix added an assessment identifier (ID) suffix to each heading (`src/entirecontext/core/futures.py:176`).
One day later, `git status` showed uncommitted changes in the file.
These changes removed every suffix.
They undid the merged fix.

The repository source was correct.
Agent hooks invoked `ec` from the uv tool install at `~/.local/share/uv/tools/entirecontext`.
That install predated PR #214.
Hook-driven `auto_distill` regenerated `LESSONS.md` with the pre-fix code.
The regeneration silently reverted a shipped change.

Both copies reported the version `0.14.0`.

## Guidance

Treat the globally installed command-line interface (CLI) as **another code copy without a provenance link to the checkout**. In a repository that uses its own tool through hooks, the code that runs is not the code you edited or reviewed.

1. When a merged fix appears to revert itself, first identify which binary produced the generated or hook-written file. Run `which -a <cmd>`. Read the shebang. Locate the package with `<that-python> -c 'import <pkg>, os; print(os.path.dirname(<pkg>.__file__))'`. Grep the fixed line in that directory.
2. Do not use the version string as the drift check. Same-version drift is the normal case. A global install made before a fix and the checkout after it both report the last released version. As a result, any `__version__` comparison passes even when the code differs.
3. Detect drift by provenance, not by version. Stamp the git commit hash at build time. Make the tool's `doctor` command compare that stamp with `git rev-parse HEAD` for the repository where it runs.
4. Reinstall from the checkout after you merge changes to code that hooks execute: `uv tool install --force .`. Verify that the fixed line appears in the installed package. Do not assume that the reinstall succeeded.
5. Prefer a provenance stamp to a route that runs hooks through `uv run` in the checkout. This route fixes the developer-machine problem. It changes behavior for every user, including users who deliberately installed the tool outside a checkout.

### Capture the broken state before repairing it

The repair destroys the measurement.
The `uv tool install --force .` command overwrote the stale package before anyone recorded its source revision.
As a result, the staleness window has only one known end.

The fix merged at 03:09Z.
One hook-driven regeneration ran at 03:35Z.
The reinstall happened around 05:47Z.
No one can recover how long the install had been stale before the fix.

When you find a defect in a mutable environment, record its identifying state before you repair it. Examples include an installed package, a cache, a running container, or a database row.

## Why this matters

Every existing check compares the repository against itself.
Tests run from the checkout.
Continuous integration (CI) builds from the branch.
Reviewers read the diff.
None of these checks observes the artifact that the hooks actually execute.

A fix can pass review.
It can pass CI.
It can merge.
It can still fail to affect the environment whose output returns to the repository.

The failure also hides itself.
The stale tool rewrites the generated file on every run.
As a result, the evidence of drift looks like an ordinary uncommitted change.
That change looks like noise to revert, not a signal that the shipped fix does not work.

## When to apply

- A repository whose own hooks call its own CLI.
- Any generated or tool-written file tracked in git.
- Investigating a change that "reverted itself" after merge.
- Deciding what a `doctor`-style health command should verify.
- Immediately after merging a change to code that hooks execute.

## Example

```
$ which -a ec
/Users/x/.local/bin/ec
$ head -1 /Users/x/.local/bin/ec
#!/Users/x/.local/share/uv/tools/entirecontext/bin/python3
$ grep -c "a\['id'\]\[:8\]" \
    /Users/x/.local/share/uv/tools/entirecontext/lib/python3.13/site-packages/entirecontext/core/futures.py
0                      # the fix is absent from the code that actually runs
$ grep -c "a\['id'\]\[:8\]" src/entirecontext/core/futures.py
1                      # and present in the code that was reviewed

$ uv tool install --force .
$ grep -n "a\['id'\]\[:8\]" \
    /Users/x/.local/share/uv/tools/entirecontext/lib/python3.13/site-packages/entirecontext/core/futures.py
176:            lines.append(f"### {feedback_icon} {a.get('impact_summary', 'No summary')} ({a['id'][:8]})")
```

Both `ec --version` invocations reported `0.14.0`, before and after.
