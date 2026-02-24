"""Tests for project_cmds: hook timeouts, config structure, git hooks, doctor sync check."""

from __future__ import annotations

import json
import stat
from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.cli.project_cmds import _is_ec_hook, _install_git_hooks

runner = CliRunner()


class TestHookTimeoutUnits:
    """Timeouts must be in seconds (matcher-based format)."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_generates_correct_timeouts(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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


class TestGitHooksInstallation:
    """Gap 7: Git hook installation in enable/disable."""

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_installs_git_hooks(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        (repo / ".git" / "hooks").mkdir(parents=True)
        hook = repo / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\n# EntireContext: already here\n")

        installed = _install_git_hooks(str(repo))
        assert "post-commit" not in installed

    def test_post_commit_script_content(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".git" / "hooks").mkdir(parents=True)

        _install_git_hooks(str(repo))

        content = (repo / ".git" / "hooks" / "post-commit").read_text()
        assert "EntireContext" in content
        assert "PostCommit" in content

    def test_pre_push_script_content(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".git" / "hooks").mkdir(parents=True)

        _install_git_hooks(str(repo))

        content = (repo / ".git" / "hooks" / "pre-push").read_text()
        assert "EntireContext" in content
        assert "sync" in content


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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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
        repo.mkdir()
        (repo / ".git" / "hooks").mkdir(parents=True)
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


class TestCodexIntegration:
    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_writes_project_notify(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        assert result.exit_code == 0
        content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "codex-notify" in content

    @patch("entirecontext.core.project.find_git_root")
    def test_enable_codex_preserves_upstream_notify(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        result = runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        assert result.exit_code == 0
        state = json.loads((repo / ".entirecontext" / "state" / "codex_notify.json").read_text(encoding="utf-8"))
        assert state["upstream_notify"] == ["python", "hook.py"]

    @patch("entirecontext.core.project.find_git_root")
    def test_disable_codex_restores_upstream_notify(self, mock_git_root, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text('notify = ["python", "old-hook.py"]\n', encoding="utf-8")
        mock_git_root.return_value = str(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        runner.invoke(app, ["enable", "--agent", "codex", "--no-git-hooks"])
        result = runner.invoke(app, ["disable", "--agent", "codex"])
        assert result.exit_code == 0
        content = (repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "old-hook.py" in content

    @patch("entirecontext.core.project.find_git_root")
    def test_doctor_codex_warns_when_missing(self, mock_git_root, ec_repo, monkeypatch):
        mock_git_root.return_value = str(ec_repo)
        fake_home = ec_repo.parent / "fakehome_codex"
        fake_home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["doctor", "--agent", "codex"])
        assert "codex" in result.output.lower()
