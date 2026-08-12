"""Tests for project_cmds: hook timeouts, config structure, git hooks, doctor sync check."""

from __future__ import annotations

import importlib.util
import json
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.cli.project_cmds import (
    _install_git_hooks,
    _is_ec_hook,
    _remove_git_hooks,
    _resolve_ec_command,
    _strip_ec_hooks,
)

runner = CliRunner()


class TestHookTimeoutUnits:
    """Timeouts must be in seconds (matcher-based format)."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_generates_correct_timeouts(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["enable", "--no-git-hooks"])
        assert result.exit_code == 0

        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        hooks = settings["hooks"]

        assert hooks["SessionStart"][0]["hooks"][0]["timeout"] == 5
        assert hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"] == 5
        assert hooks["Stop"][0]["hooks"][0]["timeout"] == 10
        assert hooks["PostToolUse"][0]["hooks"][0]["timeout"] == 3
        assert hooks["SessionEnd"][0]["hooks"][0]["timeout"] == 5

    @patch("entirecontext.core.project.find_git_root")
    def test_timeouts_are_positive_seconds(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        runner.invoke(app, ["enable", "--no-git-hooks"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        hooks = settings["hooks"]

        for hook_name, entries in hooks.items():
            for entry in entries:
                for h in entry.get("hooks", []):
                    assert h["timeout"] > 0, f"{hook_name} timeout must be positive"


class TestHookConfigStructure:
    """Matcher-based format per Claude Code spec."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_generates_matcher_format(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        runner.invoke(app, ["enable", "--no-git-hooks"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        hooks = settings["hooks"]

        for hook_name, entries in hooks.items():
            for entry in entries:
                assert "matcher" in entry, f"{hook_name}: missing 'matcher'"
                assert "hooks" in entry, f"{hook_name}: missing 'hooks' array"
                inner = entry["hooks"]
                assert len(inner) == 1, f"{hook_name}: expected 1 inner hook"
                assert inner[0]["type"] == "command", f"{hook_name}: inner hook type must be 'command'"
                assert "command" in inner[0], f"{hook_name}: inner hook missing 'command'"
                assert "timeout" in inner[0], f"{hook_name}: inner hook missing 'timeout'"

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_command_contains_hook_type(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        runner.invoke(app, ["enable", "--no-git-hooks"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())

        for hook_name in ["SessionStart", "UserPromptSubmit", "Stop", "PostToolUse", "SessionEnd"]:
            cmd = settings["hooks"][hook_name][0]["hooks"][0]["command"]
            assert f"--type {hook_name}" in cmd


class TestIsEcHook:
    """_is_ec_hook must handle both matcher-based and flat (legacy) formats."""

    def test_flat_format_ec(self):
        assert _is_ec_hook({"command": "/usr/bin/ec hook handle --type Stop", "timeout": 10000})

    def test_flat_format_module(self):
        assert _is_ec_hook({"command": "python -m entirecontext.cli hook handle --type Stop", "timeout": 10000})

    def test_matcher_format(self):
        entry = {"matcher": "", "hooks": [{"type": "command", "command": "ec hook handle --type Stop", "timeout": 5}]}
        assert _is_ec_hook(entry)

    def test_non_ec_hook(self):
        assert not _is_ec_hook({"command": "some-other-tool run", "timeout": 5000})

    def test_empty_entry(self):
        assert not _is_ec_hook({})

    def test_quoted_executable_path(self):
        entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": "'/tmp/bin with space/ec' hook handle --type Stop"}],
        }
        assert _is_ec_hook(entry)

    def test_quoted_module_form(self):
        assert _is_ec_hook({"command": "'/opt/py 3/python' -m entirecontext.cli hook handle --type Stop"})

    def test_unbalanced_quotes_do_not_raise(self):
        assert not _is_ec_hook({"command": "some-tool 'unterminated"})

    def test_windows_exe_launcher(self):
        assert _is_ec_hook({"command": r"C:\Users\me\.venv\Scripts\ec.exe hook handle --type Stop"})

    def test_windows_exe_launcher_quoted(self):
        assert _is_ec_hook({"command": "'C:/Program Files/venv/Scripts/ec.exe' hook handle --type Stop"})

    def test_bare_exe_launcher(self):
        assert _is_ec_hook({"command": "ec.exe hook handle --type Stop"})

    def test_similarly_named_executable_is_not_ours(self):
        assert not _is_ec_hook({"command": "/usr/bin/ecx hook handle --type Stop"})

    def test_ec_executable_with_other_subcommand(self):
        assert not _is_ec_hook({"command": "/usr/bin/ec search foo"})

    def test_foreign_tool_whose_name_ends_in_ec(self):
        assert not _is_ec_hook({"command": "/usr/local/bin/myec hook handle --type Stop"})

    def test_foreign_tool_whose_name_ends_in_ec_exe(self):
        assert not _is_ec_hook({"command": r"C:\tools\myec.exe hook handle --type Stop"})


class TestStripEcHooks:
    """_strip_ec_hooks must remove only our commands, never a sibling's."""

    def test_preserves_sibling_command_in_same_entry(self):
        entry = {
            "matcher": "",
            "hooks": [
                {"type": "command", "command": "ec hook handle --type Stop", "timeout": 10},
                {"type": "command", "command": "other-tool record", "timeout": 5},
            ],
        }

        result = _strip_ec_hooks([entry])

        assert len(result) == 1
        assert [h["command"] for h in result[0]["hooks"]] == ["other-tool record"]

    def test_drops_entry_when_only_ec_commands_remain(self):
        entry = {"matcher": "", "hooks": [{"type": "command", "command": "ec hook handle --type Stop"}]}
        assert _strip_ec_hooks([entry]) == []

    def test_keeps_unrelated_entry_untouched(self):
        entry = {"matcher": "", "hooks": [{"type": "command", "command": "other-tool record"}]}
        assert _strip_ec_hooks([entry]) == [entry]

    def test_drops_flat_legacy_ec_entry(self):
        assert _strip_ec_hooks([{"command": "ec hook handle --type Stop", "timeout": 10}]) == []

    def test_preserves_foreign_tool_whose_name_ends_in_ec(self):
        entry = {"matcher": "", "hooks": [{"type": "command", "command": "/usr/local/bin/myec hook handle"}]}
        assert _strip_ec_hooks([entry]) == [entry]

    def test_drops_windows_exe_entry(self):
        entry = {"matcher": "", "hooks": [{"type": "command", "command": r"C:\venv\Scripts\ec.exe hook handle"}]}
        assert _strip_ec_hooks([entry]) == []

    def test_preserves_entry_with_already_empty_hooks(self):
        entry = {"matcher": "", "hooks": []}
        assert _strip_ec_hooks([entry]) == [entry]


class TestFallbackModuleIsRunnable:
    """The no-PATH fallback writes `python -m entirecontext.cli`, which must execute."""

    def test_module_entry_point_exists(self):
        spec = importlib.util.find_spec("entirecontext.cli.__main__")
        assert spec is not None, "python -m entirecontext.cli needs a __main__ module"

    def test_module_form_runs(self):
        result = subprocess.run(
            [sys.executable, "-m", "entirecontext.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "No module named" not in result.stderr

    def test_plain_import_does_not_run_the_cli(self):
        result = subprocess.run(
            [sys.executable, "-c", "import entirecontext.cli.__main__"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "Usage:" not in result.stdout

    def test_fallback_command_is_recognized(self, monkeypatch):
        monkeypatch.setattr("entirecontext.cli.project_cmds.shutil.which", lambda _: None)
        assert _is_ec_hook({"command": _resolve_ec_command("Stop", quote_path=True)})


class TestGitHooksInstallation:
    """Gap 7: Git hook installation in enable/disable."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_installs_git_hooks(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["enable"])
        assert result.exit_code == 0
        assert "Git hooks installed" in result.output

        post_commit = repo / ".git" / "hooks" / "post-commit"
        pre_push = repo / ".git" / "hooks" / "pre-push"
        assert post_commit.exists()
        assert pre_push.exists()
        assert post_commit.stat().st_mode & stat.S_IEXEC
        assert pre_push.stat().st_mode & stat.S_IEXEC

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_no_git_hooks_flag(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["enable", "--no-git-hooks"])
        assert result.exit_code == 0
        assert "Git hooks installed" not in result.output

        assert not (repo / ".git" / "hooks" / "post-commit").exists()
        assert not (repo / ".git" / "hooks" / "pre-push").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_removes_git_hooks(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        runner.invoke(app, ["enable"])
        assert (repo / ".git" / "hooks" / "post-commit").exists()

        result = runner.invoke(app, ["disable"])
        assert result.exit_code == 0
        assert "Git hooks removed" in result.output
        assert not (repo / ".git" / "hooks" / "post-commit").exists()
        assert not (repo / ".git" / "hooks" / "pre-push").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_leaves_non_ec_git_hooks(self, mock_git_root, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)

        other_hook = repo / ".git" / "hooks" / "post-commit"
        other_hook.write_text("#!/bin/sh\necho other\n")

        (repo / ".claude").mkdir(parents=True)
        (repo / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))

        runner.invoke(app, ["disable"])
        assert other_hook.exists()
        content = other_hook.read_text()
        assert "other" in content

    def test_install_git_hooks_no_git_dir(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _install_git_hooks(str(repo))
        assert result == []

    def test_install_skips_existing_ec_hooks(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        hook = repo / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\n# EntireContext: already here\n")

        installed = _install_git_hooks(str(repo))
        assert "post-commit" not in installed

    def test_install_preserves_foreign_hooks(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        hook = repo / ".git" / "hooks" / "pre-push"
        original = "#!/bin/sh\n# husky\nnpm test\n"
        hook.write_text(original)

        installed = _install_git_hooks(str(repo))

        assert "pre-push" not in installed
        assert hook.read_text() == original
        assert "post-commit" in installed

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_preserves_sibling_command_in_shared_entry(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        settings_path = repo / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {"type": "command", "command": "ec hook handle --type Stop", "timeout": 10},
                                    {"type": "command", "command": "other-tool record", "timeout": 5},
                                ],
                            }
                        ]
                    }
                }
            )
        )

        assert runner.invoke(app, ["enable", "--no-git-hooks"]).exit_code == 0

        commands = [
            h["command"] for entry in json.loads(settings_path.read_text())["hooks"]["Stop"] for h in entry["hooks"]
        ]
        assert "other-tool record" in commands
        assert sum(1 for c in commands if "hook handle" in c) == 1

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_preserves_sibling_command_in_shared_entry(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        settings_path = repo / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {"type": "command", "command": "ec hook handle --type Stop", "timeout": 10},
                                    {"type": "command", "command": "other-tool record", "timeout": 5},
                                ],
                            }
                        ]
                    }
                }
            )
        )

        result = runner.invoke(app, ["disable"])
        assert result.exit_code == 0

        commands = [
            h["command"] for entry in json.loads(settings_path.read_text())["hooks"]["Stop"] for h in entry["hooks"]
        ]
        assert commands == ["other-tool record"]

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_quotes_claude_hook_executable_path(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        spaced = tmp_path / "bin with space"
        spaced.mkdir()
        ec_bin = spaced / "ec"
        ec_bin.write_text("#!/bin/sh\n")
        ec_bin.chmod(0o755)
        monkeypatch.setattr("entirecontext.cli.project_cmds.shutil.which", lambda _: str(ec_bin))

        assert runner.invoke(app, ["enable", "--no-git-hooks"]).exit_code == 0

        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert shlex.split(command)[0] == str(Path(ec_bin).resolve())
        assert _is_ec_hook(settings["hooks"]["Stop"][0]), "quoted command must stay recognizable to ec disable"

    def test_install_restores_exec_bit_on_owned_hook(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        hook = repo / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\n# EntireContext: create checkpoint on commit\n")
        hook.chmod(0o644)

        _install_git_hooks(str(repo))

        assert hook.stat().st_mode & stat.S_IEXEC

    def test_install_skips_when_core_hooks_path_is_set(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        shared = tmp_path / "shared-hooks"
        shared.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "core.hooksPath", str(shared)], check=True, capture_output=True
        )

        installed = _install_git_hooks(str(repo))

        assert installed == []
        assert "core.hooksPath" in capsys.readouterr().out
        assert list(shared.iterdir()) == []

    def test_install_skips_when_core_hooks_path_is_empty(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ""], check=True, capture_output=True)

        installed = _install_git_hooks(str(repo))

        assert installed == []
        assert not (repo / "post-commit").exists()
        assert not (repo / "pre-push").exists()

    def test_remove_leaves_shared_hooks_path_untouched(self, tmp_path):
        repo = tmp_path / "repo"
        shared = tmp_path / "shared-hooks"
        shared.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "core.hooksPath", str(shared)], check=True, capture_output=True
        )
        sentinel = shared / "post-commit"
        sentinel.write_text("#!/bin/sh\n# EntireContext: installed by another repo\n")

        removed = _remove_git_hooks(str(repo))

        assert removed == []
        assert sentinel.exists()

    def test_install_creates_missing_hooks_dir(self, tmp_path):
        template = tmp_path / "empty-template"
        template.mkdir()
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", f"--template={template}", str(repo)], check=True, capture_output=True)
        assert not (repo / ".git" / "hooks").exists()

        installed = _install_git_hooks(str(repo))

        assert sorted(installed) == ["post-commit", "pre-push"]
        assert (repo / ".git" / "hooks" / "post-commit").exists()

    def test_hook_script_quotes_executable_path(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        spaced = tmp_path / "bin with space"
        spaced.mkdir()
        ec_bin = spaced / "ec"
        ec_bin.write_text("#!/bin/sh\n")
        ec_bin.chmod(0o755)
        monkeypatch.setattr("entirecontext.cli.project_cmds.shutil.which", lambda _: str(ec_bin))

        _install_git_hooks(str(repo))

        content = (repo / ".git" / "hooks" / "post-commit").read_text()
        command_line = [line for line in content.splitlines() if line and not line.startswith("#")][-1]
        assert shlex.split(command_line)[0] == str(ec_bin)

    def test_install_resolves_hooks_dir_in_linked_worktree(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"], check=True, capture_output=True
        )
        linked = tmp_path / "linked"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", "wt", str(linked)], check=True, capture_output=True
        )
        assert (linked / ".git").is_file()

        installed = _install_git_hooks(str(linked))

        assert sorted(installed) == ["post-commit", "pre-push"]
        assert (repo / ".git" / "hooks" / "post-commit").exists()

    def test_post_commit_script_content(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

        _install_git_hooks(str(repo))

        content = (repo / ".git" / "hooks" / "post-commit").read_text()
        assert "EntireContext" in content
        assert "PostCommit" in content

    def test_pre_push_script_content(self, tmp_path):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

        _install_git_hooks(str(repo))

        content = (repo / ".git" / "hooks" / "pre-push").read_text()
        assert "EntireContext" in content
        assert "sync --if-enabled" in content


def _setup_fake_home_with_mcp(ec_repo, monkeypatch):
    """Set up a fake HOME with MCP config for doctor tests."""
    fake_home = ec_repo.parent / "fakehome"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    user_claude = fake_home / ".claude"
    user_claude.mkdir(parents=True, exist_ok=True)
    (user_claude / "settings.json").write_text(
        json.dumps({"mcpServers": {"entirecontext": {"command": "ec", "args": ["mcp", "serve"], "type": "stdio"}}})
    )
    return fake_home


class TestDoctorUnsyncedCheck:
    """Gap 8: Doctor uses sync_metadata.last_export_at."""

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_detects_unsynced_checkpoints(self, mock_git_root, ec_repo, ec_db, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        _setup_fake_home_with_mcp(ec_repo, monkeypatch)

        (ec_repo / ".claude").mkdir(parents=True, exist_ok=True)
        settings = {"hooks": {"SessionStart": [{"command": "ec hook handle --type SessionStart", "timeout": 5000}]}}
        (ec_repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        ec_db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("s1", ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()[0], "interactive"),
        )
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("cp1", "s1", "abc123"),
        )
        ec_db.commit()

        result = runner.invoke(app, ["doctor"])
        assert "not synced" in result.output.lower()

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_no_warning_when_synced(self, mock_git_root, ec_repo, ec_db, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        _setup_fake_home_with_mcp(ec_repo, monkeypatch)

        (ec_repo / ".claude").mkdir(parents=True, exist_ok=True)
        settings = {"hooks": {"SessionStart": [{"command": "ec hook handle --type SessionStart", "timeout": 5000}]}}
        (ec_repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        ec_db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("s1", ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()[0], "interactive"),
        )
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at) VALUES (?, ?, ?, datetime('now', '-1 hour'))",
            ("cp1", "s1", "abc123"),
        )
        ec_db.execute("INSERT OR REPLACE INTO sync_metadata (id, last_export_at) VALUES (1, datetime('now'))")
        ec_db.commit()

        result = runner.invoke(app, ["doctor"])
        assert "not synced" not in result.output.lower()

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_no_sync_metadata_row(self, mock_git_root, ec_repo, ec_db, monkeypatch):
        """When sync_metadata has no rows, all checkpoints are unsynced."""
        mock_git_root.return_value = str(ec_repo)
        _setup_fake_home_with_mcp(ec_repo, monkeypatch)

        (ec_repo / ".claude").mkdir(parents=True, exist_ok=True)
        settings = {"hooks": {"SessionStart": [{"command": "ec hook handle --type SessionStart", "timeout": 5000}]}}
        (ec_repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        ec_db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("s1", ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()[0], "interactive"),
        )
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("cp1", "s1", "abc123"),
        )
        ec_db.commit()

        row = ec_db.execute("SELECT COUNT(*) FROM sync_metadata").fetchone()[0]
        assert row == 0

        result = runner.invoke(app, ["doctor"])
        assert "not synced" in result.output.lower()


class TestDoctorMCPCheck:
    """Doctor warns when MCP server is not configured in user settings."""

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_warns_missing_mcp(self, mock_git_root, ec_repo, ec_db, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        fake_home = ec_repo.parent / "fakehome_nomcp"
        fake_home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(fake_home))

        (ec_repo / ".claude").mkdir(parents=True, exist_ok=True)
        settings = {"hooks": {"SessionStart": [{"command": "ec hook handle --type SessionStart", "timeout": 5000}]}}
        (ec_repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        result = runner.invoke(app, ["doctor"])
        assert "mcp" in result.output.lower()

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_no_mcp_warning_when_configured(self, mock_git_root, ec_repo, ec_db, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        _setup_fake_home_with_mcp(ec_repo, monkeypatch)

        (ec_repo / ".claude").mkdir(parents=True, exist_ok=True)
        settings = {"hooks": {"SessionStart": [{"command": "ec hook handle --type SessionStart", "timeout": 5000}]}}
        (ec_repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        result = runner.invoke(app, ["doctor"])
        assert "mcp server not configured" not in result.output.lower()


class TestEnableDisableRoundTrip:
    """Enable then disable should cleanly remove all EC hooks."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_disable_cleans_up(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        runner.invoke(app, ["enable"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        assert len(settings["hooks"]) > 0

        runner.invoke(app, ["disable"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        assert len(settings.get("hooks", {})) == 0
        assert not (repo / ".git" / "hooks" / "post-commit").exists()
        assert not (repo / ".git" / "hooks" / "pre-push").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_preserves_existing_hooks(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        (repo / ".claude").mkdir(parents=True)
        settings = {"hooks": {"SessionStart": [{"command": "other-tool run", "timeout": 1000}]}}
        (repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        runner.invoke(app, ["enable", "--no-git-hooks"])
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())

        session_start_hooks = settings["hooks"]["SessionStart"]
        assert len(session_start_hooks) == 2
        assert any("other-tool" in h.get("command", "") for h in session_start_hooks)
        assert any(_is_ec_hook(h) for h in session_start_hooks)


class TestDisablePreservesEmptyHookGroups:
    """_strip_ec_hooks must not corrupt settings containing pre-existing empty hook entries."""

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_preserves_empty_hooks_entry(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        (repo / ".claude").mkdir(parents=True)
        settings = {"hooks": {"Stop": [{"matcher": "", "hooks": []}]}}
        (repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        result = runner.invoke(app, ["disable"])

        after = json.loads((repo / ".claude" / "settings.local.json").read_text())
        assert "Stop" in after.get("hooks", {}), "Stop key must survive disable"
        assert after["hooks"]["Stop"] == [{"matcher": "", "hooks": []}]
        assert "No EntireContext hooks found" in result.output


class TestDisablePreservesEmptyGroupKeys:
    """disable must not delete hook-type keys whose value is an empty list."""

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_preserves_empty_group_key_when_sibling_triggers_rewrite(
        self, mock_git_root, tmp_path, monkeypatch
    ):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        (repo / ".claude").mkdir(parents=True)
        settings = {
            "hooks": {
                "PreToolUse": [],
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "ec hook handle --type Stop", "timeout": 10}],
                    }
                ],
            }
        }
        (repo / ".claude" / "settings.local.json").write_text(json.dumps(settings))

        runner.invoke(app, ["disable"])

        after = json.loads((repo / ".claude" / "settings.local.json").read_text())
        assert "PreToolUse" in after.get("hooks", {}), "empty PreToolUse key must survive disable"
        assert after["hooks"]["PreToolUse"] == []
        assert "Stop" not in after.get("hooks", {}), "Stop with only EC hooks must be removed"


class TestCodexIntegration:
    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_writes_user_notify(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        assert result.exit_code == 0
        content = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "codex-notify" in content
        assert not (repo / ".codex" / "config.toml").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_skips_claude_and_git_hooks(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["enable", "--agent", "codex"])
        assert result.exit_code == 0
        assert not (repo / ".claude" / "settings.local.json").exists()
        assert not (repo / ".git" / "hooks" / "post-commit").exists()
        assert not (repo / ".git" / "hooks" / "pre-push").exists()
        user_settings = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "entirecontext" in user_settings["mcpServers"]

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_migrates_project_notify_to_upstream(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        assert result.exit_code == 0
        state = json.loads((fake_home / ".entirecontext" / "state" / "codex_notify.json").read_text(encoding="utf-8"))
        assert state["repos"][str(repo)]["upstream_notify"] == ["python", "hook.py"]
        local_content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "notify" not in local_content

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_codex_restores_upstream_notify_to_user_config(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "old-hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        result = runner.invoke(app, ["disable", "--agent", "codex"])
        assert result.exit_code == 0
        local_content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "old-hook.py" in local_content

    @patch("entirecontext.core.project.find_git_root")
    def test_repeated_enable_preserves_upstream_notify_for_disable(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "old-hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        first_enable = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        second_enable = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        disable = runner.invoke(app, ["disable", "--agent", "codex"])

        assert first_enable.exit_code == 0
        assert second_enable.exit_code == 0
        assert disable.exit_code == 0
        local_content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "old-hook.py" in local_content

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_preserves_legacy_local_notify_when_user_notify_is_ec(
        self, mock_git_root, tmp_path, monkeypatch
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "old-hook.py"]\n', encoding="utf-8")
        fake_home = tmp_path / "fakehome"
        (fake_home / ".codex").mkdir(parents=True)
        (fake_home / ".codex" / "config.toml").write_text('notify = ["ec", "hook", "codex-notify"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(fake_home))

        enable = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        disable = runner.invoke(app, ["disable", "--agent", "codex"])

        assert enable.exit_code == 0
        assert disable.exit_code == 0
        local_content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "old-hook.py" in local_content

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_from_different_repo_does_not_restore_other_repos_upstream(
        self, mock_git_root, tmp_path, monkeypatch
    ):
        first_repo = tmp_path / "repo-a"
        second_repo = tmp_path / "repo-b"
        first_repo.mkdir()
        second_repo.mkdir()
        (first_repo / ".git").mkdir()
        (second_repo / ".git").mkdir()
        (first_repo / ".codex").mkdir()
        (first_repo / ".codex" / "config.toml").write_text('notify = ["python", "old-hook.py"]\n', encoding="utf-8")
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        mock_git_root.return_value = str(first_repo)
        enable = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        mock_git_root.return_value = str(second_repo)
        disable = runner.invoke(app, ["disable", "--agent", "codex"])

        assert enable.exit_code == 0
        assert disable.exit_code == 0
        content = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "old-hook.py" not in content
        state = json.loads((fake_home / ".entirecontext" / "state" / "codex_notify.json").read_text(encoding="utf-8"))
        assert state["repos"][str(first_repo)]["upstream_notify"] == ["python", "old-hook.py"]

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_ingest_reads_upstream_from_global_path(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        assert result.exit_code == 0

        from entirecontext.hooks.codex_ingest import _load_state

        state = _load_state(str(repo))
        assert state.get("upstream_notify") == ["python", "hook.py"]

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_codex_warns_when_missing(self, mock_git_root, ec_repo, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        fake_home = ec_repo.parent / "fakehome_codex"
        fake_home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["doctor", "--agent", "codex"])
        assert "codex" in result.output.lower()


class TestInitInstallsIntegrations:
    """ec init installs hooks by default; --no-hooks opts out."""

    @staticmethod
    def _hooks(repo):
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        return settings["hooks"]

    @patch("entirecontext.core.project.find_git_root")
    def test_init_installs_hooks_by_default(self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        hooks = self._hooks(git_repo)
        for name in ("SessionStart", "UserPromptSubmit", "Stop", "PostToolUse", "SessionEnd"):
            assert any(_is_ec_hook(h) for h in hooks[name])

    @patch("entirecontext.core.project.find_git_root")
    def test_init_installs_git_hooks_by_default(
        self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch
    ):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        for name in ("post-commit", "pre-push"):
            hook_path = git_repo / ".git" / "hooks" / name
            assert hook_path.exists()
            assert "EntireContext" in hook_path.read_text(encoding="utf-8")

    @patch("entirecontext.core.project.find_git_root")
    def test_init_registers_mcp_server(self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch):
        fake_home = tmp_path / "fakehome"
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        user_settings = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "entirecontext" in user_settings["mcpServers"]

    @patch("entirecontext.core.project.find_git_root")
    def test_init_no_hooks_skips_installation(self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch):
        fake_home = tmp_path / "fakehome"
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["init", "--no-hooks"])
        assert result.exit_code == 0
        assert "ec enable" in result.output

        # --no-hooks supersedes --agent, so an unrecognized value must not abort the
        # database-only path.
        result = runner.invoke(app, ["init", "--no-hooks", "--agent", "bogus"])
        assert result.exit_code == 0

        assert not (git_repo / ".claude" / "settings.local.json").exists()
        assert not (git_repo / ".git" / "hooks" / "post-commit").exists()
        assert not (git_repo / ".git" / "hooks" / "pre-push").exists()
        assert not (fake_home / ".claude" / "settings.json").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_init_no_git_hooks_flag(self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["init", "--no-git-hooks"])
        assert result.exit_code == 0

        assert (git_repo / ".claude" / "settings.local.json").exists()
        assert not (git_repo / ".git" / "hooks" / "post-commit").exists()
        assert not (git_repo / ".git" / "hooks" / "pre-push").exists()

    @patch("entirecontext.core.project.find_git_root")
    def test_init_agent_codex_skips_claude_and_git_hooks(
        self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch
    ):
        fake_home = tmp_path / "fakehome"
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["init", "--agent", "codex"])
        assert result.exit_code == 0

        assert "codex-notify" in (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert not (git_repo / ".claude" / "settings.local.json").exists()
        assert not (git_repo / ".git" / "hooks" / "post-commit").exists()
        assert not (git_repo / ".git" / "hooks" / "pre-push").exists()
        user_settings = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "entirecontext" in user_settings["mcpServers"]

    @patch("entirecontext.core.project.find_git_root")
    def test_init_idempotent(self, mock_git_root, git_repo, isolated_global_db, tmp_path, monkeypatch):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        assert runner.invoke(app, ["init"]).exit_code == 0
        assert runner.invoke(app, ["init"]).exit_code == 0

        assert len(self._hooks(git_repo)["SessionStart"]) == 1

    @patch("entirecontext.cli.project_cmds._install_integrations")
    @patch("entirecontext.core.project.find_git_root")
    def test_init_hook_failure_warns_and_exits_zero(
        self, mock_git_root, mock_install, git_repo, isolated_global_db, tmp_path, monkeypatch
    ):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.setenv("COLUMNS", "200")
        mock_install.side_effect = OSError("boom")

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert result.exception is None
        assert "boom" in result.output
        assert "ec enable" in result.output

    @patch("entirecontext.cli.project_cmds._install_integrations")
    @patch("entirecontext.core.project.find_git_root")
    def test_init_failure_recovery_preserves_agent(
        self, mock_git_root, mock_install, git_repo, isolated_global_db, tmp_path, monkeypatch
    ):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.setenv("COLUMNS", "200")
        mock_install.side_effect = OSError("boom")

        result = runner.invoke(app, ["init", "--agent", "codex"])
        assert result.exit_code == 0
        assert "ec enable --agent codex" in result.output

    @patch("entirecontext.cli.project_cmds._install_integrations")
    @patch("entirecontext.core.project.find_git_root")
    def test_init_failure_recovery_preserves_no_git_hooks(
        self, mock_git_root, mock_install, git_repo, isolated_global_db, tmp_path, monkeypatch
    ):
        mock_git_root.return_value = str(git_repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.setenv("COLUMNS", "200")
        mock_install.side_effect = OSError("boom")

        result = runner.invoke(app, ["init", "--no-git-hooks"])
        assert result.exit_code == 0
        assert "ec enable --agent claude --no-git-hooks" in result.output
