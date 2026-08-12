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

PR #214 fixed MD024 duplicate headings in `LESSONS.md` by appending an assessment-ID suffix
to each heading (`src/entirecontext/core/futures.py:176`). One day later the file appeared in
`git status` with uncommitted changes that removed every suffix — the merged fix undoing
itself.

The repository source was correct. The `ec` that the agent hooks invoke is a uv tool install
at `~/.local/share/uv/tools/entirecontext`, and that install predated PR #214. Hook-driven
`auto_distill` therefore regenerated `LESSONS.md` with the pre-fix code and silently reverted
a shipped change.

Both copies reported version `0.14.0`.

## Guidance

Treat the globally installed CLI as a **second copy of the code with no provenance link to
the checkout**. In a repo that dogfoods its own tool through hooks, the code that runs is not
the code you edited or reviewed.

1. When a merged fix appears to revert itself in a generated or hook-written file, resolve
   which binary produced the file *before* diagnosing the source. `which -a <cmd>`, then read
   the shebang, then locate the package with
   `<that-python> -c 'import <pkg>, os; print(os.path.dirname(<pkg>.__file__))'`, then grep
   the fixed line inside *that* directory.
2. Do not use the version string as the drift check. Same-version drift is the normal case:
   a global install made before a fix and the checkout after it both report the last released
   version, so any `__version__` comparison passes while the code differs.
3. Detect drift by provenance, not version. Stamp the git SHA at build time and have the
   tool's `doctor` command compare that stamp against `git rev-parse HEAD` for the repository
   it is running in.
4. Reinstall from the checkout after merging anything the hooks execute
   (`uv tool install --force .`), and verify the fixed line is present in the installed
   package rather than assuming the reinstall took.
5. Prefer stamping over routing hooks through `uv run` in the checkout. Routing fixes the
   developer-machine problem by changing behavior for every user, including those who
   deliberately installed the tool outside a checkout.

### Capture the broken state before repairing it

The repair destroys the measurement. Running `uv tool install --force .` overwrote the stale
package before its source revision was recorded, so the staleness window could only be bounded
at one end: the fix merged at 03:09Z, one hook-driven regeneration ran at 03:35Z, the reinstall
happened around 05:47Z. How long the install had been stale before the fix is unrecoverable.

When a defect is found in a mutable environment — an installed package, a cache, a running
container, a database row — record its identifying state first, then repair.

## Why this matters

Every check that exists compares the repository against itself: tests run from the checkout,
CI builds from the branch, review reads the diff. None of them observe the artifact the hooks
actually execute. A fix can pass review, pass CI, merge, and still not take effect in the one
environment whose output lands back in the repository.

The failure is also self-concealing. The stale tool rewrites the generated file on every run,
so the evidence of the drift looks like an ordinary uncommitted change — noise to be reverted
rather than a signal that the shipped fix is inert.

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
