"""Tests for LLM backend abstraction."""

from __future__ import annotations

import os

import pytest

from entirecontext.core.llm import CLIBackend, OpenAIBackend, get_backend


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
