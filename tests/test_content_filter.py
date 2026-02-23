"""Tests for content filtering engine."""

from __future__ import annotations

from entirecontext.core.content_filter import (
    redact_content,
    redact_for_query,
    should_skip_file,
    should_skip_tool,
    should_skip_turn,
)


def _config(exclusions=None, query_redaction=None):
    cfg = {"capture": {"exclusions": exclusions or {}}}
    if query_redaction is not None:
        cfg["filtering"] = {"query_redaction": query_redaction}
    return cfg


class TestShouldSkipTurn:
    def test_match_returns_true(self):
        cfg = _config({"enabled": True, "content_patterns": [r"password\s*="]})
        assert should_skip_turn("password=abc", cfg) is True

    def test_no_match_returns_false(self):
        cfg = _config({"enabled": True, "content_patterns": [r"password\s*="]})
        assert should_skip_turn("normal text", cfg) is False

    def test_empty_patterns(self):
        cfg = _config({"enabled": True, "content_patterns": []})
        assert should_skip_turn("password=abc", cfg) is False

    def test_disabled(self):
        cfg = _config({"enabled": False, "content_patterns": [r"password\s*="]})
        assert should_skip_turn("password=abc", cfg) is False

    def test_invalid_regex(self):
        cfg = _config({"enabled": True, "content_patterns": ["[invalid"]})
        assert should_skip_turn("test", cfg) is False


class TestShouldSkipFile:
    def test_env_match(self):
        cfg = _config({"enabled": True, "file_patterns": [".env"]})
        assert should_skip_file(".env", cfg) is True

    def test_glob_match(self):
        cfg = _config({"enabled": True, "file_patterns": ["*.pem"]})
        assert should_skip_file("server.pem", cfg) is True

    def test_glob_match_nested(self):
        cfg = _config({"enabled": True, "file_patterns": ["credentials/*"]})
        assert should_skip_file("credentials/aws.json", cfg) is True

    def test_no_match(self):
        cfg = _config({"enabled": True, "file_patterns": [".env"]})
        assert should_skip_file("src/main.py", cfg) is False

    def test_disabled(self):
        cfg = _config({"enabled": False, "file_patterns": [".env"]})
        assert should_skip_file(".env", cfg) is False


class TestShouldSkipTool:
    def test_match(self):
        cfg = _config({"enabled": True, "tool_names": ["Bash"]})
        assert should_skip_tool("Bash", cfg) is True

    def test_no_match(self):
        cfg = _config({"enabled": True, "tool_names": ["Bash"]})
        assert should_skip_tool("Edit", cfg) is False


class TestRedactContent:
    def test_replaces_pattern(self):
        cfg = _config({"enabled": True, "redact_patterns": [r"password\s*=\s*\S+"]})
        result = redact_content("password=secret", cfg)
        assert "[FILTERED]" in result
        assert "secret" not in result

    def test_multiple_patterns(self):
        cfg = _config({"enabled": True, "redact_patterns": [r"password\s*=\s*\S+", r"token\s*=\s*\S+"]})
        result = redact_content("password=secret token=abc123", cfg)
        assert "secret" not in result
        assert "abc123" not in result

    def test_empty_patterns(self):
        cfg = _config({"enabled": True, "redact_patterns": []})
        assert redact_content("password=secret", cfg) == "password=secret"

    def test_disabled(self):
        cfg = _config({"enabled": False, "redact_patterns": [r"password\s*=\s*\S+"]})
        assert redact_content("password=secret", cfg) == "password=secret"

    def test_invalid_regex(self):
        cfg = _config({"enabled": True, "redact_patterns": ["[invalid", r"token\s*=\s*\S+"]})
        result = redact_content("token=abc123", cfg)
        assert "abc123" not in result


class TestRedactForQuery:
    def test_enabled(self):
        cfg = _config(query_redaction={"enabled": True, "patterns": [r"password\s*=\s*\S+"]})
        result = redact_for_query("password=secret", cfg)
        assert "[FILTERED]" in result
        assert "secret" not in result

    def test_disabled(self):
        cfg = _config(query_redaction={"enabled": False, "patterns": [r"password\s*=\s*\S+"]})
        assert redact_for_query("password=secret", cfg) == "password=secret"

    def test_custom_replacement(self):
        cfg = _config(query_redaction={"enabled": True, "patterns": [r"password\s*=\s*\S+"], "replacement": "***"})
        result = redact_for_query("password=secret", cfg)
        assert "***" in result
        assert "secret" not in result
