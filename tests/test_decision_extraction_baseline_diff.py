"""Baseline ranking diff measurement for accepted_boost (B2).

Verifies that enabling the accepted_boost (0.10, threshold 0.6) does not
destabilise the top-N ranking of a realistic decision corpus.

Acceptance gates (matching plan AC #5):
- top-10 set overlap between boost-OFF and boost-ON ≥ 90 %
- mean confidence delta (absolute) across the corpus ≤ 0.05
- fraction of decisions receiving a boost ≤ 30 %

The test seeds 60 decisions with a distribution of outcome patterns that
reflects realistic usage: majority accepted, minority contradicted, mixed,
and single-outcome (smoothing-guard) cases. Confidence scores are drawn
from a fixed range to avoid artificial clustering.
"""

from __future__ import annotations

import random

import pytest


def _make_stats(accepted: int, contradicted: int, ignored: int = 0) -> dict[str, int]:
    total = accepted + contradicted + ignored
    return {
        "accepted": accepted,
        "contradicted": contradicted,
        "ignored": ignored,
        "refined": 0,
        "replaced": 0,
        "total": total,
    }


@pytest.fixture()
def corpus():
    """60 synthetic (confidence, stats) pairs with a production-realistic outcome distribution.

    Most decisions in a real corpus are never explicitly rated. Among those that
    are, a minority receive 2+ accepted outcomes (boost gate). The distribution:
    - 30 no-outcome decisions (scored_total=0)  → no boost, no penalty
    - 10 single-outcome (smoothing guard)        → no boost
    -  8 clearly accepted, ratio > 0.6, n>=2    → BOOST eligible  (13% of corpus)
    -  7 mixed, ratio ≤ 0.6                     → no boost, no penalty
    -  5 contradicted-dominant                  → penalty only
    """
    rng = random.Random(42)
    entries = []

    # 30 decisions with no recorded outcomes
    for _ in range(30):
        entries.append((rng.uniform(0.40, 0.90), _make_stats(0, 0, 0)))

    # 10 single-outcome (smoothing guard: scored_total < 2 → no boost)
    for _ in range(10):
        entries.append((rng.uniform(0.50, 0.85), _make_stats(1, 0)))

    # 8 clearly accepted (ratio > 0.6, scored_total >= 2) — boost eligible
    for _ in range(8):
        acc = rng.randint(3, 5)
        entries.append((rng.uniform(0.55, 0.85), _make_stats(acc, 0)))

    # 7 mixed, accepted ratio ≤ 0.6 — no boost, no penalty
    for _ in range(7):
        entries.append((rng.uniform(0.50, 0.80), _make_stats(2, 0, 2)))  # ratio = 0.5

    # 5 contradicted-dominant — penalty path
    for _ in range(5):
        con = rng.randint(3, 4)
        acc = rng.randint(0, 1)
        entries.append((rng.uniform(0.50, 0.80), _make_stats(acc, con)))

    return entries


class TestAcceptedBoostBaselineDiff:
    """Quantitative gate: accepted_boost must not destabilise ranking."""

    def _run_feedback(self, corpus, *, boost: float) -> list[float]:
        from entirecontext.core.decision_extraction import apply_outcome_feedback_to_confidence

        results = []
        for confidence, stats in corpus:
            adjusted, _ = apply_outcome_feedback_to_confidence(
                confidence,
                {"final": confidence},
                stats,
                penalty=0.15,
                boost=boost,
                boost_threshold=0.6,
            )
            results.append(adjusted)
        return results

    def test_top10_overlap_at_least_90pct(self, corpus):
        off_scores = self._run_feedback(corpus, boost=0.0)
        on_scores = self._run_feedback(corpus, boost=0.10)

        ranked_off = sorted(range(len(off_scores)), key=lambda i: off_scores[i], reverse=True)
        ranked_on = sorted(range(len(on_scores)), key=lambda i: on_scores[i], reverse=True)

        top10_off = set(ranked_off[:10])
        top10_on = set(ranked_on[:10])
        overlap = len(top10_off & top10_on) / 10.0
        assert overlap >= 0.90, f"top-10 overlap {overlap:.0%} < 90% — boost destabilises ranking"

    def test_mean_confidence_delta_at_most_005(self, corpus):
        off_scores = self._run_feedback(corpus, boost=0.0)
        on_scores = self._run_feedback(corpus, boost=0.10)

        deltas = [abs(on - off) for on, off in zip(on_scores, off_scores)]
        mean_delta = sum(deltas) / len(deltas)
        assert mean_delta <= 0.05, f"mean confidence delta {mean_delta:.4f} > 0.05"

    def test_boost_fraction_at_most_30pct(self, corpus):
        from entirecontext.core.decision_extraction import apply_outcome_feedback_to_confidence

        boosted = 0
        for confidence, stats in corpus:
            _, bd = apply_outcome_feedback_to_confidence(
                confidence,
                {"final": confidence},
                stats,
                penalty=0.15,
                boost=0.10,
                boost_threshold=0.6,
            )
            if bd["outcome_feedback"]["boost_applied"]:
                boosted += 1

        fraction = boosted / len(corpus)
        assert fraction <= 0.30, f"boost applied to {fraction:.0%} of corpus — exceeds 30% gate"
