# Deviation: git hook installation safety

**Date:** 2026-08-11
**Author:** implementation session for PR #205
**Authorized by:** user, during PR #205 review round 1

## Original contract

Governing artifacts, both approved before implementation:

- Spec: `docs/specs/2026-08-11-init-installs-hooks-design.md` (`status: approved`)
- Plan: `docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md` (`status: approved`, sealed)

The spec's Scope/Out section excludes changing `ec enable` and changing what a hook does.
The plan's U1 mandates that `enable()`'s installation body move into the shared helper
"verbatim — same statements, same order, same console messages, same conditional nesting."
`_install_git_hooks()` was named as a consumed interface, not as something to modify. SC4
declares that no existing test in `tests/test_project_cmds.py` or
`tests/test_e2e_hooks_install.py` may be modified.

## Observable behavior that deviates

Three changes fall outside that contract. All three are in `_install_git_hooks()` and its
new sibling `_resolve_hooks_dir()`, and all three are observable through `ec enable` as well
as `ec init`.

1. **Foreign hooks are preserved.** An existing `post-commit` or `pre-push` that does not
   contain the `EntireContext` marker is now left in place with a warning. It was previously
   overwritten.
2. **The hooks directory is resolved, not assumed.** `git rev-parse --git-path hooks`
   replaces the hardcoded `<repo>/.git/hooks`. When resolution fails, installation is
   skipped with an explicit warning instead of returning an empty list silently.
3. **Four existing tests were modified**, contrary to SC4. `TestGitHooksInstallation`
   constructed fake repositories (`mkdir` of a `.git/hooks` path with no `git init`), which
   `git rev-parse` correctly refuses to treat as a repository. They now call
   `git init`. This is a fixture upgrade, not an assertion change: no assertion was
   weakened, removed, or retargeted, and the repository's own testing guidance calls for
   real git repos.

## Why

Both defects predate this change and neither was introduced by it. What this change did was
widen their blast radius: installation moved from `ec enable`, which a user runs
deliberately, to `ec init`, which the documentation now presents as the single first command
every new user runs in every repository.

Defect 1 is data loss. Reproduced before fixing: a repository with a custom `pre-push` hook,
then `ec init` — the custom hook's contents were replaced by EntireContext's script with no
warning and no backup. Under the old flow this required an explicit `ec enable`; under the
new flow it happens during setup.

Defect 2 is a silent no-op. Reproduced in this repository's own linked worktree, where
`.git` is a file: `Path(repo)/".git"/"hooks"` is not a directory, so `_install_git_hooks`
returned `[]` and `ec init` reported success having installed no git hooks.

## Evidence

| Claim | Command | Observed |
|---|---|---|
| Foreign hook destroyed before the fix | `ec init` in a temp repo whose `pre-push` contained `# my precious custom hook` | `custom hook survived: False`; content replaced with `# EntireContext: sync on push...` |
| Worktree resolution broken before the fix | `python3 -c "print((Path('.git')/'hooks').is_dir())"` in `.worktrees/init-installs-hooks` | `False`; `.git` is an 84-byte ASCII file |
| Both fixed | `uv run python -m pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | 49 passed, including `test_install_preserves_foreign_hooks` and `test_install_resolves_hooks_dir_in_linked_worktree` |

## Traceability

- Raised by: PR #205 review comments `3755765241` (P1) and `3755765246` (P2)
- ADR: `docs/adr/0005-init-installs-integrations.md`
- EC decision: `83213b14-31a0-4b1f-9a42-a0aa0929a6f4`
- Scope decision: the user was presented with fix-now / separate-PR / decline for each defect
  and chose fix-now for both.
