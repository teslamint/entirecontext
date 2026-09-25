"""Contracts that keep canonical-project vs. workspace root resolution in one place."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app

SRC = Path(__file__).resolve().parent.parent / "src" / "entirecontext"

_SHOW_TOPLEVEL_ALLOWED = {
    SRC / "core" / "repo_roots.py",
    SRC / "cli" / "project_cmds.py",
}
_FIND_GIT_ROOT_WRAPPERS = {
    SRC / "core" / "context.py",
    SRC / "hooks" / "session_lifecycle.py",
}


def _sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_show_toplevel_only_in_resolver_and_inject_script():
    offenders = {p for p in _sources() if "--show-toplevel" in p.read_text(encoding="utf-8")}
    assert offenders <= _SHOW_TOPLEVEL_ALLOWED, sorted(str(p.relative_to(SRC)) for p in offenders)

    project_cmds = (SRC / "cli" / "project_cmds.py").read_text(encoding="utf-8")
    script = project_cmds.split('_INJECT_SCRIPT = """', 1)[1].split('"""', 1)[0]
    assert project_cmds.count("--show-toplevel") == script.count("--show-toplevel")


def test_private_git_root_helpers_are_only_compat_wrappers():
    pattern = re.compile(r"^def _find_git_root\(", re.MULTILINE)
    definers = {p for p in _sources() if pattern.search(p.read_text(encoding="utf-8"))}
    assert definers == _FIND_GIT_ROOT_WRAPPERS


@pytest.mark.parametrize(
    "args",
    [
        ["session", "list"],
        ["event", "list"],
        ["checkpoint", "list"],
        ["decision", "list"],
        ["dashboard"],
        ["graph"],
        ["compact"],
        ["search", "foo"],
        ["status"],
    ],
)
def test_cli_from_linked_worktree_uses_canonical_db(ec_worktree, monkeypatch, args):
    _main, linked = ec_worktree
    monkeypatch.chdir(linked)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert not (linked / ".entirecontext" / "db").exists()
