"""E5: optimize_for_context_budget tests (PR-E E5).

Covers: min_confidence cut, top_k slice, max_tokens trim, rationale truncation.
"""

from __future__ import annotations

import builtins
import types

from entirecontext.core import decision_prompt_surfacing
from entirecontext.core.decision_prompt_surfacing import optimize_for_context_budget


def _d(title: str, score: float, rank: int = 1, rationale: str = "") -> dict:
    return {
        "id": f"dec-{rank:04d}",
        "title": title,
        "rationale": rationale or f"Rationale for {title}.",
        "staleness_status": "fresh",
        "score": score,
        "rank": rank,
    }


class TestOptimizeForContextBudget:
    def test_min_confidence_cut_removes_low_score(self):
        ranked = [_d("High", 0.9, rank=1), _d("Low", 0.2, rank=2)]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=2000, min_confidence=0.4)
        ids = [d["id"] for d in result]
        assert "dec-0001" in ids
        assert "dec-0002" not in ids

    def test_min_confidence_all_cut_returns_empty(self):
        ranked = [_d("A", 0.1, rank=1), _d("B", 0.2, rank=2)]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=2000, min_confidence=0.5)
        assert result == []

    def test_top_k_limits_count(self):
        ranked = [_d(f"D{i}", 0.8, rank=i + 1) for i in range(10)]
        result = optimize_for_context_budget(ranked, top_k=3, max_tokens=10000, min_confidence=0.0)
        assert len(result) == 3

    def test_max_tokens_trim_removes_lowest_score(self):
        ranked = [
            _d("High score", 0.9, rank=1, rationale="x" * 200),
            _d("Low score", 0.5, rank=2, rationale="y" * 200),
        ]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=50, min_confidence=0.0)
        assert len(result) <= 2

    def test_single_entry_rationale_truncated_when_over_budget(self):
        long_rationale = "A" * 500
        ranked = [_d("Huge", 0.9, rank=1, rationale=long_rationale)]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=10, min_confidence=0.0)
        assert len(result) == 1
        assert len(result[0].get("rationale", "")) <= 105

    def test_single_entry_long_title_truncated_when_over_budget(self):
        long_title = "T" * 200
        ranked = [_d(long_title, 0.9, rank=1, rationale="Short rationale.")]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=10, min_confidence=0.0)
        assert len(result) == 1
        assert len(result[0].get("title", "")) <= 84  # 80 chars + "…"

    def test_empty_input_returns_empty(self):
        assert optimize_for_context_budget([], top_k=5, max_tokens=800, min_confidence=0.4) == []

    def test_all_entries_within_budget_returns_all(self):
        ranked = [_d(f"D{i}", 0.8, rank=i + 1) for i in range(3)]
        result = optimize_for_context_budget(ranked, top_k=5, max_tokens=10000, min_confidence=0.0)
        assert len(result) == 3


class TestEstimateTokens:
    def test_returns_positive_int_for_normal_text(self, monkeypatch):
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_encoding", None)
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_checked", False)
        result = decision_prompt_surfacing._estimate_tokens("normal text")
        assert isinstance(result, int)
        assert result > 0

    def test_falls_back_when_tiktoken_import_fails(self, monkeypatch):
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_encoding", None)
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_checked", False)
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "tiktoken":
                raise ImportError("no tiktoken")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = decision_prompt_surfacing._estimate_tokens("fallback text")

        assert result == max(1, len("fallback text".encode("utf-8")) // 3)
        assert decision_prompt_surfacing._tiktoken_encoding is None
        assert decision_prompt_surfacing._tiktoken_checked is True

    def test_uses_tiktoken_when_available(self, monkeypatch):
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_encoding", None)
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_checked", False)
        real_import = builtins.__import__
        calls = {"get_encoding": 0}

        class FakeEncoding:
            def encode(self, text: str) -> list[int]:
                return [1, 2, 3, 4]

        def fake_get_encoding(name: str):
            calls["get_encoding"] += 1
            assert name == "cl100k_base"
            return FakeEncoding()

        fake_module = types.SimpleNamespace(get_encoding=fake_get_encoding)

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "tiktoken":
                return fake_module
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = decision_prompt_surfacing._estimate_tokens("tokenized text")

        assert result == 4
        assert calls["get_encoding"] == 1

    def test_lazy_singleton_initializes_once(self, monkeypatch):
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_encoding", None)
        monkeypatch.setattr(decision_prompt_surfacing, "_tiktoken_checked", False)
        real_import = builtins.__import__
        calls = {"imports": 0, "get_encoding": 0}

        class FakeEncoding:
            def encode(self, text: str) -> list[int]:
                return list(range(len(text.split()) + 1))

        def fake_get_encoding(name: str):
            calls["get_encoding"] += 1
            assert name == "cl100k_base"
            return FakeEncoding()

        fake_module = types.SimpleNamespace(get_encoding=fake_get_encoding)

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "tiktoken":
                calls["imports"] += 1
                return fake_module
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        first = decision_prompt_surfacing._estimate_tokens("first call")
        second = decision_prompt_surfacing._estimate_tokens("second call")

        assert first > 0
        assert second > 0
        assert calls["imports"] == 1
        assert calls["get_encoding"] == 1
