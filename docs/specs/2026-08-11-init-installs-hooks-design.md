---
title: ec init installs hooks
status: draft
date: 2026-08-11
schema: spec/v1
---

# ec init installs hooks Design

_Created 2026-08-11._

## Overview

`ec init` creates the repo-local database but installs nothing, so every new repo needs a
second command (`ec enable`) before capture works. This moves the whole installation step
into `ec init`, with `--no-hooks` as the opt-out. `ec enable` stays as the idempotent
re-install and repair path.

## User Scenarios

### S1: First-time setup in a new repo

A developer clones a repo and runs `ec init`. The command creates `.entirecontext/`,
registers the project, installs the Claude Code hooks, installs the git hooks, and
registers the MCP server. Capture works from the next agent session with no second command.

```
$ ec init
Initialized EntireContext in /path/to/repo
  Project: repo (a1b2c3d4...)
Hooks installed in .claude/settings.local.json
Git hooks installed: post-commit, pre-push
MCP server configured in ~/.claude/settings.json
```

### S2: Initialization without touching agent config

A CI job or a developer evaluating the tool wants the database only.

```
$ ec init --no-hooks
Initialized EntireContext in /path/to/repo
  Project: repo (a1b2c3d4...)
  Run ec enable to install Claude Code hooks.
```

### S3: Repairing a clobbered hook config

A developer's `.claude/settings.local.json` was overwritten by another tool. `ec doctor`
reports the missing hooks. `ec enable` reinstalls them without re-running any database
work. This is the flow `docs/entirecontext-project-manual.md:750` documents; it keeps
working unchanged.

### S4: Codex user

A Codex user runs `ec init --agent codex`. The command initializes the project, writes the
Codex notify entry to `~/.codex/config.toml`, and registers the MCP server — but installs
no Claude Code hooks and no git hooks. That asymmetry is exactly what
`ec enable --agent codex` does today (git hook installation is nested inside the claude
branch; MCP registration is not), and this change preserves it rather than correcting it.

### S5: Re-running init on an initialized repo

`ec init` is already idempotent at the database layer (`init_project()` reuses the existing
`projects` row). Hook installation is also idempotent (`ec enable` strips its own prior
entries before re-adding, and git hooks skip files already containing `EntireContext`).
Re-running `ec init` therefore converges instead of duplicating anything.

### S6: Hook installation fails mid-init

`~/.claude/settings.json` is malformed JSON, or `.claude/` is read-only. The database was
already created successfully, so `init` reports the failure as a warning, tells the user to
run `ec enable`, and exits 0. The user is not left with a half-message that claims success.

## Scope

### In

- `ec init` gains `--no-hooks`, `--no-git-hooks`, and `--agent` options.
- All four installation actions currently performed by `ec enable` move into the default
  `ec init` path: Claude Code hooks, git hooks, user-level MCP registration, and (under
  `--agent codex|both`) the Codex notify entry.
- Extraction of the installation body of `enable()` into one shared helper that both
  `init()` and `enable()` call.
- Hook-installation failures inside `init` degrade to a warning rather than aborting.
- Documentation updates: `README.md`, `docs/spec.md`, `docs/entirecontext-project-manual.md`.
- Tests for the new `init` behavior; existing `enable` tests must keep passing unchanged.

### Out

- Deprecating or removing `ec enable`. It stays, with unchanged behavior and unchanged
  flags.
- Changing `ec disable`.
- Changing what a hook does, its timeout values, or the hook wire format.
- Changing `init_project()` in `core/project.py`.
- A global (non-repo) install command.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| `init_project()` is idempotent — a second run reuses the existing `projects` row rather than inserting a duplicate | `rg -n "def init_project" -A 30 src/entirecontext/core/project.py` | `2026-08-11T14:40:00+09:00` | `SELECT id, name FROM projects WHERE repo_path = ?` branches to reuse when a row exists | Working tree at `bf790bc` |
| `ec init` has no test coverage today | `rg -n "def test.*init\|project_cmds.init" tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | `2026-08-11T14:45:00+09:00` | zero matches | Working tree at `bf790bc` |
| Hook-install tests isolate the home directory with `monkeypatch.setenv("HOME", ...)`, so a helper that writes `~/.claude/settings.json` is testable | `rg -n "monkeypatch.setenv" tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | `2026-08-11T14:45:00+09:00` | 20+ matches across both files | Working tree at `bf790bc` |
| `enable()` currently performs exactly four installation actions | `sed -n '340,412p' src/entirecontext/cli/project_cmds.py` | `2026-08-11T14:30:00+09:00` | Claude hooks block, `_install_git_hooks`, `_enable_codex_notify`, MCP `mcpServers.entirecontext` block | Working tree at `bf790bc` |

