"""Tests for decision embedding: build text, semantic search, generate, auto-embed gate."""

from __future__ import annotations

import struct
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4


from entirecontext.core.decisions import create_decision
from entirecontext.core.embedding import (
    _build_decision_embed_text,
    generate_embeddings,
    semantic_search_decisions,
)


# ---------------------------------------------------------------------------
# Helpers (reuse patterns from test_embedding.py)
# ---------------------------------------------------------------------------


def _make_mock_model() -> MagicMock:
    mock_model = MagicMock()
    fake_vector = MagicMock()
    fake_vector.tobytes.return_value = b"\x00" * 1536
    fake_vector.__len__ = lambda self: 384
    mock_model.encode.return_value = fake_vector
    return mock_model


def _patch_sentence_transformers(mock_model: MagicMock) -> Any:
    mock_module = types.ModuleType("sentence_transformers")
    mock_module.SentenceTransformer = MagicMock(return_value=mock_model)
    return patch.dict(sys.modules, {"sentence_transformers": mock_module})


def _make_float_vector(values: list[float]) -> bytes:
    """Build a real float32 byte vector for cosine_similarity."""
    return struct.pack(f"{len(values)}f", *values)


# ---------------------------------------------------------------------------
# _build_decision_embed_text
# ---------------------------------------------------------------------------


class TestBuildDecisionEmbedText:
    def test_title_only(self):
        result = _build_decision_embed_text("Use Redis", None, None)
        assert result == "Use Redis"

    def test_title_and_rationale(self):
        result = _build_decision_embed_text("Use Redis", "Fast caching", None)
        assert result == "Use Redis Fast caching"

    def test_title_rationale_and_alternatives(self):
        import json

        alts = [
            {"alternative": "Memcached", "reason": "less features"},
            {"alternative": "In-memory", "reason": "not persistent"},
        ]
        result = _build_decision_embed_text("Use Redis", "Fast caching", json.dumps(alts))
        assert result == "Use Redis Fast caching Memcached In-memory"

    def test_legacy_strings(self):
        import json

        alts = ["Memcached", "In-memory dict"]
        result = _build_decision_embed_text("Use Redis", "Fast caching", json.dumps(alts))
        assert result == "Use Redis Fast caching Memcached In-memory dict"

    def test_invalid_json_ignored(self):
        result = _build_decision_embed_text("Use Redis", None, "not valid json{{{")
        assert result == "Use Redis"

    def test_empty_title(self):
        result = _build_decision_embed_text("", None, None)
        assert result == ""


# ---------------------------------------------------------------------------
# semantic_search_decisions
# ---------------------------------------------------------------------------


def test_semantic_search_decisions(ec_db):
    """Create 2 decisions, manually insert embedding rows, verify ranking."""
    conn = ec_db

    # Create two decisions
    d1 = create_decision(conn, title="Use Redis for caching")
    d2 = create_decision(conn, title="Use PostgreSQL for storage")

    # Build vectors with known similarity properties:
    # query vector close to d1, far from d2
    dim = 4
    query_vec = _make_float_vector([1.0, 0.0, 0.0, 0.0])
    d1_vec = _make_float_vector([0.9, 0.1, 0.0, 0.0])  # high similarity to query
    d2_vec = _make_float_vector([0.0, 0.0, 1.0, 0.0])  # low similarity to query

    # Insert embedding rows manually
    conn.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
        "VALUES (?, 'decision', ?, 'all-MiniLM-L6-v2', ?, ?, 'hash1')",
        (str(uuid4()), d1["id"], d1_vec, dim),
    )
    conn.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
        "VALUES (?, 'decision', ?, 'all-MiniLM-L6-v2', ?, ?, 'hash2')",
        (str(uuid4()), d2["id"], d2_vec, dim),
    )
    conn.commit()

    # Mock embed_text to return our known query vector
    with patch("entirecontext.core.embedding.embed_text", return_value=query_vec):
        results = semantic_search_decisions(conn, "caching solution")

    assert len(results) == 2
    assert results[0]["decision_id"] == d1["id"]
    assert results[1]["decision_id"] == d2["id"]
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["title"] == "Use Redis for caching"
    assert results[1]["title"] == "Use PostgreSQL for storage"


# ---------------------------------------------------------------------------
# generate_embeddings with decisions
# ---------------------------------------------------------------------------


def test_generate_embeddings_includes_decisions(ec_db):
    conn = ec_db
    create_decision(conn, title="Use WAL mode for SQLite")

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        count = generate_embeddings(conn, "/tmp/test-repo")

    assert count >= 1
    rows = conn.execute("SELECT * FROM embeddings WHERE source_type = 'decision'").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] is not None


