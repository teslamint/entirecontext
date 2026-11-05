"""Opt-in semantic signal tests for the decision ranker."""

from entirecontext.core.config import DEFAULT_CONFIG
from entirecontext.core.decisions import rank_related_decisions


def _seed(conn):
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, updated_at) VALUES ('semantic', 'unrelated words', 'none', '2020-01-01')"
    )
    conn.execute("INSERT INTO decisions (id, title, rationale) VALUES ('baseline', 'matching keyword', 'none')")
    # 25 newer decisions fill the recent-decision padding, so 'semantic' can enter only through its score.
    for i in range(25):
        conn.execute(
            "INSERT INTO decisions (id, title, rationale, updated_at) VALUES (?, 'filler entry', 'none', '2030-01-01')",
            (f"filler-{i}",),
        )
    conn.commit()


def test_semantic_only_candidate_surfaces(ec_db):
    _seed(ec_db)
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        semantic_scores={"semantic": 0.8},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    match = next(item for item in ranked if item["id"] == "semantic")
    assert match["score_breakdown"]["semantic"] == 2.4
    assert match["base_score"] >= 2.4


def test_semantic_below_threshold_adds_nothing(ec_db):
    _seed(ec_db)
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        semantic_scores={"semantic": 0.29},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    assert "semantic" not in {item["id"] for item in ranked}


def test_without_semantic_scores_breakdown_is_unchanged(ec_db):
    """MCP and CLI callers pass no scores; their score_breakdown keys must not change."""
    _seed(ec_db)
    ranked = rank_related_decisions(ec_db, diff_text="matching keyword")
    assert ranked
    assert all("semantic" not in item["score_breakdown"] for item in ranked)
    assert "semantic" not in {item["id"] for item in ranked}
    assert DEFAULT_CONFIG["decisions"]["semantic"]["enabled"] is False


def test_semantic_candidate_respects_until(ec_db):
    """A decision created after the cutoff stays out even with a high semantic score."""
    _seed(ec_db)
    ec_db.execute(
        "INSERT INTO decisions (id, title, rationale, created_at) VALUES ('future', 'later', 'none', '2027-01-01')"
    )
    ec_db.commit()
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        until="2026-01-01",
        semantic_scores={"future": 0.99},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    assert "future" not in {item["id"] for item in ranked}
