"""Tests for LLM backend abstraction."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from entirecontext.core.llm import (
    CLIBackend,
    GitHubModelsBackend,
    OllamaBackend,
    OpenAIBackend,
    get_backend,
    strip_markdown_fences,
)


def test_get_backend_openai():
    backend = get_backend("openai")
    assert isinstance(backend, OpenAIBackend)
    assert backend.model == "gpt-4o-mini"


def test_get_backend_openai_custom_model():
    backend = get_backend("openai", model="gpt-4o")
    assert isinstance(backend, OpenAIBackend)
    assert backend.model == "gpt-4o"


def test_get_backend_codex():
    backend = get_backend("codex")
    assert isinstance(backend, CLIBackend)
    assert backend.command == "codex"


def test_get_backend_claude():
    backend = get_backend("claude")
    assert isinstance(backend, CLIBackend)
    assert backend.command == "claude"


def test_get_backend_unknown():
    with pytest.raises(ValueError, match="Unknown backend"):
        get_backend("nonexistent")


def test_openai_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAIBackend()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        backend.complete("system", "user")


class TestStripMarkdownFences:
    def test_strips_json_fences(self):
        assert strip_markdown_fences('```json\n{"key": "value"}\n```') == '{"key": "value"}'

    def test_strips_python_fences(self):
        assert strip_markdown_fences("```python\nprint('hello')\n```") == "print('hello')"

    def test_no_fences_passthrough(self):
        assert strip_markdown_fences("plain text") == "plain text"

    def test_empty_string(self):
        assert strip_markdown_fences("") == ""


class TestOpenAIBackendComplete:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        backend = OpenAIBackend()
        response_body = json.dumps({"choices": [{"message": {"content": "test response"}}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("entirecontext.core.llm.urlopen", return_value=mock_resp) as mock_urlopen:
            result = backend.complete("system prompt", "user prompt")
            assert result == "test response"
            mock_urlopen.assert_called_once()

    def test_http_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        backend = OpenAIBackend()
        with patch("entirecontext.core.llm.urlopen", side_effect=URLError("connection refused")):
            with pytest.raises(URLError):
                backend.complete("system prompt", "user prompt")


class TestCLIBackendComplete:
    def test_codex_returns_stdout(self):
        backend = CLIBackend(command="codex")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "codex output"
        with patch("entirecontext.core.llm.subprocess.run", return_value=mock_result):
            result = backend.complete("system", "user")
            assert result == "codex output"

    def test_claude_returns_parsed_json(self):
        backend = CLIBackend(command="claude")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"result": "answer"})
        with patch("entirecontext.core.llm.subprocess.run", return_value=mock_result):
            result = backend.complete("system", "user")
            assert result == "answer"

    def test_nonzero_exit_raises(self):
        backend = CLIBackend(command="codex")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"
        with patch("entirecontext.core.llm.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="codex failed"):
                backend.complete("system", "user")

    def test_timeout_raises(self):
        backend = CLIBackend(command="codex")
        with patch(
            "entirecontext.core.llm.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=120),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                backend.complete("system", "user")


class TestOllamaBackendComplete:
    def test_success(self):
        backend = OllamaBackend()
        response_body = json.dumps({"message": {"content": "ollama response"}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("entirecontext.core.llm.urlopen", return_value=mock_resp):
            result = backend.complete("system", "user")
            assert result == "ollama response"


class TestGitHubModelsBackendComplete:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-token")
        backend = GitHubModelsBackend()
        response_body = json.dumps({"choices": [{"message": {"content": "github response"}}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("entirecontext.core.llm.urlopen", return_value=mock_resp):
            result = backend.complete("system", "user")
            assert result == "github response"

    def test_no_github_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        backend = GitHubModelsBackend()
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            backend.complete("system", "user")
