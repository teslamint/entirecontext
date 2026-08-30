"""Project management commands: init, enable, disable, status, config, doctor."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .._build_provenance import BUILD_DIRTY, BUILD_SHA

console = Console()

_AGENT_CHOICES = {"claude", "codex", "both"}


def _parse_agent_option(agent: str) -> str:
    value = (agent or "claude").strip().lower()
    if value not in _AGENT_CHOICES:
        raise typer.BadParameter("--agent must be one of: claude, codex, both")
    return value


def _resolve_ec_codex_notify_command() -> list[str]:
    if shutil.which("ec"):
        return [str(Path(shutil.which("ec")).resolve()), "hook", "codex-notify"]
    return [sys.executable, "-m", "entirecontext.cli", "hook", "codex-notify"]


def _is_ec_codex_notify_command(command: list[str]) -> bool:
    if len(command) >= 3 and command[-2:] == ["hook", "codex-notify"]:
        return True
    joined = " ".join(command)
    return "entirecontext.cli hook codex-notify" in joined


def _read_toml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def _write_toml_file(path: Path, data: dict) -> None:
    from ..core.config import _write_toml

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_toml(path, data)


def _codex_state_path(repo_path: str) -> Path:
    return _codex_global_state_path()


def _codex_legacy_state_path(repo_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / "state" / "codex_notify.json"


def _codex_global_state_path() -> Path:
    return Path.home() / ".entirecontext" / "state" / "codex_notify.json"


def _codex_user_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _codex_project_config_path(repo_path: str) -> Path:
    return Path(repo_path) / ".codex" / "config.toml"


def _read_global_state() -> dict:
    state_path = _codex_global_state_path()
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_global_state(state: dict) -> None:
    state_path = _codex_global_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


_UNSET = object()


def _save_codex_upstream(
    repo_path: str,
    command: list[str] | None,
    *,
    global_upstream: list[str] | None | object = _UNSET,
) -> None:
    state = _read_global_state()
    repos = state.setdefault("repos", {})
    entry: dict = {"enabled": True}
    if command:
        entry["upstream_notify"] = command
    repos[repo_path] = entry
    if global_upstream is not _UNSET:
        if global_upstream:
            state["global_upstream"] = global_upstream
        else:
            state.pop("global_upstream", None)
    _write_global_state(state)


def _remove_codex_repo_entry(repo_path: str) -> dict:
    state = _read_global_state()
    state.get("repos", {}).pop(repo_path, None)
    _write_global_state(state)
    return state


def _has_other_active_repos(state: dict, exclude: str) -> bool:
    repos = state.get("repos", {})
    return any(k != exclude for k in repos)


def _validate_upstream(upstream: object) -> list[str] | None:
    if not isinstance(upstream, list) or not upstream:
        return None
    if not all(isinstance(item, str) for item in upstream):
        return None
    return upstream


def _load_codex_upstream(repo_path: str) -> list[str] | None:
    state = _read_global_state()
    repo_entry = state.get("repos", {}).get(repo_path)
    if isinstance(repo_entry, dict):
        result = _validate_upstream(repo_entry.get("upstream_notify"))
        if result:
            return result

    result = _validate_upstream(state.get("global_upstream"))
    if result:
        return result

    result = _validate_upstream(state.get("upstream_notify"))
    if result:
        return result

    legacy_path = _codex_legacy_state_path(repo_path)
    if legacy_path.exists():
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if isinstance(legacy, dict):
            return _validate_upstream(legacy.get("upstream_notify"))
    return None


def _load_repo_only_upstream(repo_path: str) -> list[str] | None:
    state = _read_global_state()
    repo_entry = state.get("repos", {}).get(repo_path)
    if isinstance(repo_entry, dict):
        return _validate_upstream(repo_entry.get("upstream_notify"))
    return None


def _load_global_upstream() -> list[str] | None:
    state = _read_global_state()
    result = _validate_upstream(state.get("global_upstream"))
    if result:
        return result
    return _validate_upstream(state.get("upstream_notify"))


def _is_valid_notify(notify: object) -> bool:
    return isinstance(notify, list) and bool(notify) and all(isinstance(x, str) for x in notify)


def _enable_codex_notify(repo_path: str) -> None:
    local_config_path = _codex_project_config_path(repo_path)
    user_config_path = _codex_user_config_path()
    local_cfg = _read_toml_file(local_config_path)
    user_cfg = _read_toml_file(user_config_path)
    local_notify = local_cfg.get("notify")
    user_notify = user_cfg.get("notify")

    local_upstream: list[str] | None = None
    user_upstream: list[str] | None = None
    if _is_valid_notify(local_notify) and not _is_ec_codex_notify_command(local_notify):
        local_upstream = local_notify
    if _is_valid_notify(user_notify) and not _is_ec_codex_notify_command(user_notify):
        user_upstream = user_notify

    repo_upstream = local_upstream or user_upstream
    if not repo_upstream and _is_valid_notify(user_notify) and _is_ec_codex_notify_command(user_notify):
        repo_upstream = _load_codex_upstream(repo_path)

    if "notify" in local_cfg:
        local_cfg.pop("notify", None)
        _write_toml_file(local_config_path, local_cfg)

    user_cfg["notify"] = _resolve_ec_codex_notify_command()
    _write_toml_file(user_config_path, user_cfg)
    _save_codex_upstream(
        repo_path, repo_upstream, global_upstream=user_upstream if user_upstream is not None else _UNSET
    )


def _disable_codex_notify(repo_path: str) -> bool:
    local_config_path = _codex_project_config_path(repo_path)
    user_config_path = _codex_user_config_path()
    local_cfg = _read_toml_file(local_config_path)
    user_cfg = _read_toml_file(user_config_path)
    local_notify = local_cfg.get("notify")
    user_notify = user_cfg.get("notify")

    found = False
    if _is_valid_notify(local_notify) and _is_ec_codex_notify_command(local_notify):
        found = True
        local_cfg.pop("notify", None)
        _write_toml_file(local_config_path, local_cfg)

    if not (_is_valid_notify(user_notify) and _is_ec_codex_notify_command(user_notify)):
        if found:
            local_only = _load_repo_only_upstream(repo_path)
            if local_only:
                local_cfg["notify"] = local_only
                _write_toml_file(local_config_path, local_cfg)
            _remove_codex_repo_entry(repo_path)
        return found

    found = True
    local_only = _load_repo_only_upstream(repo_path)
    global_upstream = _load_global_upstream()
    state = _remove_codex_repo_entry(repo_path)

    if local_only:
        local_cfg["notify"] = local_only
        _write_toml_file(local_config_path, local_cfg)

    if _has_other_active_repos(state, repo_path):
        return found

    if global_upstream:
        user_cfg["notify"] = global_upstream
    else:
        user_cfg.pop("notify", None)
    _write_toml_file(user_config_path, user_cfg)
    return found


def _resolve_ec_command(hook_type: str | None = None, quote_path: bool = False) -> str:
    """Build the `ec hook handle` invocation.

    `quote_path` shell-quotes the executable path so an `ec` under a path containing spaces
    still runs. It is safe for the Claude settings command as well as the git hook scripts
    because `_is_ec_command` recognizes the quoted and unquoted forms alike.
    """
    ec_bin = shutil.which("ec")
    if ec_bin:
        executable = str(Path(ec_bin).resolve())
        base = f"{shlex.quote(executable) if quote_path else executable} hook handle"
    else:
        executable = shlex.quote(sys.executable) if quote_path else sys.executable
        base = f"{executable} -m entirecontext.cli hook handle"
    if hook_type:
        base += f" --type {hook_type}"
    return base


def _is_ec_command(cmd: str) -> bool:
    """Recognize an EntireContext hook command however it was written.

    Three forms have to match, because failing to recognize one makes `ec disable` leave the
    hook behind and every reinstall append a duplicate:

    - `/usr/local/bin/ec hook handle` — what older installs wrote, path raw
    - `'/x y/ec' hook handle` — what current installs write, path shell-quoted
    - `C:\\...\\ec.exe hook handle` — the Windows console-script launcher

    Matching is token-based rather than by substring, because `ec hook handle` is a substring
    of another tool's `myec hook handle` and deleting a foreign hook is worse than missing
    one of ours.
    """
    if not cmd:
        return False
    return any(_tokens_are_ec_invocation(t) for t in _tokenizations(cmd))


def _tokenizations(cmd: str) -> list[list[str]]:
    """Split a command both ways, because neither split alone covers both platforms.

    POSIX mode resolves the quotes current installs write, but eats the backslashes in a
    Windows path. Non-POSIX mode keeps the path intact but leaves the quotes attached.
    """
    results = []
    for posix in (True, False):
        try:
            tokens = shlex.split(cmd, posix=posix)
        except ValueError:
            continue
        if tokens:
            results.append(tokens)
    return results


def _tokens_are_ec_invocation(tokens: list[str]) -> bool:
    rest = tokens[1:]
    if _executable_name(tokens[0]) == "ec":
        return rest[:2] == ["hook", "handle"]
    return rest[:4] == ["-m", "entirecontext.cli", "hook", "handle"]


def _executable_name(token: str) -> str:
    """Basename of a command token, without surrounding quotes or a Windows `.exe` suffix.

    Splits on both separators rather than using `Path`, because the flavor that wrote the
    settings file is not necessarily the one reading it.
    """
    name = re.split(r"[\\/]", token.strip("'\""))[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_ec_hook(entry: dict) -> bool:
    if _is_ec_command(entry.get("command", "")):
        return True
    return any(_is_ec_command(h.get("command", "")) for h in entry.get("hooks", []))


def _strip_ec_hooks(entries: list) -> list:
    """Remove EntireContext commands, preserving sibling commands in the same entry.

    A matcher entry can hold several nested commands. Dropping the whole entry because one
    of them is ours would delete another tool's hook.
    """
    kept = []
    for entry in entries:
        if _is_ec_command(entry.get("command", "")):
            continue
        inner = entry.get("hooks")
        if isinstance(inner, list):
            remaining = [h for h in inner if not _is_ec_command(h.get("command", ""))]
            if inner and not remaining:
                continue
            if len(remaining) != len(inner):
                entry = {**entry, "hooks": remaining}
        kept.append(entry)
    return kept


def init(
    no_hooks: bool = typer.Option(False, "--no-hooks", help="Skip hook and MCP installation"),
    no_git_hooks: bool = typer.Option(False, "--no-git-hooks", help="Skip git hook installation"),
    agent: str = typer.Option("claude", "--agent", help="Target agent integration (claude|codex|both)"),
):
    """Initialize EntireContext in current git repo and install agent hooks."""
    from ..core.project import init_project

    if not no_hooks:
        agent = _parse_agent_option(agent)

    try:
        project = init_project()
        console.print(f"[green]Initialized EntireContext[/green] in {project['repo_path']}")
        console.print(f"  Project: {project['name']} ({project['id'][:8]}...)")
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if no_hooks:
        console.print("  Run [bold]ec enable[/bold] to install Claude Code hooks.")
        return

    try:
        _install_integrations(project["repo_path"], agent, no_git_hooks)
    except Exception as exc:
        retry = f"ec enable --agent {agent}"
        if no_git_hooks:
            retry += " --no-git-hooks"
        console.print(f"[yellow]Warning:[/yellow] hook installation failed: {exc}")
        console.print(f"  Run [bold]{retry}[/bold] to retry.")


def _git_capture(repo_path: str, args: list[str]) -> str | None:
    """Run a git command in repo_path. Returns stripped stdout, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _has_custom_hooks_path(repo_path: str) -> bool:
    """True when core.hooksPath is set, which may point outside this repository.

    Presence, not truthiness: `core.hooksPath = ""` exits 0 with empty output, and treating
    that as unset makes `git rev-parse --git-path hooks` resolve to the repository root.
    """
    return _git_capture(repo_path, ["config", "--get", "core.hooksPath"]) is not None


