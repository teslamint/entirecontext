from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from entirecontext.core.search import (
    _apply_query_redaction,
    _regex_search_content,
    _regex_search_events,
    regex_search,
)
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
    db.commit()
    return db


@pytest.fixture
def conn_with_session(conn):
    session_id = str(uuid4())
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, session_title, session_summary, started_at, last_activity_at) "
        "VALUES (?, ?, 'interactive', 'test session', 'summary', '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
        (session_id, project_id),
    )
    conn.commit()
    return conn, session_id


def _insert_turn(conn, session_id, user_message="hello", assistant_summary="world", timestamp="2025-01-01T00:00:00"):
    turn_id = str(uuid4())
    content_hash = hashlib.md5(f"{user_message}{assistant_summary}".encode()).hexdigest()
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES (?, ?, 1, ?, ?, ?, ?)",
        (turn_id, session_id, user_message, assistant_summary, content_hash, timestamp),
    )
    conn.commit()
    return turn_id


def test_regex_search_events_with_since_filter(conn):
    old_event_id = str(uuid4())
    new_event_id = str(uuid4())
    conn.execute(
        "INSERT INTO events (id, event_type, title, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (old_event_id, "decision", "old deploy", "deployed old version", "active", "2024-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO events (id, event_type, title, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_event_id, "decision", "new deploy", "deployed new version", "active", "2025-06-01T00:00:00"),
    )
    conn.commit()

    results = _regex_search_events(conn, "deploy", since="2025-01-01T00:00:00", limit=10)
    assert len(results) == 1
    assert results[0]["id"] == new_event_id


def test_regex_search_content_match(conn_with_session, tmp_path):
    conn, session_id = conn_with_session
    conn.execute("UPDATE projects SET repo_path = ? WHERE 1=1", (str(tmp_path),))
    conn.commit()

    turn_id = _insert_turn(conn, session_id)

    content_dir = tmp_path / ".entirecontext" / "content"
    content_dir.mkdir(parents=True)
    content_file = content_dir / "turn1.jsonl"
    content_file.write_text("this contains the magic keyword foobar in it\n", encoding="utf-8")

    conn.execute(
        "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, ?)",
        (turn_id, "content/turn1.jsonl", 46, "abc123"),
    )
    conn.commit()

    results = _regex_search_content(conn, "foobar", limit=10)
    assert len(results) == 1
    assert results[0]["turn_id"] == turn_id
    assert results[0]["content_path"] == "content/turn1.jsonl"


def test_regex_search_content_missing_file(conn_with_session):
    conn, session_id = conn_with_session
    turn_id = _insert_turn(conn, session_id)

    conn.execute(
        "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, ?)",
        (turn_id, "content/nonexistent.jsonl", 0, "abc123"),
    )
    conn.commit()

    results = _regex_search_content(conn, "anything", limit=10)
    assert results == []


def test_apply_query_redaction():
    config = {
        "filtering": {
            "query_redaction": {
                "enabled": True,
                "patterns": [r"secret-\w+", r"\d{3}-\d{2}-\d{4}"],
                "replacement": "[REDACTED]",
            }
        }
    }
    results = [
        {"user_message": "my token is secret-abc123", "assistant_summary": "noted"},
        {"title": "SSN is 123-45-6789", "description": "stored"},
    ]
    redacted = _apply_query_redaction(results, config)
    assert redacted[0]["user_message"] == "my token is [REDACTED]"
    assert redacted[1]["title"] == "SSN is [REDACTED]"
    assert redacted[0]["assistant_summary"] == "noted"
    assert redacted[1]["description"] == "stored"


def test_apply_query_redaction_none_config():
    results = [{"user_message": "hello"}]
    assert _apply_query_redaction(results, None) is results


def test_search_turns_null_fields(conn_with_session):
    conn, session_id = conn_with_session
    _insert_turn(conn, session_id, user_message=None, assistant_summary=None)

    results = regex_search(conn, "anything", target="turn", limit=10)
    assert isinstance(results, list)
