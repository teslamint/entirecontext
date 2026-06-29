"""Tests for LLM backend output parsing."""

from __future__ import annotations

import json
from unittest.mock import patch

from entirecontext.core.llm import CLIBackend


class TestCLIBackendClaude:
    """CLIBackend must unwrap claude --output-format json output."""

    def _make_claude_output(self, result_text: str) -> str:
        """Build a realistic claude --output-format json response."""
        events = [
            {"type": "system", "subtype": "init", "session_id": "test-123", "tools": []},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": result_text}]}},
            {"type": "result", "subtype": "success", "result": result_text, "session_id": "test-123"},
        ]
        return json.dumps(events)

    @patch("entirecontext.core.llm.subprocess.run")
    def test_unwraps_json_array_response(self, mock_run):
        """claude output is a JSON array; result is in the {type:result} item."""
        result_text = '[{"title": "Use Redis", "rationale": "faster"}]'
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": self._make_claude_output(result_text),
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == result_text

    @patch("entirecontext.core.llm.subprocess.run")
    def test_unwraps_dict_response(self, mock_run):
        """Backward compat: dict envelope still works."""
        result_text = "[]"
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"result": result_text, "type": "result"}),
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == result_text

    @patch("entirecontext.core.llm.subprocess.run")
    def test_returns_raw_on_unparseable(self, mock_run):
        """If output is not valid JSON, return as-is."""
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "not json at all",
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == "not json at all"

    @patch("entirecontext.core.llm.subprocess.run")
    def test_codex_backend_passthrough(self, mock_run):
        """Codex backend should not apply claude unwrap logic."""
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "raw codex output",
            "stderr": "",
        })()

        backend = CLIBackend(command="codex")
        output = backend.complete("system prompt", "user text")

        assert output == "raw codex output"
