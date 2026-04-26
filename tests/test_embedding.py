from __future__ import annotations

import hashlib
import sys
import types
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from entirecontext.core.embedding import generate_embeddings
from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema


@pytest.fixture
def conn():
    db = get_memory_db()
    init_schema(db)
    project_id = str(uuid4())
    db.execute(
        "INSERT INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        (project_id, "test-repo", "/tmp/test-repo"),
    )
    session_id = str(uuid4())
    db.execute(
        "INSERT INTO sessions (id, project_id, session_type, session_title, session_summary, started_at, last_activity_at) "
        "VALUES (?, ?, 'interactive', 'test session', 'session summary', '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
        (session_id, project_id),
    )
    db.commit()
    return db, session_id


def _make_mock_model():
    mock_model = MagicMock()
    fake_vector = MagicMock()
    fake_vector.tobytes.return_value = b"\x00" * 1536
    fake_vector.__len__ = lambda self: 384
    mock_model.encode.return_value = fake_vector
    return mock_model


def _patch_sentence_transformers(mock_model):
    mock_module = types.ModuleType("sentence_transformers")
    mock_module.SentenceTransformer = MagicMock(return_value=mock_model)
    return patch.dict(sys.modules, {"sentence_transformers": mock_module})


def _seed_turn(conn, session_id, user_message="hello", assistant_summary="world"):
    turn_id = str(uuid4())
    content_hash = hashlib.md5(f"{user_message}{assistant_summary}".encode()).hexdigest()
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES (?, ?, 1, ?, ?, ?, '2025-01-01T00:00:00')",
        (turn_id, session_id, user_message, assistant_summary, content_hash),
    )
    conn.commit()
    return turn_id


def test_generate_embeddings_basic(conn):
    db, session_id = conn
    _seed_turn(db, session_id, "implement auth", "added auth module")
    mock_model = _make_mock_model()

    with _patch_sentence_transformers(mock_model):
        count = generate_embeddings(db, "/tmp/test-repo")

    assert count == 2
    rows = db.execute("SELECT * FROM embeddings").fetchall()
    assert len(rows) == 2
    source_types = {r["source_type"] for r in rows}
    assert source_types == {"turn", "session"}


def test_generate_embeddings_skip_existing(conn):
    db, session_id = conn
    _seed_turn(db, session_id, "implement auth", "added auth module")
    mock_model = _make_mock_model()

    with _patch_sentence_transformers(mock_model):
        first_count = generate_embeddings(db, "/tmp/test-repo")
        assert first_count == 2

        second_count = generate_embeddings(db, "/tmp/test-repo")
        assert second_count == 0

    rows = db.execute("SELECT * FROM embeddings").fetchall()
    assert len(rows) == 2


def test_generate_embeddings_skip_existing_does_not_open_writer_transaction(conn, monkeypatch):
    db, session_id = conn
    _seed_turn(db, session_id, "implement auth", "added auth module")
    mock_model = _make_mock_model()

    with _patch_sentence_transformers(mock_model):
        first_count = generate_embeddings(db, "/tmp/test-repo")
        assert first_count == 2

        def _fail_transaction(conn):
            raise AssertionError("transaction() must not be called when all embeddings already exist")

        monkeypatch.setattr("entirecontext.core.embedding.transaction", _fail_transaction)

        second_count = generate_embeddings(db, "/tmp/test-repo")

    assert second_count == 0


def test_generate_embeddings_force(conn):
    db, session_id = conn
    _seed_turn(db, session_id, "implement auth", "added auth module")
    mock_model = _make_mock_model()

    with _patch_sentence_transformers(mock_model):
        first_count = generate_embeddings(db, "/tmp/test-repo")
        assert first_count == 2

        force_count = generate_embeddings(db, "/tmp/test-repo", force=True)
        assert force_count == 2

    rows = db.execute("SELECT * FROM embeddings").fetchall()
    assert len(rows) == 2


def test_generate_embeddings_null_text(conn):
    db, session_id = conn
    turn_id = str(uuid4())
    content_hash = hashlib.md5(b"").hexdigest()
    db.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES (?, ?, 1, NULL, NULL, ?, '2025-01-01T00:00:00')",
        (turn_id, session_id, content_hash),
    )
    db.execute(
        "UPDATE sessions SET session_title = NULL, session_summary = NULL WHERE id = ?",
        (session_id,),
    )
    db.commit()

    mock_model = _make_mock_model()
    with _patch_sentence_transformers(mock_model):
        count = generate_embeddings(db, "/tmp/test-repo")

    assert count == 0
    mock_model.encode.assert_not_called()


def test_generate_embeddings_import_error():
    db = get_memory_db()
    init_schema(db)

    with patch.dict("sys.modules", {"sentence_transformers": None}):
        with pytest.raises(ImportError, match="sentence-transformers is required"):
            generate_embeddings(db, "/tmp/test-repo")
