"""E2E tests for hook installation (enable/disable/doctor)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.cli.project_cmds import _is_ec_hook

runner = CliRunner()


class TestHookInstall:
    def test_enable_creates_settings(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["enable"])
        assert result.exit_code == 0

        settings_path = ec_repo / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        hooks = settings["hooks"]
        expected = {
            "SessionStart",
            "UserPromptSubmit",
            "Stop",
            "PostToolUse",
            "SessionEnd",
        }
        assert expected == set(hooks.keys())
        for entries in hooks.values():
            assert any(_is_ec_hook(h) for h in entries)
            for entry in entries:
                if _is_ec_hook(entry):
                    assert "matcher" in entry
                    assert "hooks" in entry
                    inner = entry["hooks"]
                    assert len(inner) == 1
                    assert inner[0]["type"] == "command"
                    assert "ec hook handle" in inner[0]["command"] or "entirecontext.cli hook handle" in inner[0]["command"]
                    assert isinstance(inner[0]["timeout"], int)
                    assert inner[0]["timeout"] <= 10

    def test_enable_idempotent(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        runner.invoke(app, ["enable"])
        runner.invoke(app, ["enable"])

        settings = json.loads((ec_repo / ".claude" / "settings.json").read_text())
        for hook_name, entries in settings["hooks"].items():
            ec_entries = [h for h in entries if _is_ec_hook(h)]
            assert len(ec_entries) == 1, f"Duplicate hooks for {hook_name}"

    def test_disable_removes_hooks(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        runner.invoke(app, ["enable"])
        result = runner.invoke(app, ["disable"])
        assert result.exit_code == 0

        settings = json.loads((ec_repo / ".claude" / "settings.json").read_text())
        hooks = settings.get("hooks", {})
        for entries in hooks.values():
            assert not any(_is_ec_hook(h) for h in entries)

    def test_doctor_healthy(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        runner.invoke(app, ["enable"])
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "passed" in result.output.lower()