def _resolve_hooks_dir(repo_path: str, create: bool = False) -> Path | None:
    """Resolve git's effective hooks directory. Returns None when it cannot be determined.

    In a linked worktree `.git` is a file, so `<repo>/.git/hooks` does not exist; git
    resolves the hooks path into the main repository instead. Callers must rule out
    `core.hooksPath` first — see `_has_custom_hooks_path`.
    """
    out = _git_capture(repo_path, ["rev-parse", "--git-path", "hooks"])
    if out is None:
        return None

    hooks_dir = Path(out)
    if not hooks_dir.is_absolute():
        hooks_dir = Path(repo_path) / hooks_dir
    if create:
        try:
            hooks_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    return hooks_dir if hooks_dir.is_dir() else None


def _is_ec_git_hook(content: str, hook_name: str) -> bool:
    """Return whether a hook file exactly matches the EC-owned script shape."""
    expected_args = {
        "post-commit": ["hook", "handle", "--type", "PostCommit"],
        "pre-push": ["sync", "--if-enabled"],
    }.get(hook_name)
    lines = content.splitlines()
    if (
        expected_args is None
        or len(lines) != 3
        or lines[0] != "#!/bin/sh"
        or not lines[1].startswith("# EntireContext:")
    ):
        return False

    for tokens in _tokenizations(lines[2]):
        executable = _executable_name(tokens[0])
        if executable == "ec":
            args = tokens[1:]
        elif re.fullmatch(r"(?:python(?:\d+(?:\.\d+)*)?|pypy\d*)", executable) is not None:
            if tokens[1:3] != ["-m", "entirecontext.cli"]:
                continue
            args = tokens[3:]
        else:
            continue
        if args == expected_args:
            return True
    return False


