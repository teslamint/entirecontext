---
schema: plan/v1
title: ec init installs hooks
type: feat
status: done
completed_by: 705765762c13fe3befbd484ed7a752ae6bdecfdf
date: 2026-08-11
execution: code
origin: docs/specs/2026-08-11-init-installs-hooks-design.md
body_seal: ecefd1bbdb56bfb152d919181fffa142c97575784412f5bd4871e6131fb1a774
---

# ec init installs hooks

## Goal

Make `ec init` install the Claude Code hooks, git hooks, MCP registration, and Codex notify
entry that `ec enable` installs today, so a new repo needs one command instead of two.
`ec enable` keeps working unchanged as the re-install and repair path.

## Architecture notes

The installation body of `enable()` (`src/entirecontext/cli/project_cmds.py:353-411`) moves
verbatim into a module-level private helper, `_install_integrations()`. This follows the
file's existing convention: `_install_git_hooks()`, `_remove_git_hooks()`,
`_enable_codex_notify()`, and `_resolve_ec_command()` are already module-level private
helpers in the same file. No new module is created.

```
def _install_integrations(repo_path: str, agent: str, no_git_hooks: bool) -> None
```

The helper takes an already-resolved repo path and an already-parsed agent string, so
neither caller's flag surface leaks into it. `enable()` keeps its own
`_parse_agent_option()` call and `find_git_root()` lookup; `init()` gets the repo path from
`init_project()`'s return value and does its own `_parse_agent_option()` call.

**The conditional nesting inside the helper is load-bearing and must be preserved
verbatim.** In today's `enable()`:

- The Claude Code hook block and the `_install_git_hooks()` call are both inside
  `if agent in {"claude", "both"}`, and the git-hook call is further nested inside
  `if not no_git_hooks`.
- The `_enable_codex_notify()` call is inside `if agent in {"codex", "both"}`.
- The MCP registration block sits outside every agent conditional and therefore runs on
  every invocation.

Consequence: `--agent codex` installs no git hooks but does register the MCP server. A
helper that treats the four actions as unconditional siblings changes `enable`'s behavior.
U1 adds the characterization test that pins this before the extraction happens.

The helper raises rather than handling errors, so `enable()`'s exception behavior is
unchanged. `init()` wraps the call in `try/except Exception` and degrades to a warning —
that degradation belongs to `init()`'s contract, not the helper's. `except Exception` is
the correct breadth here because the failure modes are heterogeneous (`json.JSONDecodeError`
from a malformed settings file, `OSError`/`PermissionError` from an unwritable path,
`tomllib`/TOML errors from the Codex path) and the response is identical for all of them.
Ruff runs on defaults in this repo (`[tool.ruff]` sets only `target-version` and
`line-length`), so `BLE001` is not enabled; `decisions_cmds.py:592` and `:648` are existing
precedent for the same pattern.

`src/entirecontext/core/project.py` is not modified. Every existing test and the `ec_repo`
fixture calls `init_project()` there directly rather than the `init()` CLI command, so
adding installation to the CLI command leaves all existing fixtures untouched.

## Assumption Recheck

Origin spec `docs/specs/2026-08-11-init-installs-hooks-design.md` retains four live
assumptions. All four rerun clean against the worktree at `2fe26df`.

