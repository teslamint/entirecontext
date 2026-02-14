"""Tests for MCP server commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestMcpServe:
    def test_import_error(self):
        with patch("entirecontext.cli.mcp_cmds.console") as mock_console:
            with patch.dict("sys.modules", {"entirecontext.mcp": None, "entirecontext.mcp.server": None}):
                result = runner.invoke(app, ["mcp", "serve"])
                assert result.exit_code == 1

    def test_success(self):
        with patch("entirecontext.mcp.server.run_server") as mock_run:
            result = runner.invoke(app, ["mcp", "serve"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