def _install_git_hooks(repo_path: str) -> list[str]:
    """Install git hooks (post-commit, pre-push). Returns list of installed hook names."""
    if _has_custom_hooks_path(repo_path):
        console.print("[yellow]Warning:[/yellow] core.hooksPath is set; skipping git hook installation.")
        return []

    hooks_dir = _resolve_hooks_dir(repo_path, create=True)
    if hooks_dir is None:
        console.print("[yellow]Warning:[/yellow] could not resolve the git hooks directory; skipping git hooks.")
        return []

    installed = []
    ec_cmd = _resolve_ec_command(quote_path=True)

    post_commit_script = f"""#!/bin/sh
# EntireContext: create checkpoint on commit if active session
{ec_cmd.replace("hook handle", "hook handle --type PostCommit")}
"""
    pre_push_script = f"""#!/bin/sh
# EntireContext: sync on push if auto_sync_on_push is enabled
{ec_cmd.replace("hook handle", "sync --if-enabled")}
"""

    for name, script in [("post-commit", post_commit_script), ("pre-push", pre_push_script)]:
        hook_path = hooks_dir / name
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
            if _is_ec_git_hook(content, name):
                hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
                continue
            console.print(f"[yellow]Warning:[/yellow] {name} hook already exists and is not ours; leaving it alone.")
            continue
        hook_path.write_text(script, encoding="utf-8")
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
        installed.append(name)

    return installed


