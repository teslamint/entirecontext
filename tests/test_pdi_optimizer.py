"""E5: optimize_for_context_budget tests (PR-E E5).

Covers: min_confidence cut, top_k slice, max_tokens trim, rationale truncation.
"""

from __future__ import annotations

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
