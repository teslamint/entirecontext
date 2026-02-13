"""FTS index rebuild and embedding generation."""

from __future__ import annotations

import hashlib
import sqlite3
from uuid import uuid4


def rebuild_fts_indexes(conn: sqlite3.Connection) -> dict:
    """Rebuild FTS5 content-sync tables using the FTS5 'rebuild' command."""
    counts = {}

    conn.execute("INSERT INTO fts_turns(fts_turns) VALUES('rebuild')")
    counts["fts_turns"] = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]

    conn.execute("INSERT INTO fts_events(fts_events) VALUES('rebuild')")
    counts["fts_events"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    conn.execute("INSERT INTO fts_sessions(fts_sessions) VALUES('rebuild')")
    counts["fts_sessions"] = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    conn.commit()
    return counts


def generate_embeddings(
    conn: sqlite3.Connection,
    repo_path: str,
    model_name: str = "all-MiniLM-L6-v2",
    force: bool = False,
) -> int:
    """Generate embeddings for turns/sessions without existing embeddings.

    Returns the count of new embeddings generated.
    Requires sentence-transformers to be installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers is required for embedding generation. "
            "Install with: pip install 'entirecontext[semantic]'"
        )

    model = SentenceTransformer(model_name)
    count = 0

    if force:
        existing_turn_ids: set[str] = set()
        existing_session_ids: set[str] = set()
    else:
        rows = conn.execute(
            "SELECT source_id FROM embeddings WHERE source_type = 'turn' AND model_name = ?",
            (model_name,),
        ).fetchall()
        existing_turn_ids = {r[0] for r in rows}

        rows = conn.execute(
            "SELECT source_id FROM embeddings WHERE source_type = 'session' AND model_name = ?",
            (model_name,),
        ).fetchall()
        existing_session_ids = {r[0] for r in rows}

    turns = conn.execute("SELECT id, user_message, assistant_summary FROM turns").fetchall()
    for turn in turns:
        if not force and turn["id"] in existing_turn_ids:
            continue
        text = f"{turn['user_message'] or ''} {turn['assistant_summary'] or ''}".strip()
        if not text:
            continue
        vector = model.encode(text)
        vector_bytes = vector.tobytes()
        text_hash = hashlib.md5(text.encode()).hexdigest()

        if force:
            conn.execute(
                "DELETE FROM embeddings WHERE source_type = 'turn' AND source_id = ? AND model_name = ?",
                (turn["id"], model_name),
            )

        conn.execute(
            "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), "turn", turn["id"], model_name, vector_bytes, len(vector), text_hash),
        )
        count += 1

    sessions = conn.execute("SELECT id, session_title, session_summary FROM sessions").fetchall()
    for session in sessions:
        if not force and session["id"] in existing_session_ids:
            continue
        text = f"{session['session_title'] or ''} {session['session_summary'] or ''}".strip()
        if not text:
            continue
        vector = model.encode(text)
        vector_bytes = vector.tobytes()
        text_hash = hashlib.md5(text.encode()).hexdigest()

        if force:
            conn.execute(
                "DELETE FROM embeddings WHERE source_type = 'session' AND source_id = ? AND model_name = ?",
                (session["id"], model_name),
            )

        conn.execute(
            "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), "session", session["id"], model_name, vector_bytes, len(vector), text_hash),
        )
        count += 1

    conn.commit()
    return count
