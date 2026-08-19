"""Tests for MCP server commands."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.mcp import server as server_module

runner = CliRunner()


class TestMcpServe:
    def test_import_error(self):
        with patch.dict("sys.modules", {"entirecontext.mcp.server": None}):
            result = runner.invoke(app, ["mcp", "serve"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "MCP server module import failed" in result.stderr

    def test_success(self):
        with patch("entirecontext.mcp.server.run_server") as mock_run:
            result = runner.invoke(app, ["mcp", "serve"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            assert result.stdout == ""

    def test_run_server_import_error_propagates(self):
        """Regression: run_server() raising ImportError must not be swallowed."""
        with patch.object(server_module, "run_server", side_effect=ImportError("boom")):
            result = runner.invoke(app, ["mcp", "serve"])
        assert result.exit_code == 1
        assert "boom" in str(result.exception)
        assert "MCP server module import failed" not in result.stderr

    def test_run_server_sdk_missing_raises(self):
        """When the MCP SDK is unavailable, run_server must raise, not return."""
        with (
            patch.object(server_module, "mcp", None),
            patch.object(server_module, "_MCP_IMPORT_ERROR", ImportError("no mcp")),
        ):
            with pytest.raises(RuntimeError, match="MCP SDK unavailable"):
                server_module.run_server()

    def test_run_server_sdk_missing_message_mentions_install(self):
        """The RuntimeError message includes install guidance but no 'MCP not available' duplicate."""
        with (
            patch.object(server_module, "mcp", None),
            patch.object(server_module, "_MCP_IMPORT_ERROR", ImportError("no mcp")),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                server_module.run_server()
            msg = str(excinfo.value)
            assert "Install the extra" in msg
            assert "MCP not available" not in msg
