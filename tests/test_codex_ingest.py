"""Tests for Codex notify ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from entirecontext.db import get_db
from entirecontext.hooks.codex_ingest import ingest_codex_notify_event


def _write_codex_session_file(codex_home: Path, *, session_id: str, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "02" / "24"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"rollout-2026-02-24T00-00-00-{session_id}.jsonl"
    records = [
        {
            "timestamp": "2026-02-24T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-02-24T00:00:00Z", "cwd": cwd},
        },
        {
            "timestamp": "2026-02-24T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        },
        {
            "timestamp": "2026-02-24T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "world"}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_ingest_codex_notify_event_creates_session_and_turn(ec_repo):
    codex_home = ec_repo.parent / "codex-home"
    session_id = "s-codex-1"
    _write_codex_session_file(codex_home, session_id=session_id, cwd=str(ec_repo))

    ingest_codex_notify_event(
        {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)},
        payload_text='{"thread_id":"s-codex-1"}',
    )

    conn = get_db(str(ec_repo))
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    turn = conn.execute("SELECT * FROM turns WHERE session_id = ?", (session_id,)).fetchone()
    content = conn.execute("SELECT * FROM turn_content WHERE turn_id = ?", (turn["id"],)).fetchone()
    conn.close()

    assert session is not None
    assert session["session_type"] == "codex"
    assert turn is not None
    assert turn["user_message"] == "hello"
    assert turn["assistant_summary"] == "world"
    assert content is not None


def test_ingest_codex_notify_event_is_idempotent(ec_repo):
    codex_home = ec_repo.parent / "codex-home"
    session_id = "s-codex-2"
    _write_codex_session_file(codex_home, session_id=session_id, cwd=str(ec_repo))

    payload = {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)}
    ingest_codex_notify_event(payload, payload_text="{}")
    ingest_codex_notify_event(payload, payload_text="{}")

    conn = get_db(str(ec_repo))
    turn_count = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
    conn.close()
    assert turn_count == 1