Repository invariants that still apply: `src/entirecontext/cli/project_cmds.py` registers
`init`, `enable`, `disable`, `status`, `config`, and `doctor` through its `register(app)`
function; the CLI package auto-discovers that function.

## Architecture

One shared helper carries the installation body; `init()` and `enable()` are both thin
callers.

```
init()                      enable()
  init_project()              _parse_agent_option()
  _parse_agent_option()       find_git_root()
  _install_integrations() <-- _install_integrations()
        |
        +-- if agent in {claude, both}:
        |     Claude Code hooks -> .claude/settings.local.json
        |     if not no_git_hooks:
        |       _install_git_hooks() -> .git/hooks/{post-commit,pre-push}
        +-- if agent in {codex, both}:
        |     _enable_codex_notify() -> ~/.codex/config.toml
        +-- unconditional:
              MCP registration -> ~/.claude/settings.json
```

`_install_integrations(repo_path, agent, no_git_hooks)` is the whole current body of
`enable()` after its argument parsing and git-root lookup, moved verbatim. It prints the
same messages it prints today, so `enable`'s observable output does not change.

The nesting above is not incidental — it is today's behavior at
`src/entirecontext/cli/project_cmds.py:353-411` and the helper must preserve it exactly.
Two consequences are easy to flatten by accident: **git hook installation lives inside the
claude branch**, so `--agent codex` installs no git hooks; and **MCP registration sits
outside every agent conditional**, so `--agent codex` still registers the MCP server. A
helper that treats the four actions as unconditional siblings changes `enable`'s behavior
while possibly still passing the existing suite, so the test table below adds the
assertions that pin it.

The design-for-isolation test: the helper takes a resolved repo path, a parsed agent
string, and a boolean; it depends on nothing from either caller's argument parsing; both
callers can change their flag surface without touching it.

## Interface

`ec init` gains three options, all matching `ec enable`'s existing names and defaults:

| Option | Default | Effect |
|---|---|---|
| `--no-hooks` | off | Skip all installation. Restores today's `ec init` behavior, including the "Run `ec enable`" hint. |
| `--no-git-hooks` | off | Install everything except the git hooks. Same meaning as on `ec enable`. |
| `--agent claude\|codex\|both` | `claude` | Same meaning as on `ec enable`. |

`--no-hooks` supersedes the other two: when it is set, `--no-git-hooks` and `--agent` have
no effect. This is stated rather than enforced with an error, because the combination is
harmless and erroring on it adds a failure mode with no user benefit.

`ec enable`'s signature, flags, output, and exit codes are unchanged.

`init()`'s current trailing hint — `Run ec enable to install Claude Code hooks.` — prints
only on the `--no-hooks` path. On the default path it is replaced by the installer's own
output.

## Error handling

`init_project()` failures keep today's behavior: print the error, exit 1.

Installation failures after a successful `init_project()` print a warning naming the
failure and instructing the user to run `ec enable`, then exit 0. The rationale: the
database was created and the project registered, so the command's primary contract
succeeded; exiting 1 would suggest nothing happened and could cause a scripted caller to
retry an already-complete initialization. The warning is unconditional and visible, so the
degradation is never silent.

`ec enable` invoked directly keeps propagating its exceptions as they are today — the
warning path is added in `init()`, not inside the shared helper.

## Testing

New tests in `tests/test_project_cmds.py`, following the existing class layout and the
same isolation pattern already used there: `@patch("entirecontext.core.project.find_git_root")`
(the `mock_git_root` argument in existing tests is this patch's mock, not a conftest
fixture) plus `monkeypatch.setenv("HOME", ...)`.

Because `init()` calls `init_project()`, these tests additionally need a real git repo and
the `isolated_global_db` fixture — `init_project()` opens the repo DB, runs migrations, and
calls `_register_in_global_db()`. The existing `git_repo` fixture (`tests/conftest.py:22`)
supplies the repo; `ec_repo` is not used because these tests must observe initialization
happening rather than inherit an already-initialized repo.

| Test | Asserts |
|---|---|
| `test_init_installs_hooks_by_default` | after `init()`, `.claude/settings.local.json` exists and contains all five EC hook entries |
| `test_init_installs_git_hooks_by_default` | `.git/hooks/post-commit` and `pre-push` exist and contain `EntireContext` |
| `test_init_registers_mcp_server` | `~/.claude/settings.json` contains `mcpServers.entirecontext` |
| `test_init_no_hooks_skips_installation` | with `no_hooks=True`, `.claude/settings.local.json` does not exist and no git hooks are written |
| `test_init_no_git_hooks_flag` | Claude hooks installed, git hooks absent |
| `test_init_agent_codex_writes_notify` | `~/.codex/config.toml` contains the EC notify entry |
| `test_init_agent_codex_skips_claude_and_git_hooks` | with `--agent codex`: `.claude/settings.local.json` absent, no git hooks written, and `~/.claude/settings.json` still contains `mcpServers.entirecontext` — pins the conditional structure the Architecture section describes |
| `test_init_hook_failure_warns_and_exits_zero` | with the installer patched to raise, `init()` does not raise `typer.Exit` and the warning text is printed |
| `test_init_idempotent` | running `init()` twice leaves exactly one EC entry per hook type |

