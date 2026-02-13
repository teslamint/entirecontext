"""Semantic embedding and similarity search."""

from __future__ import annotations

import sqlite3
import struct


def embed_text(text: str, model_name: str = "all-MiniLM-L6-v2") -> bytes:
    """Encode text to embedding bytes using sentence-transformers."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers is required for semantic search. Install with: pip install 'entirecontext[semantic]'"
        )

    model = SentenceTransformer(model_name)
    vector = model.encode(text)
    return vector.tobytes()


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding byte vectors."""
    n = len(a) // 4
    if len(b) // 4 != n:
        raise ValueError(f"Dimension mismatch: {n} vs {len(b) // 4}")

    vec_a = struct.unpack(f"{n}f", a)
    vec_b = struct.unpack(f"{n}f", b)

    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    norm_a = sum(x * x for x in vec_a) ** 0.5
    norm_b = sum(x * x for x in vec_b) ** 0.5

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    model_name: str = "all-MiniLM-L6-v2",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Embed query and compare against stored embeddings.

    Returns ranked results with similarity scores.
    Supports post-filters: file_filter, commit_filter, agent_filter, since.
    """
    query_embedding = embed_text(query, model_name)

    rows = conn.execute(
        "SELECT id, source_type, source_id, vector FROM embeddings WHERE model_name = ?",
        (model_name,),
    ).fetchall()

    scored = []
    for row in rows:
        score = cosine_similarity(query_embedding, row["vector"])
        scored.append(
            {
                "embedding_id": row["id"],
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "score": score,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    fetch_limit = limit * 5 if any([file_filter, commit_filter, agent_filter, since]) else limit
    top = scored[:fetch_limit]

    results = []
    for item in top:
        result = {
            "source_type": item["source_type"],
            "source_id": item["source_id"],
            "id": item["source_id"],
            "score": round(item["score"], 4),
        }

        if item["source_type"] == "turn":
            turn = conn.execute(
                "SELECT id, session_id, user_message, assistant_summary, timestamp, "
                "files_touched, git_commit_hash FROM turns WHERE id = ?",
                (item["source_id"],),
            ).fetchone()
            if turn:
                result["user_message"] = turn["user_message"]
                result["assistant_summary"] = turn["assistant_summary"]
                result["session_id"] = turn["session_id"]
                result["timestamp"] = turn["timestamp"]
                result["files_touched"] = turn["files_touched"]
                result["git_commit_hash"] = turn["git_commit_hash"]
            else:
                continue
        elif item["source_type"] == "session":
            session = conn.execute(
                "SELECT id, session_title, session_summary, started_at FROM sessions WHERE id = ?",
                (item["source_id"],),
            ).fetchone()
            if session:
                result["session_title"] = session["session_title"]
                result["session_summary"] = session["session_summary"]
                result["started_at"] = session["started_at"]
            else:
                continue

        if file_filter and result.get("source_type") == "turn":
            ft = result.get("files_touched")
            if not ft or file_filter not in ft:
                continue

        if commit_filter and result.get("source_type") == "turn":
            if not (result.get("git_commit_hash") or "").startswith(commit_filter):
                continue

        if agent_filter and result.get("source_type") == "turn":
            session_row = conn.execute(
                "SELECT session_type FROM sessions WHERE id = ?",
                (result.get("session_id"),),
            ).fetchone()
            if not session_row or session_row["session_type"] != agent_filter:
                continue

        if since:
            ts = result.get("timestamp") or result.get("started_at") or ""
            if ts < since:
                continue

        results.append(result)
        if len(results) >= limit:
            break

    return results
