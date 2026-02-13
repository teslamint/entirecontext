"""E2E tests for config management."""

from __future__ import annotations

import tomllib

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.config import get_config_value, load_config, save_config

runner = CliRunner()


class TestConfigAPI:
    def test_load_default(self, ec_repo, isolated_global_config):
        config = load_config(str(ec_repo))
        assert config["capture"]["auto_capture"] is True
        assert config["search"]["default_mode"] == "regex"

    def test_save_and_load(self, ec_repo, isolated_global_config):
        save_config(str(ec_repo), "capture.auto_capture", "false")
        config = load_config(str(ec_repo))
        assert config["capture"]["auto_capture"] is False

    def test_get_config_value(self, ec_repo, isolated_global_config):
        config = load_config(str(ec_repo))
        assert get_config_value(config, "capture.auto_capture") is True
        assert get_config_value(config, "nonexistent.key") is None

    def test_config_file_valid_toml(self, ec_repo, isolated_global_config):
        save_config(str(ec_repo), "capture.auto_capture", "false")
        config_path = ec_repo / ".entirecontext" / "config.toml"
        assert config_path.exists()
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["capture"]["auto_capture"] is False


class TestConfigCLI:
    def test_dump_all(self, ec_repo, isolated_global_config, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "auto_capture" in result.output

    def test_get_key(self, ec_repo, isolated_global_config, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["config", "capture.auto_capture"])
        assert result.exit_code == 0
        assert "True" in result.output or "true" in result.output

    def test_set_and_get_key(self, ec_repo, isolated_global_config, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["config", "capture.auto_capture", "false"])
        assert result.exit_code == 0
        assert "Set" in result.output

        result = runner.invoke(app, ["config", "capture.auto_capture"])
        assert "False" in result.output or "false" in result.output