def test_generate_embeddings_skip_existing_decisions(ec_db):
    conn = ec_db
    create_decision(conn, title="Use WAL mode for SQLite")

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        first_count = generate_embeddings(conn, "/tmp/test-repo")
        assert first_count >= 1

        second_count = generate_embeddings(conn, "/tmp/test-repo")
        assert second_count == 0


def test_generate_embeddings_no_writer_tx_when_all_embedded(ec_db, monkeypatch):
    """When all turns/sessions/decisions are already embedded, generate_embeddings()
    should return 0 WITHOUT opening a writer transaction."""
    conn = ec_db
    create_decision(conn, title="Use WAL mode for SQLite")

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        first_count = generate_embeddings(conn, "/tmp/test-repo")
        assert first_count >= 1

        def _fail_transaction(conn):
            raise AssertionError("transaction() must not be called when all embeddings already exist")

        monkeypatch.setattr("entirecontext.core.embedding.transaction", _fail_transaction)

        second_count = generate_embeddings(conn, "/tmp/test-repo")

    assert second_count == 0


# ---------------------------------------------------------------------------
# create_decision auto-embed gate
# ---------------------------------------------------------------------------


def test_create_decision_auto_embed_gate(ec_repo, ec_db, monkeypatch):
    conn = ec_db
    repo_path = str(ec_repo)
    mock_model = _make_mock_model()

    # Test with auto_embed=True: embedding should be created
    def _config_auto_embed_on(path=None):
        return {"decisions": {"auto_embed": True}}

    monkeypatch.setattr("entirecontext.core.config.load_config", _config_auto_embed_on)

    with _patch_sentence_transformers(mock_model):
        d1 = create_decision(conn, title="Auto-embedded decision", repo_path=repo_path)

    rows = conn.execute("SELECT * FROM embeddings WHERE source_type = 'decision'").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == d1["id"]

    # Clean up for next assertion
    conn.execute("DELETE FROM embeddings WHERE source_type = 'decision'")
    conn.commit()

    # Test with auto_embed=False: no embedding should be created
    def _config_auto_embed_off(path=None):
        return {"decisions": {"auto_embed": False}}

    monkeypatch.setattr("entirecontext.core.config.load_config", _config_auto_embed_off)

    with _patch_sentence_transformers(mock_model):
        create_decision(conn, title="Not auto-embedded", repo_path=repo_path)

    rows = conn.execute("SELECT * FROM embeddings WHERE source_type = 'decision'").fetchall()
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# stale re-embed and duplicate cleanup
# ---------------------------------------------------------------------------


def test_generate_embeddings_re_embeds_stale_decision(ec_db):
    """When a decision's content changes, the old embedding is replaced."""
    conn = ec_db
    d = create_decision(conn, title="Original title")

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        count = generate_embeddings(conn, "/tmp/test-repo")
    assert count >= 1

    old_hash = conn.execute(
        "SELECT text_hash FROM embeddings WHERE source_type = 'decision' AND source_id = ?",
        (d["id"],),
    ).fetchone()["text_hash"]

    conn.execute("UPDATE decisions SET title = ? WHERE id = ?", ("Changed title", d["id"]))

    with _patch_sentence_transformers(mock_model):
        count = generate_embeddings(conn, "/tmp/test-repo")
    assert count >= 1

    rows = conn.execute(
        "SELECT text_hash FROM embeddings WHERE source_type = 'decision' AND source_id = ?",
        (d["id"],),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["text_hash"] != old_hash


def test_generate_embeddings_deduplicates_decisions(ec_db):
    """Pre-existing duplicate embeddings are cleaned up to exactly one row."""
    conn = ec_db
    d = create_decision(conn, title="Dedup target")

    import hashlib

    text = "Dedup target"
    text_hash = hashlib.md5(text.encode()).hexdigest()
    for _ in range(3):
        conn.execute(
            "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
            "VALUES (?, 'decision', ?, 'all-MiniLM-L6-v2', ?, 384, ?)",
            (str(uuid4()), d["id"], b"\x00" * 1536, text_hash),
        )

    dupes = conn.execute(
        "SELECT COUNT(*) AS cnt FROM embeddings WHERE source_type = 'decision' AND source_id = ?",
        (d["id"],),
    ).fetchone()["cnt"]
    assert dupes == 3

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        generate_embeddings(conn, "/tmp/test-repo")

    rows = conn.execute(
        "SELECT * FROM embeddings WHERE source_type = 'decision' AND source_id = ?",
        (d["id"],),
    ).fetchall()
    assert len(rows) == 1