Regression scope: the full `tests/test_project_cmds.py` and `tests/test_e2e_hooks_install.py`
suites must pass unchanged. No existing `enable` test may be modified — if one needs
changing, `enable`'s behavior drifted and the change is a bug.

External dependencies (`shutil.which`, home directory, git root) are isolated with
`monkeypatch` per the repository's testing rule; the installation logic itself is not
mocked, except in `test_init_hook_failure_warns_and_exits_zero` where the raise is the
subject of the test.

## Measurement

Per the Measure-First principle, the measurement infrastructure is the test suite itself:
each success criterion below names a test or command that proves it. No separate
measurement commit is needed, and none of the criteria depend on a dashboard metric.

## Risks

| Risk | Mitigation |
|---|---|
| `ec init` now writes outside the repo (`~/.claude/settings.json`, `~/.codex/config.toml`), which some users will not expect | Documented in README and the manual; `--no-hooks` is the escape hatch; the MCP write is already skipped when the entry exists |
| Moving the installation body could silently change `enable`'s output | The helper is moved verbatim, and no existing `enable` test may be edited — those tests are the equivalence check |
| Docs referencing `ec enable` as the install step become misleading | All six documented locations are enumerated in the plan's blast radius and updated in the same PR |
| A test or fixture that creates a project without wanting hooks starts writing to the home directory | The `ec_repo` fixture and every existing test call `init_project()` in `core/project.py` directly, never the `init()` CLI command; the installation is added to the CLI command only, so `core/project.py` stays untouched and no fixture changes behavior |

## Success Criteria

**SC1: A fresh repo needs one command.** `ec init` in a git repo with no `.claude/`
directory produces `.claude/settings.local.json` containing all five EC hook types.
_Measured by:_ `test_init_installs_hooks_by_default` passes.

**SC2: All four installation actions move, with their conditional structure intact.**
`ec init` produces the Claude hooks, both git hooks, the MCP registration, and — under
`--agent codex` — the Codex notify entry without Claude or git hooks.
_Measured by:_ `test_init_installs_git_hooks_by_default`, `test_init_registers_mcp_server`,
`test_init_agent_codex_writes_notify`, and
`test_init_agent_codex_skips_claude_and_git_hooks` pass.

**SC3: The opt-out restores the old behavior.** `ec init --no-hooks` writes nothing outside
`.entirecontext/` and prints the `ec enable` hint.
_Measured by:_ `test_init_no_hooks_skips_installation` passes.

**SC4: `ec enable` is unchanged.** Every existing test in `tests/test_project_cmds.py` and
`tests/test_e2e_hooks_install.py` passes without modification.
_Measured by:_ `uv run pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py`
green, and
`git diff -U0 main -- tests/test_project_cmds.py tests/test_e2e_hooks_install.py | grep -c '^-[^-]'`
returns 0 (no deleted or modified existing test lines).

**SC5: Installation logic exists once.** The Claude-hook dictionary, the git-hook call, the
MCP registration block, and the Codex notify call each appear exactly once in
`src/entirecontext/cli/project_cmds.py`.
_Measured by:_ each of these returns 1 against
`src/entirecontext/cli/project_cmds.py` —
`rg -c 'setdefault\("mcpServers"'`,
`rg -c '_install_git_hooks\(repo_path\)'`,
`rg -c '_enable_codex_notify\(repo_path\)'`,
`rg -c '"SessionStart": 5'`.
(A plain `rg -c 'mcpServers'` returns 2 both before and after this change: the second match
is `doctor()`'s read-only check at line 629, which is not a registration site.)

**SC6: Failure is loud, not fatal.** A failing installer leaves `init` exiting 0 with a
warning naming the failure and the recovery command.
_Measured by:_ `test_init_hook_failure_warns_and_exits_zero` passes.

**SC7: Docs match code.** No documentation states that `ec enable` is required after
`ec init`.
_Measured by:_ manual review of the locations listed in Scope/In, plus
`rg -n 'Run .*ec enable' README.md docs/ --glob '!docs/specs/**'` returning no match.

## Open Decisions

None. The three scope questions (which actions move, `ec enable`'s fate, opt-in vs.
opt-out) were resolved with the user before this spec was written.
