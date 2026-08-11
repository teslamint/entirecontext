# 0005. `ec init` installs integrations by default

**Status:** accepted
**Date:** 2026-08-11
**EC Decision:** `83213b14-31a0-4b1f-9a42-a0aa0929a6f4`

## Context

Setting up EntireContext in a new repository required two commands. `ec init` created
`.entirecontext/` and registered the project; `ec enable` installed the Claude Code hooks,
the git hooks, the user-level MCP registration, and — under `--agent codex|both` — the
Codex notify entry. Nothing captured anything until the second command ran, and nothing in
the tool's own output made that failure state visible: a repo that had been `init`-ed but
not `enable`-d looked initialized and silently recorded nothing.

This is a public CLI contract change (three new flags on `ec init`, plus a changed default
behavior), which this repository's policy places under ADR governance.

## Decision

`ec init` performs the installation by default. Both commands call one shared helper,
`_install_integrations(repo_path, agent, no_git_hooks)`, so the installation logic exists
in exactly one place.

`ec init` gains three flags, each matching `ec enable`'s existing name and default:

| Flag | Default | Effect |
|---|---|---|
| `--no-hooks` | off | Skip all installation; restores the previous `ec init` behavior |
| `--no-git-hooks` | off | Install everything except the git hooks |
| `--agent claude\|codex\|both` | `claude` | Target agent integration |

`ec enable` is kept, unchanged in signature and output, as the re-install and repair path.
It does no database work, which is what makes it the right command for a clobbered hook
config — the case `ec doctor`'s troubleshooting guidance points at.

Installation failures after a successful `init_project()` print a warning naming the failure
and a retry command that preserves the selected `--agent` and `--no-git-hooks` choices, then
exit 0. The database was created and the project registered, so the command's primary
contract succeeded; exiting non-zero would misreport that and could make a scripted caller
retry work that is already complete.

Two safety properties of git hook installation were tightened in the same change, because
moving installation into `ec init` made them reachable by every new user rather than only by
someone who deliberately ran `ec enable`:

- An existing hook file that does not carry the `EntireContext` marker is left alone with a
  warning. Previously it was overwritten, silently destroying husky, pre-commit, or any
  other tooling's hook.
- The hooks directory is resolved with `git rev-parse --git-path hooks` rather than assumed
  to be `<repo>/.git/hooks`. In a linked worktree `.git` is a file, so the old assumption
  made installation a silent no-op.

## Consequences

Easier: one command sets up a repository completely. The "initialized but capturing
nothing" state stops being reachable by accident. Installation logic has a single
definition, so a change to hook wiring cannot drift between the two commands.

Harder: `ec init` now writes outside the repository — `~/.claude/settings.json` always, and
`~/.codex/config.toml` on the codex path. Users who expect `init` to be repo-local need
`--no-hooks`. Any future test or script that invokes `ec init` must isolate `HOME` or it
will write the real one; no such caller exists today.

Accepted asymmetry, preserved rather than corrected: `--agent codex` installs no git hooks,
because git hook installation lives inside the `claude|both` branch, while MCP registration
runs unconditionally. Git hooks are agent-independent, so this is arguably a bug — but
changing it would alter `ec enable`'s behavior, which the governing spec put out of scope.
It is registered as follow-up work rather than fixed here.

## References

- Spec: [`docs/specs/2026-08-11-init-installs-hooks-design.md`](../specs/2026-08-11-init-installs-hooks-design.md)
- Plan: [`docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md`](../plans/2026-08-11-001-feat-init-installs-hooks-plan.md)
- Deviation: [`docs/deviations/2026-08-11-git-hook-installation-safety.md`](../deviations/2026-08-11-git-hook-installation-safety.md)
