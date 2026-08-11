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

Ten behavior changes fall outside that contract, plus one test-fixture change recorded
separately below. They live in `_install_git_hooks()`, its new sibling `_resolve_hooks_dir()`,
the Claude settings merge, or `init()`'s option handling, and all are observable through
`ec enable` as well as `ec init` except item 6, which is `ec init`-only.

1. **Foreign hooks are preserved.** An existing `post-commit` or `pre-push` that does not
   contain the `EntireContext` marker is now left in place with a warning. It was previously
   overwritten.
2. **The hooks directory is resolved, not assumed.** `git rev-parse --git-path hooks`
   replaces the hardcoded `<repo>/.git/hooks`. When resolution fails, installation is
   skipped with an explicit warning instead of returning an empty list silently. The
   resolved directory is created when it does not exist.
3. **`core.hooksPath` disables git hook management.** When that config is set, both
   installation and removal are skipped; installation warns.
4. **The executable path is shell-quoted in the generated git hook scripts.** Item 8 extends
   the same quoting to the Claude settings command once recognition no longer depended on the
   raw text.
5. **An owned hook that lost its executable bit gets it back.** Previously a file carrying
   the `EntireContext` marker was skipped before the `chmod`, so a hook copied through a
   filesystem that drops modes stayed at 0644 and git never ran it.
6. **`--agent` is no longer validated on the `--no-hooks` path.** The approved spec says
   `--no-hooks` supersedes `--agent`, so `ec init --no-hooks --agent bogus` now initializes
   the database instead of exiting 2. Validation still runs before `init_project()` on the
   installing path, preserving the plan's fail-fast requirement.
7. **Claude hook groups keep their sibling commands.** `_strip_ec_hooks()` now removes only
   the matching inner command; the previous filter discarded a whole matcher entry when any
   nested command was ours, deleting another tool's hook on reinstall.
8. **Claude hook commands are shell-quoted.** `_is_ec_command()` matches the raw string and
   the shlex-normalized string, so quoted new entries and unquoted existing ones are both
   recognized and `ec disable` keeps working across the change.

9. **`python -m entirecontext.cli` is runnable.** The installer falls back to this form when
   the `ec` console script is not on PATH, but `entirecontext.cli` had no `__main__.py`, so
   every generated hook exited with `No module named entirecontext.cli.__main__` — capture
   never ran and the failing `pre-push` hook blocked every push. A `__main__.py` now invokes
   the Typer app.
10. **`ec.exe` is recognized as our command.** On Windows the console script resolves to
   `ec.exe`, which the substring match missed, so `ec disable` could not remove the hook and
   every reinstall appended a duplicate. `_is_ec_command()` now also tokenizes the command
   and compares the executable by name, trying both POSIX and non-POSIX splits because the
   first eats Windows backslashes and the second leaves quotes attached.

### Test-fixture change (SC4)

Four existing tests were modified, contrary to SC4. `TestGitHooksInstallation`
constructed fake repositories (`mkdir` of a `.git/hooks` path with no `git init`), which
`git rev-parse` correctly refuses to treat as a repository. They now call
`git init`. This is a fixture upgrade, not an assertion change: no assertion was
weakened, removed, or retargeted, and the repository's own testing guidance calls for
real git repos.

## Why

The two round-1 defects predate this change; the round-2 `core.hooksPath` hazard did not — see
the self-inflicted note below. What this change did to the pre-existing pair was widen their
blast radius: installation moved from `ec enable`, which a user runs
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
| Hooks dir missing after an empty-template init | `git init --template=<empty-dir>`, then `_resolve_hooks_dir(repo)` | `.git/hooks exists: False`; resolver returned `None` while `git rev-parse` returned the valid path `.git/hooks` |
| `core.hooksPath` made two repositories share one directory | two repos each `git config core.hooksPath <shared>`, then `_resolve_hooks_dir` on both | both returned the same `<shared>` path; the pre-change code used `<repo>/.git/hooks` and never followed `core.hooksPath` |
| Empty `core.hooksPath` read as unset | `git config core.hooksPath ""`, then `_has_custom_hooks_path(repo)` | `git config --get` exits 0 with `'\n'`; the truthiness check returned `False` and `_resolve_hooks_dir` resolved to the repository root |
| Quoted command still recognized | `shlex` round-trip over 5 command shapes | raw match missed both quoted forms; the shlex-normalized match caught all four EC forms and rejected `some-other-tool run` |
| Fallback module runs | `uv run python -m entirecontext.cli --help` | before: `No module named entirecontext.cli.__main__`; after: exit 0 with the usage banner |
| All fixed | `uv run python -m pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | 74 passed; full suite 2147 passed / 1 skipped (18 pre-existing local Rich-console failures, identical on the unmodified tree) |

## Round 2 note: one deviation was self-inflicted

The `core.hooksPath` sharing hazard was **introduced by this PR's own round-1 fix**, not
inherited. Before that fix, `_install_git_hooks` hardcoded `<repo>/.git/hooks` and therefore
never followed `core.hooksPath`, so cross-repository deletion was impossible. Resolving the
hooks directory through git — necessary to fix the linked-worktree no-op — made it possible.
Round 2 closes it by refusing to manage hooks at all when `core.hooksPath` is set.

## Traceability

- Raised by: PR #205 review comments `3755765241` (P1) and `3755765246` (P2) in round 1;
  `3755884180` (P1), `3755884172` (P2), and `3755884176` (P2) in round 2;
  `3755985910` (P2) and `3755985915` (P2) in round 3; `3756069218` (P2), `3756069221` (P1),
  and `3756069214` (P2) in round 4; `3756118788`, `3756118790`, and `3756118795` in round 5;
  `3756252088` (P2) in round 6; `3756297185` (P1) and `3756297182` (P2) in round 7
- ADR: `docs/adr/0005-init-installs-integrations.md`
- EC decision: `83213b14-31a0-4b1f-9a42-a0aa0929a6f4`
- Scope decision: the user was presented with fix-now / separate-PR / decline for each defect
  and chose fix-now every time, including at the merge gate for the two Claude-hook findings
  that had been deferred at the review round cap.