def _remove_git_hooks(repo_path: str) -> list[str]:
    """Remove EntireContext git hooks. Returns list of removed hook names."""
    if _has_custom_hooks_path(repo_path):
        return []

    hooks_dir = _resolve_hooks_dir(repo_path)
    if hooks_dir is None:
        return []

    removed = []
    for name in ("post-commit", "pre-push"):
        hook_path = hooks_dir / name
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
            if _is_ec_git_hook(content, name):
                hook_path.unlink()
                removed.append(name)

    return removed


def _is_ec_mcp_server(value: object) -> bool:
    """Return whether an MCP entry has a standard EC form eligible for explicit removal."""
    if not isinstance(value, dict) or set(value) != {"command", "args", "type"}:
        return False
    command = value["command"]
    args = value["args"]
    if not isinstance(command, str) or value["type"] != "stdio" or not isinstance(args, list):
        return False

    executable = _executable_name(command)
    if executable == "ec":
        return args == ["mcp", "serve"]
    return re.fullmatch(r"(?:python(?:\d+(?:\.\d+)*)?|pypy\d*)", executable) is not None and args == [
        "-m",
        "entirecontext.cli",
        "mcp",
        "serve",
    ]


def _remove_mcp_registration() -> bool:
    """Remove only the recognized EntireContext user-level MCP entry."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return False

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    mcp_servers = settings.get("mcpServers")
    if not isinstance(mcp_servers, dict) or not _is_ec_mcp_server(mcp_servers.get("entirecontext")):
        return False

    del mcp_servers["entirecontext"]
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True


def _install_integrations(repo_path: str, agent: str, no_git_hooks: bool) -> None:
    """Install agent hooks, git hooks, and the user-level MCP server entry."""
    if agent in {"claude", "both"}:
        settings_path = Path(repo_path) / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict = {}
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

        hooks = settings.setdefault("hooks", {})
        hook_timeouts = {
            "SessionStart": 5,
            "UserPromptSubmit": 5,
            "Stop": 10,
            "PostToolUse": 3,
            "SessionEnd": 5,
        }
        ec_hooks = {
            name: [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": _resolve_ec_command(name, quote_path=True), "timeout": timeout}
                    ],
                }
            ]
            for name, timeout in hook_timeouts.items()
        }

        for hook_name, hook_configs in ec_hooks.items():
            existing = hooks.get(hook_name, [])
            existing = _strip_ec_hooks(existing)
            existing.extend(hook_configs)
            hooks[hook_name] = existing

        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        console.print("[green]Hooks installed[/green] in .claude/settings.local.json")

    if not no_git_hooks:
        installed = _install_git_hooks(repo_path)
        if installed:
            console.print(f"[green]Git hooks installed:[/green] {', '.join(installed)}")

    if agent in {"codex", "both"}:
        _enable_codex_notify(repo_path)
        console.print("[green]Codex notify installed[/green] in ~/.codex/config.toml")

    user_settings_path = Path.home() / ".claude" / "settings.json"
    user_settings_path.parent.mkdir(parents=True, exist_ok=True)
    user_settings: dict = {}
    if user_settings_path.exists():
        user_settings = json.loads(user_settings_path.read_text(encoding="utf-8"))
    mcp_servers = user_settings.setdefault("mcpServers", {})
    if "entirecontext" not in mcp_servers:
        ec_bin = shutil.which("ec")
        mcp_servers["entirecontext"] = {
            "command": str(Path(ec_bin).resolve()) if ec_bin else sys.executable,
            "args": ["mcp", "serve"] if ec_bin else ["-m", "entirecontext.cli", "mcp", "serve"],
            "type": "stdio",
        }
        user_settings_path.write_text(json.dumps(user_settings, indent=2) + "\n", encoding="utf-8")
        console.print("[green]MCP server configured[/green] in ~/.claude/settings.json")


def enable(
    no_git_hooks: bool = typer.Option(False, "--no-git-hooks", help="Skip git hook installation"),
    agent: str = typer.Option("claude", "--agent", help="Target agent integration (claude|codex|both)"),
):
    """Enable auto-capture by installing agent hooks."""
    from ..core.project import find_git_root

    agent = _parse_agent_option(agent)
    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    _install_integrations(repo_path, agent, no_git_hooks)


def disable(
    agent: str = typer.Option("claude", "--agent", help="Target agent integration (claude|codex|both)"),
    remove_mcp: bool = typer.Option(False, "--remove-mcp", help="Also remove the standard user-level EC MCP entry"),
):
    """Disable auto-capture by removing selected repository and agent integrations."""
    from ..core.project import find_git_root

    agent = _parse_agent_option(agent)
    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if agent in {"claude", "both"}:
        local_settings_path = Path(repo_path) / ".claude" / "settings.local.json"
        settings_path = Path(repo_path) / ".claude" / "settings.json"
        changed = False

        for path in [local_settings_path, settings_path]:
            if not path.exists():
                continue
            settings = json.loads(path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", {})
            path_changed = False
            for hook_name in list(hooks.keys()):
                original = hooks[hook_name]
                filtered = _strip_ec_hooks(original)
                if filtered != original:
                    path_changed = True
                    changed = True
                if filtered:
                    hooks[hook_name] = filtered
                elif original:
                    del hooks[hook_name]
            if path_changed:
                path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

        if changed:
            console.print("[yellow]Hooks removed[/yellow] from .claude/settings.local.json")
        else:
            console.print("No EntireContext hooks found.")

    removed = _remove_git_hooks(repo_path)
    if removed:
        console.print(f"[yellow]Git hooks removed:[/yellow] {', '.join(removed)}")

    if agent in {"codex", "both"}:
        if _disable_codex_notify(repo_path):
            console.print("[yellow]Codex notify removed[/yellow] from ~/.codex/config.toml")
        else:
            console.print("No Codex notify integration found.")
    if remove_mcp:
        if _remove_mcp_registration():
            console.print("[yellow]MCP server removed[/yellow] from ~/.claude/settings.json")
        else:
            console.print("No standard EntireContext MCP registration found.")


def status(
    agent: str = typer.Option("claude", "--agent", help="View status for claude|codex|both"),
):
    """Show EntireContext capture status."""
    from ..core.project import find_git_root
    from ..core.project import get_status

    agent = _parse_agent_option(agent)
    st = get_status()

    if not st.get("initialized"):
        console.print("[yellow]EntireContext is not initialized in this repository.[/yellow]")
        console.print("Run [bold]ec init[/bold] to get started.")
        return

    table = Table(title="EntireContext Status")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    p = st["project"]
    table.add_row("Project", f"{p['name']} ({p['id'][:8]}...)")
    table.add_row("Repo", p["repo_path"])
    table.add_row("Sessions", str(st["session_count"]))
    table.add_row("Turns", str(st["turn_count"]))
    table.add_row("Checkpoints", str(st["checkpoint_count"]))

    if st["active_session"]:
        s = st["active_session"]
        table.add_row("Active Session", f"{s['id'][:8]}... ({s['total_turns']} turns)")
    else:
        table.add_row("Active Session", "None")

    repo_path = find_git_root()
    if repo_path and agent in {"codex", "both"}:
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            codex_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE session_type = 'codex'").fetchone()[0]
            codex_turns = conn.execute(
                """SELECT COUNT(*)
                   FROM turns t JOIN sessions s ON s.id = t.session_id
                   WHERE s.session_type = 'codex'"""
            ).fetchone()[0]
        finally:
            conn.close()
        table.add_row("Codex Sessions", str(codex_sessions))
        table.add_row("Codex Turns", str(codex_turns))

    console.print(table)


def config(
    key: str | None = typer.Argument(None, help="Config key (dotted notation, e.g. capture.auto_capture)"),
    value: str | None = typer.Argument(None, help="Value to set"),
):
    """Get or set configuration."""
    from ..core.config import get_config_value, load_config, save_config
    from ..core.project import find_git_root

    repo_path = find_git_root()

    if key is None:
        cfg = load_config(repo_path)
        console.print_json(data=cfg)
        return

    if value is None:
        cfg = load_config(repo_path)
        val = get_config_value(cfg, key)
        if val is None:
            console.print(f"[yellow]Key not found:[/yellow] {key}")
        else:
            console.print(f"{key} = {val}")
        return

    save_config(repo_path, key, value)
    console.print(f"[green]Set[/green] {key} = {value}")


def _is_entirecontext_checkout(repo_path: str) -> bool:
    root = Path(repo_path)
    try:
        with (root / "pyproject.toml").open("rb") as file:
            project = tomllib.load(file).get("project")
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return (
        isinstance(project, dict)
        and project.get("name") == "entirecontext"
        and (root / "src" / "entirecontext").is_dir()
    )


def _running_from_checkout_source(repo_path: str) -> bool:
    expected = Path(repo_path) / "src" / "entirecontext" / "cli" / "project_cmds.py"
    return Path(__file__).resolve() == expected.resolve()


def _build_provenance_warning(repo_path: str) -> str | None:
    if not _is_entirecontext_checkout(repo_path) or _running_from_checkout_source(repo_path):
        return None

    from ..core.git_utils import get_current_commit

    checkout_sha = get_current_commit(repo_path)
    reinstall = "Run 'uv tool install --force .' from this checkout."
    if checkout_sha is None:
        return (
            "Build provenance unavailable: could not resolve checkout HEAD. "
            "Create or check out a commit before rebuilding the installed ec executable."
        )
    if BUILD_SHA is None:
        return f"Build provenance unavailable for the installed ec executable. {reinstall}"
    if BUILD_DIRTY:
        return (
            f"Build provenance is dirty at {BUILD_SHA[:7]} and cannot prove checkout equivalence. "
            f"Commit or restore tracked changes, then {reinstall.lower()}"
        )
    if BUILD_SHA != checkout_sha:
        return (
            f"Build provenance mismatch: installed build {BUILD_SHA[:7]} "
            f"does not match checkout {checkout_sha[:7]}. {reinstall}"
        )
    return None


def _active_python_version() -> tuple[int, int]:
    return sys.version_info[:2]


def _configured_python_version() -> tuple[int, int] | None:
    try:
        config = (Path(sys.prefix) / "pyvenv.cfg").read_text(encoding="utf-8")
        match = re.search(r"(?m)^version_info\s*=\s*(\d+)\.(\d+)(?:\.\d+)?\s*$", config)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))
    except (OSError, UnicodeError, ValueError):
        return None


def _python_interpreter_drift_warning(repo_path: str) -> str | None:
    configured = _configured_python_version()
    active = _active_python_version()
    if configured is None or configured == active:
        return None

    install_target = "." if _is_entirecontext_checkout(repo_path) else "entirecontext"
    return (
        f"Python interpreter drift: virtual environment configured {configured[0]}.{configured[1]}, "
        f"active {active[0]}.{active[1]}. Recreate the tool environment; "
        "'uv tool install --force' can leave the stale interpreter binding in place. "
        "Run 'uv tool uninstall entirecontext', then "
        f"'uv tool install --managed-python --python 3.13 {install_target}'."
    )


def doctor(
    agent: str = typer.Option("claude", "--agent", help="Validate claude|codex|both integrations"),
):
    """Diagnose EntireContext issues."""
    from ..core.project import find_git_root

    agent = _parse_agent_option(agent)
    issues: list[str] = []
    warnings: list[str] = []

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    provenance_warning = _build_provenance_warning(repo_path)
    if provenance_warning is not None:
        warnings.append(provenance_warning)

    interpreter_warning = _python_interpreter_drift_warning(repo_path)
    if interpreter_warning is not None:
        warnings.append(interpreter_warning)

    ec_dir = Path(repo_path) / ".entirecontext"
    if not ec_dir.exists():
        issues.append("EntireContext not initialized. Run 'ec init'.")
    else:
        db_path = ec_dir / "db" / "local.db"
        if not db_path.exists():
            issues.append("Database missing. Run 'ec init'.")
        else:
            from ..db import SCHEMA_VERSION, get_current_version, get_db

            conn = get_db(repo_path)
            try:
                v = get_current_version(conn)
                if v < SCHEMA_VERSION:
                    warnings.append(f"Schema version {v} < {SCHEMA_VERSION}. Migration needed.")

                unsynced = conn.execute(
                    """SELECT COUNT(*) FROM checkpoints
                    WHERE created_at > COALESCE(
                        (SELECT last_export_at FROM sync_metadata WHERE id = 1),
                        '1970-01-01'
                    )"""
                ).fetchone()[0]
                if unsynced > 0:
                    warnings.append(f"{unsynced} checkpoints not synced to shadow branch.")
            finally:
                conn.close()

    if agent in {"claude", "both"}:
        local_settings_path = Path(repo_path) / ".claude" / "settings.local.json"
        settings_path = Path(repo_path) / ".claude" / "settings.json"
        active_settings_path = local_settings_path if local_settings_path.exists() else settings_path
        if not active_settings_path.exists():
            warnings.append("No .claude/settings.local.json found. Run 'ec enable'.")
        else:
            settings = json.loads(active_settings_path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", {})
            ec_hooks_found = any(
                any(_is_ec_hook(h) for h in hooks.get(k, []))
                for k in ["SessionStart", "UserPromptSubmit", "Stop", "PostToolUse", "SessionEnd"]
            )
            if not ec_hooks_found:
                warnings.append("EntireContext hooks not installed. Run 'ec enable'.")

    if agent in {"codex", "both"}:
        codex_cfg_path = _codex_user_config_path()
        if not codex_cfg_path.exists():
            warnings.append("No ~/.codex/config.toml found. Run 'ec enable --agent codex'.")
        else:
            cfg = _read_toml_file(codex_cfg_path)
            notify = cfg.get("notify")
            if not (isinstance(notify, list) and all(isinstance(x, str) for x in notify)):
                warnings.append("Codex notify not configured. Run 'ec enable --agent codex'.")
            elif not _is_ec_codex_notify_command(notify):
                warnings.append("Codex notify does not point to EntireContext hook.")
            else:
                state = _read_global_state()
                repo_enrolled = repo_path in state.get("repos", {})
                legacy_state = Path(repo_path) / ".entirecontext" / "state" / "codex_notify.json"
                if not repo_enrolled and not legacy_state.exists():
                    warnings.append(
                        "This repo is not enrolled for Codex capture. Run 'ec enable --agent codex' in this repo."
                    )

    if agent in {"claude", "both"}:
        user_settings_path = Path.home() / ".claude" / "settings.json"
        if user_settings_path.exists():
            user_settings = json.loads(user_settings_path.read_text(encoding="utf-8"))
            if "entirecontext" not in user_settings.get("mcpServers", {}):
                warnings.append("MCP server not configured. Run 'ec enable' to add MCP support.")
        else:
            warnings.append("MCP server not configured. Run 'ec enable' to add MCP support.")

    if issues:
        for issue in issues:
            console.print(f"[red]ERROR:[/red] {issue}")
    if warnings:
        for warning in warnings:
            console.print(f"[yellow]WARN:[/yellow] {warning}")
    if not issues and not warnings:
        console.print("[green]All checks passed.[/green]")


def register(app: typer.Typer) -> None:
    app.command()(init)
    app.command()(enable)
    app.command()(disable)
    app.command()(status)
    app.command()(config)
    app.command()(doctor)
