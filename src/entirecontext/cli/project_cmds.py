"""Project management commands: init, enable, disable, status, config, doctor."""

from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()


def _resolve_ec_command(hook_type: str | None = None) -> str:
    if shutil.which("ec"):
        base = f"{Path(shutil.which('ec')).resolve()} hook handle"
    else:
        base = f"{sys.executable} -m entirecontext.cli hook handle"
    if hook_type:
        base += f" --type {hook_type}"
    return base


def _is_ec_hook(entry: dict) -> bool:
    cmd = entry.get("command", "")
    if "ec hook handle" in cmd or "entirecontext.cli hook handle" in cmd:
        return True
    for h in entry.get("hooks", []):
        cmd = h.get("command", "")
        if "ec hook handle" in cmd or "entirecontext.cli hook handle" in cmd:
            return True
    return False


@app.command()
def init():
    """Initialize EntireContext in current git repo."""
    from ..core.project import init_project

    try:
        project = init_project()
        console.print(f"[green]Initialized EntireContext[/green] in {project['repo_path']}")
        console.print(f"  Project: {project['name']} ({project['id'][:8]}...)")
        console.print("  Run [bold]ec enable[/bold] to install Claude Code hooks.")
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _install_git_hooks(repo_path: str) -> list[str]:
    """Install git hooks (post-commit, pre-push). Returns list of installed hook names."""
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    if not hooks_dir.exists():
        return []

    installed = []
    ec_cmd = _resolve_ec_command()

    post_commit_script = f"""#!/bin/sh
# EntireContext: create checkpoint on commit if active session
{ec_cmd.replace("hook handle", "hook handle --type PostCommit")}
"""
    pre_push_script = f"""#!/bin/sh
# EntireContext: sync on push if auto_sync_on_push is enabled
{ec_cmd.replace("hook handle", "sync")}
"""

    for name, script in [("post-commit", post_commit_script), ("pre-push", pre_push_script)]:
        hook_path = hooks_dir / name
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
            if "EntireContext" in content:
                continue
        hook_path.write_text(script, encoding="utf-8")
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
        installed.append(name)

    return installed


def _remove_git_hooks(repo_path: str) -> list[str]:
    """Remove EntireContext git hooks. Returns list of removed hook names."""
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    if not hooks_dir.exists():
        return []

    removed = []
    for name in ("post-commit", "pre-push"):
        hook_path = hooks_dir / name
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
            if "EntireContext" in content:
                hook_path.unlink()
                removed.append(name)

    return removed


@app.command()
def enable(
    no_git_hooks: bool = typer.Option(False, "--no-git-hooks", help="Skip git hook installation"),
):
    """Enable auto-capture by installing Claude Code hooks."""
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    settings_path = Path(repo_path) / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings: dict = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

    hooks = settings.setdefault("hooks", {})
    hook_timeouts = {
        "SessionStart": 5000,
        "UserPromptSubmit": 5000,
        "Stop": 10000,
        "PostToolUse": 3000,
        "SessionEnd": 5000,
    }
    ec_hooks = {
        name: [{"command": _resolve_ec_command(name), "timeout": timeout}] for name, timeout in hook_timeouts.items()
    }

    for hook_name, hook_configs in ec_hooks.items():
        existing = hooks.get(hook_name, [])
        existing = [h for h in existing if not _is_ec_hook(h)]
        existing.extend(hook_configs)
        hooks[hook_name] = existing

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    console.print("[green]Hooks installed[/green] in .claude/settings.json")

    if not no_git_hooks:
        installed = _install_git_hooks(repo_path)
        if installed:
            console.print(f"[green]Git hooks installed:[/green] {', '.join(installed)}")


@app.command()
def disable():
    """Disable auto-capture by removing Claude Code hooks."""
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    settings_path = Path(repo_path) / ".claude" / "settings.json"
    if not settings_path.exists():
        console.print("No hooks configured.")
        return

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})
    changed = False

    for hook_name in list(hooks.keys()):
        original = hooks[hook_name]
        filtered = [h for h in original if not _is_ec_hook(h)]
        if len(filtered) != len(original):
            changed = True
        if filtered:
            hooks[hook_name] = filtered
        else:
            del hooks[hook_name]

    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        console.print("[yellow]Hooks removed[/yellow] from .claude/settings.json")
    else:
        console.print("No EntireContext hooks found.")

    removed = _remove_git_hooks(repo_path)
    if removed:
        console.print(f"[yellow]Git hooks removed:[/yellow] {', '.join(removed)}")


@app.command()
def status():
    """Show EntireContext capture status."""
    from ..core.project import get_status

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

    console.print(table)


@app.command()
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


@app.command()
def doctor():
    """Diagnose EntireContext issues."""
    from ..core.project import find_git_root

    issues: list[str] = []
    warnings: list[str] = []

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

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
            conn.close()

    settings_path = Path(repo_path) / ".claude" / "settings.json"
    if not settings_path.exists():
        warnings.append("No .claude/settings.json found. Run 'ec enable'.")
    else:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        hooks = settings.get("hooks", {})
        ec_hooks_found = any(
            any(_is_ec_hook(h) for h in hooks.get(k, []))
            for k in ["SessionStart", "UserPromptSubmit", "Stop", "PostToolUse", "SessionEnd"]
        )
        if not ec_hooks_found:
            warnings.append("EntireContext hooks not installed. Run 'ec enable'.")

    if issues:
        for issue in issues:
            console.print(f"[red]ERROR:[/red] {issue}")
    if warnings:
        for warning in warnings:
            console.print(f"[yellow]WARN:[/yellow] {warning}")
    if not issues and not warnings:
        console.print("[green]All checks passed.[/green]")
