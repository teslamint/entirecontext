"""Tests for decision hooks."""

from __future__ import annotations

from entirecontext.core.config import DEFAULT_CONFIG


class TestDecisionConfig:
    def test_decisions_section_exists(self):
        assert "decisions" in DEFAULT_CONFIG

    def test_decisions_defaults_all_off(self):
        decisions = DEFAULT_CONFIG["decisions"]
        assert decisions["auto_stale_check"] is False
        assert decisions["auto_extract"] is False
        assert decisions["show_related_on_start"] is False

    def test_extract_keywords_present(self):
        keywords = DEFAULT_CONFIG["decisions"]["extract_keywords"]
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert "decided" in keywords