| Approved claim | Command rerun | Fresh result | Outcome |
|---|---|---|---|
| `init_project()` is idempotent | `rg -n "SELECT id, name FROM projects WHERE repo_path" src/entirecontext/core/project.py` | matches at line 52; the row-exists branch reuses `id`/`name` | match |
| `ec init` has no test coverage today | `rg -c "def test.*init\|project_cmds.init" tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | no matches in either file (rg exits 1) | match |
| Hook-install tests isolate `HOME` with `monkeypatch.setenv` | `rg -c "monkeypatch.setenv" tests/test_project_cmds.py tests/test_e2e_hooks_install.py` | 19 in `test_project_cmds.py`, 4 in `test_e2e_hooks_install.py` | match |
| `enable()` performs exactly four installation actions | `rg -n '_install_git_hooks\(repo_path\)\|_enable_codex_notify\(repo_path\)\|setdefault\("mcpServers"\|"SessionStart": 5' src/entirecontext/cli/project_cmds.py` | one match each at lines 389, 394, 402, 363 | match |

No contradictions and no unavailable evidence, so no deviation addendum is required.

## File structure

Modify:

- `src/entirecontext/cli/project_cmds.py` — extract `_install_integrations()`; add flags and
  the installation call to `init()`.
- `tests/test_project_cmds.py` — one characterization test for `enable --agent codex`, then
  the new `init` tests.
- `README.md` — install instructions (lines ~254–290), MCP section (~462–469), hooks section
  (~542–563).
- `docs/spec.md` — hook installation description (lines 176–186).
- `docs/entirecontext-project-manual.md` — getting-started steps (120–132), command list
  (443–444), troubleshooting row (750).

No files are created. No file is split: `project_cmds.py` already holds all six project
commands and their helpers, and this change adds one helper to that established grouping.

## Scenario coverage map

| S-ID | Scenario | Unit chain | Scenario evidence |
|---|---|---|---|
| S1 | First-time setup in a new repo | U1 → U2 | `test_init_installs_hooks_by_default`, `test_init_installs_git_hooks_by_default`, `test_init_registers_mcp_server` (Covers S1) |
| S2 | Initialization without touching agent config | U2 | `test_init_no_hooks_skips_installation` (Covers S2) |
| S3 | Repairing a clobbered hook config | U1 | `tests/test_e2e_hooks_install.py::test_enable_creates_settings` and `::test_enable_idempotent`, both existing and unmodified (Covers S3) |
| S4 | Codex user | U1 → U2 | `test_enable_codex_skips_claude_and_git_hooks` (U1) and `test_init_agent_codex_skips_claude_and_git_hooks` (U2) (Covers S4) |
| S5 | Re-running init on an initialized repo | U2 | `test_init_idempotent` (Covers S5) |
| S6 | Hook installation fails mid-init | U2 | `test_init_hook_failure_warns_and_exits_zero` (Covers S6) |

S3 is realized by U1 alone: the scenario asserts that `ec enable` still behaves as it does
today, so the evidence is the existing suite passing unmodified after the extraction.

## Implementation Units

## U1: Extract `_install_integrations()` from `enable()`
Execution note: characterization-first
Files:
  Modify: `src/entirecontext/cli/project_cmds.py`
  Test: `tests/test_project_cmds.py`
Interfaces:
  Consumes: `_resolve_ec_command(hook_type: str | None = None) -> str`, `_is_ec_hook(entry: dict) -> bool`, `_install_git_hooks(repo_path: str) -> list[str]`, `_enable_codex_notify(repo_path: str) -> None`
  Produces: `_install_integrations(repo_path: str, agent: str, no_git_hooks: bool) -> None`
Test scenarios:
  happy: `enable --agent claude` still writes all five hook types to `.claude/settings.local.json`, both git hooks, and the MCP entry — covered by the existing tests in `tests/test_project_cmds.py` and `tests/test_e2e_hooks_install.py`
  edge: `enable --agent codex` writes the Codex notify entry and the MCP entry, but writes no `.claude/settings.local.json` and no git hooks — this asymmetry has no test today and is the extraction's likeliest silent breakage
  error: n/a — the helper's error behavior is unchanged from today's inline code, which propagates exceptions to Typer; no new error path is introduced in this unit
  integration: `enable --agent codex` on a repo with no `.claude/` directory leaves that directory absent while `~/.claude/settings.json` gains `mcpServers.entirecontext` (Covers S3, Covers S4)
Steps:
  1. Add `test_enable_codex_skips_claude_and_git_hooks` to `tests/test_project_cmds.py`, in the class that already holds `test_enable_codex_writes_user_notify` (around line 393). Follow that test's setup exactly: decorate with `@patch("entirecontext.core.project.find_git_root")`, create `repo = tmp_path / "repo"` with `(repo / ".git" / "hooks").mkdir(parents=True)`, set `mock_git_root.return_value = str(repo)`, and `monkeypatch.setenv("HOME", str(fake_home))` with `fake_home = tmp_path / "fakehome"`. Invoke through the CLI runner — `result = runner.invoke(app, ["enable", "--agent", "codex"])` — which is this file's universal invocation style (`runner = CliRunner()` at line 14). Do not call `project_cmds.enable(...)` as a plain function: after U2 the sibling command's defaults become `typer.OptionInfo` objects, which are truthy, and a direct call would silently take the wrong branch. Note the deliberate omission of `--no-git-hooks`, which every existing codex test passes — its absence is what makes this test prove that the codex path installs no git hooks on its own.
  2. Assert in that test: `result.exit_code == 0`; `not (repo / ".claude" / "settings.local.json").exists()`; `not (repo / ".git" / "hooks" / "post-commit").exists()`; `not (repo / ".git" / "hooks" / "pre-push").exists()`; and `"entirecontext" in json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))["mcpServers"]`. Run the test by name with `uv run pytest tests/test_project_cmds.py -k test_enable_codex_skips_claude_and_git_hooks -x`. Confirm it PASSES. This is a characterization test: it records today's behavior before the refactor, so a failure here means the assertion was written wrong, not that the code is broken.
  3. In `src/entirecontext/cli/project_cmds.py`, add `def _install_integrations(repo_path: str, agent: str, no_git_hooks: bool) -> None:` immediately above `def enable(`. Move the body of `enable()` from the line `if agent in {"claude", "both"}:` through the final `console.print("[green]MCP server configured[/green] ...")` into it, unchanged — same statements, same order, same console messages, same conditional nesting.
  4. Replace the moved body in `enable()` with a single call: `_install_integrations(repo_path, agent, no_git_hooks)`. `enable()` keeps its `_parse_agent_option(agent)` call, its `find_git_root()` call, and its not-in-a-git-repo error exit.
  5. Run `uv run pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py`. Confirm every test passes, including the one added in step 1.
  6. Run `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`. Confirm clean.
  7. Commit: `refactor(cli): Extract _install_integrations from enable`
Acceptance: `uv run pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py` is green, and `git diff -U0 HEAD~1 -- tests/test_project_cmds.py | grep -c '^-[^-]'` returns 0 (the characterization test was added, nothing existing was edited).

## U2: `ec init` installs by default
Execution note: test-first
Files:
  Modify: `src/entirecontext/cli/project_cmds.py`
  Test: `tests/test_project_cmds.py`
Interfaces:
  Consumes: `_install_integrations(repo_path: str, agent: str, no_git_hooks: bool) -> None`, `_parse_agent_option(agent: str) -> str`, `init_project(repo_path: str | Path | None = None) -> dict`
  Produces: `init(no_hooks: bool = False, no_git_hooks: bool = False, agent: str = "claude") -> None`
Test scenarios:
  happy: `init()` on a fresh git repo writes `.claude/settings.local.json` containing all five EC hook types, writes both git hooks, and registers `mcpServers.entirecontext` in `~/.claude/settings.json` (Covers S1)
  edge: `init(no_hooks=True)` writes nothing outside `.entirecontext/` and prints the `ec enable` hint; `init(no_git_hooks=True)` writes the Claude hooks but no git hooks; `init(agent="codex")` writes the Codex notify entry and the MCP entry but no Claude hooks and no git hooks; calling `init()` twice leaves exactly one EC entry per hook type (Covers S2, Covers S4, Covers S5)
  error: with `_install_integrations` patched to raise `OSError("boom")`, `runner.invoke(app, ["init"])` returns `exit_code == 0` with `result.exception is None`, and the output contains both the failure text and the string `ec enable` (Covers S6)
  integration: a fresh `git_repo` fixture repo goes from no `.entirecontext/` and no `.claude/` to a registered project plus a complete hook installation in one `init()` call (Covers S1)
Steps:
  1. Add a new test class to `tests/test_project_cmds.py` for `init`. Every test in it takes the `git_repo` and `isolated_global_db` fixtures plus `tmp_path` and `monkeypatch`, sets `fake_home = tmp_path / "fakehome"` and `monkeypatch.setenv("HOME", str(fake_home))`, and patches `entirecontext.core.project.find_git_root` to return `str(git_repo)`. `git_repo` is required (not `ec_repo`) because these tests must observe initialization happening; `isolated_global_db` is required because `init_project()` calls `_register_in_global_db()`. No `mkdir` for `.git/hooks` is needed — `git init` creates it, verified by running `git init` in a temp directory at planning time. Every test invokes through the CLI runner (`runner.invoke(app, ["init", ...])`), never `project_cmds.init(...)` directly: Typer option defaults are `OptionInfo` objects, and every `OptionInfo` is truthy, so a direct `init()` call would read `no_hooks` as true and skip the very installation these tests assert.
  2. Write these seven failing tests: `test_init_installs_hooks_by_default` (`runner.invoke(app, ["init"])`; all five hook names present in `.claude/settings.local.json`); `test_init_installs_git_hooks_by_default` (`["init"]`; `post-commit` and `pre-push` exist and contain `EntireContext`); `test_init_registers_mcp_server` (`["init"]`; `mcpServers.entirecontext` present in `fake_home/.claude/settings.json`); `test_init_no_hooks_skips_installation` (`["init", "--no-hooks"]`; no `.claude/settings.local.json`, no git hooks, no `fake_home/.claude/settings.json`); `test_init_no_git_hooks_flag` (`["init", "--no-git-hooks"]`; Claude hooks present, git hooks absent); `test_init_agent_codex_skips_claude_and_git_hooks` (`["init", "--agent", "codex"]`; `fake_home/.codex/config.toml` contains `codex-notify`, `.claude/settings.local.json` absent, git hooks absent, MCP entry present); `test_init_idempotent` (`["init"]` twice; `len(hooks["SessionStart"]) == 1`). Every test asserts `result.exit_code == 0` first.
  3. Run `uv run pytest tests/test_project_cmds.py -k init`. Confirm all seven fail, and confirm the reason matches the test: the four that pass a new flag fail with `exit_code == 2` and `No such option` in the output, because `init` does not accept those flags yet; the three that invoke a bare `["init"]` exit 0 and fail on their file assertions, because today's `init` installs nothing.
  4. In `src/entirecontext/cli/project_cmds.py`, change `def init():` to take three Typer options: `no_hooks: bool = typer.Option(False, "--no-hooks", help="Skip hook and MCP installation")`, `no_git_hooks: bool = typer.Option(False, "--no-git-hooks", help="Skip git hook installation")`, `agent: str = typer.Option("claude", "--agent", help="Target agent integration (claude|codex|both)")`.
  5. In `init()`, after the two existing `console.print` lines that report the initialized project, replace the `Run [bold]ec enable[/bold] to install Claude Code hooks.` line with a branch: when `no_hooks` is true, print that same hint line; otherwise call `_install_integrations(project["repo_path"], _parse_agent_option(agent), no_git_hooks)`. Call `_parse_agent_option(agent)` before `init_project()` so an invalid `--agent` value fails before any database work.
  6. Run `uv run pytest tests/test_project_cmds.py -k init`. Confirm all seven pass.
  7. Write the eighth test, `test_init_hook_failure_warns_and_exits_zero`: patch `entirecontext.cli.project_cmds._install_integrations` with `side_effect=OSError("boom")`, run `result = runner.invoke(app, ["init"])`, and assert `result.exit_code == 0`, `result.exception is None`, and that `result.output` contains both `boom` and `ec enable`. Set `monkeypatch.setenv("COLUMNS", "200")` in this test — the module-level `Console()` at `project_cmds.py:16` wraps output to the detected terminal width, and a narrow width can split an asserted substring across lines. Run it; confirm it fails with `exit_code == 1` and `result.exception` holding the `OSError`, because the exception still propagates.
  8. Wrap the `_install_integrations(...)` call in `try` / `except Exception as exc:`. In the handler, print a warning naming the failure and the recovery command — for example `console.print(f"[yellow]Warning:[/yellow] hook installation failed: {exc}")` followed by `console.print("  Run [bold]ec enable[/bold] to retry.")` — and do not raise. `init_project()`'s own `RuntimeError` handler stays outside this block, unchanged, so a failed initialization still exits 1.
  9. Run `uv run pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py`. Confirm all pass, including every pre-existing test.
  10. Run `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`. Confirm clean.
  11. Commit: `feat(cli): ec init installs hooks by default`
Acceptance: `uv run pytest tests/test_project_cmds.py tests/test_e2e_hooks_install.py` is green with all eight new `init` tests present, and `rg -c 'setdefault\("mcpServers"' src/entirecontext/cli/project_cmds.py` returns 1.

## U3: Update documentation to match the new install flow
Execution note: skip-test-first
Files:
  Modify: `README.md`, `docs/spec.md`, `docs/entirecontext-project-manual.md`
  Test: n/a — documentation unit; acceptance is grep-verified
Interfaces:
  Consumes: the flag surface produced by U2 (`--no-hooks`, `--no-git-hooks`, `--agent`)
  Produces: nothing importable
Test scenarios:
  happy: n/a — no code changes in this unit
  edge: n/a — no code changes in this unit
  error: n/a — no code changes in this unit
  integration: a reader following README.md's quick-start alone reaches a working capture setup without running a second command (Covers S1)
Steps:
  1. In `README.md`, update the quick-start block near line 254 so `ec init` stands alone and `ec enable` is no longer presented as a required second step; do the same for the block near line 274.
  2. In `README.md`'s command table near line 289, change the `ec init` row's description to state that it initializes the repo and installs the Claude Code hooks, git hooks, and user-level MCP config, and list the `--no-hooks`, `--no-git-hooks`, and `--agent` options. Keep the `ec enable` row and re-describe it as the re-install and repair command.
  3. In `README.md`'s MCP section near lines 462–469, change `ec enable` to `ec init` as the command that registers the MCP server, and keep the note that `ec enable` also does it and that both are idempotent.
  4. In `README.md`'s hooks section near lines 542–563, change "`ec enable` installs two kinds of hooks" to name `ec init`, and change "Skip git hook installation with `ec enable --no-git-hooks`" to mention both `ec init --no-git-hooks` and `ec enable --no-git-hooks`.
  5. In `docs/spec.md` lines 176–186, change the three statements that attribute hook installation, MCP installation, and git hook installation to `ec enable` so they name `ec init` as the default installer and `ec enable` as the equivalent re-install path.
  6. In `docs/entirecontext-project-manual.md`, merge steps 2 and 3 near lines 120–121 into a single `ec init` step; update the `ec init` and `ec enable` descriptions near lines 131–132; update the command list near lines 443–444; and leave the troubleshooting row at line 750 naming `ec enable`, since re-installing a clobbered config is exactly what that row needs.
  7. Read each changed section back and confirm no remaining sentence tells the reader to run `ec enable` after `ec init`.
  8. Commit: `docs: ec init installs hooks`
Acceptance: `rg -n 'Run .*ec enable' README.md docs/ --glob '!docs/specs/**' --glob '!docs/plans/**'` returns no match, and `rg -n 'ec init' README.md | head` shows the quick-start block no longer paired with a following `ec enable` line.

## Mutation/failure-state matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

The deliverable crosses no outward-publication boundary: no unit pushes to a remote, creates
a remote repository, publishes to a registry, creates a platform release, or changes
repository visibility. The home-directory writes that `ec init` gains (`~/.claude/settings.json`,
`~/.codex/config.toml`) are local side effects of the same class as the `.entirecontext/`
writes `ec init` already performs today. Their partial-failure behavior is not left
unexamined — it is the subject of S6, U2 step 7–8, and SC6.

## Carry-forward trigger audit

Audited ROADMAP.md at `2fe26df`: 14 open rows, 1 fired, 0 unobservable.

| Tracker row | Trigger class | What fired it | Disposition |
|---|---|---|---|
| ROADMAP.md:370 — "Alpha → stable status: flip README badge and pyproject classifier once production observability confirms loop completion across multiple real sessions" | edit-based (names README plus an event; the tiebreak resolves a mixed trigger to edit-based) | U3 modifies `README.md` | Deferred to Follow-Up Work — the row's substantive precondition is unmet: the latest recorded telemetry is maturity 64 against a 75 target (ROADMAP.md:357), so the badge flip would assert a stability level the measurements do not support. U3 touches README's install instructions only and does not go near the badge. |

The other 13 rows did not fire. Rows 204, 231, 265, 300, 301, 336, and 357 are event-based
on measurement volume (maturity score, `n≥30` assessments, session counts) and this plan
produces no sessions or assessments. Rows 338, 354, and 359 are event-based on archaeology
inputs (Git C-style path escapes appearing in real repositories; a squash commit awaiting
export authorization) and name files this plan does not touch. Rows 378, 380, and 385 name
no trigger condition and are recorded as unclassifiable; the feature-relevance question
resolves negative for all three — product messaging for decision memory, team-scoped
decisions, and decision file rename tracking are unrelated to the `ec init` command surface.

## Deferred to Follow-Up Work

- **Alpha → stable badge flip (ROADMAP.md:370)** — fired by U3's README edit, deferred
  because maturity is 64 against the row's own 75 precondition. Re-evaluate at the next
  release whose telemetry clears the threshold.
- **`--agent codex` installs no git hooks** — surfaced while writing U1's characterization
  test. Git hooks (`post-commit` checkpointing, `pre-push` sync) are agent-independent, so
  the current nesting is arguably a bug rather than a design choice. Out of scope here: this
  plan preserves existing behavior, and changing it would alter `ec enable` — which the
  approved spec explicitly excludes. Worth a separate spec.
- **`ec disable` does not undo the MCP registration or the Codex notify entry** — noticed
  while mapping `enable`'s four actions. Pre-existing asymmetry, untouched by this change.

## Open unknowns

**Planning-time:** none.

**Implementation-time:**

- The exact test class name and insertion point for U2's new `init` tests — determined by
  the class layout in `tests/test_project_cmds.py` at implementation time.
- The exact wording of U2's warning string, beyond the requirement that it name the failure
  and contain `ec enable`.
- Whether any README line beyond the five enumerated ranges references `ec enable` as a
  required step — U3 step 7's read-back resolves it.
