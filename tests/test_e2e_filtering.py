"""E2E tests for content filtering and selective capture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_start
from entirecontext.hooks.turn_capture import on_user_prompt


class TestCaptureTimeFiltering:
    @pytest.fixture
    def filtering_repo(self, ec_repo, isolated_global_config):
        config_path = Path(str(ec_repo)) / ".entirecontext" / "config.toml"
        config_path.write_text(
            """
[capture.exclusions]
enabled = true
content_patterns = ["password\\\\s*="]
redact_patterns = ["token\\\\s*=\\\\s*\\\\S+"]
file_patterns = [".env"]
tool_names = ["Bash"]
""",
            encoding="utf-8",
        )
        return ec_repo

    def test_excluded_turn_not_stored(self, filtering_repo, transcript_file):
        cwd = str(filtering_repo)
        sid = "filter-session"
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "password=secret123"})

        conn = get_db(cwd)
        turns = conn.execute("SELECT * FROM turns WHERE session_id = ?", (sid,)).fetchall()
        conn.close()
        assert len(turns) == 0

    def test_redacted_content_in_db_and_jsonl(self, filtering_repo, transcript_file):
        cwd = str(filtering_repo)
        sid = "filter-session-2"
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "fix token=abc123 issue"})

        conn = get_db(cwd)
        turn = conn.execute("SELECT * FROM turns WHERE session_id = ?", (sid,)).fetchone()
        conn.close()
        assert turn is not None
        assert "abc123" not in turn["user_message"]
        assert "[FILTERED]" in turn["user_message"]


class TestSelectiveCaptureToggle:
    def test_capture_disabled_skips_all(self, ec_repo, isolated_global_config):
        config_path = Path(str(ec_repo)) / ".entirecontext" / "config.toml"
        config_path.write_text(
            """
[capture]
auto_capture = false
""",
            encoding="utf-8",
        )

        cwd = str(ec_repo)
        sid = "disabled-session"
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "do something"})

        conn = get_db(cwd)
        turns = conn.execute("SELECT * FROM turns WHERE session_id = ?", (sid,)).fetchall()
        conn.close()
        assert len(turns) == 0

    def test_per_session_disable(self, ec_repo, isolated_global_config):
        cwd = str(ec_repo)
        sid = "per-session-disabled"
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})

        conn = get_db(cwd)
        conn.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"capture_disabled": True}), sid),
        )
        conn.commit()
        conn.close()

        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "do something"})

        conn = get_db(cwd)
        turns = conn.execute("SELECT * FROM turns WHERE session_id = ?", (sid,)).fetchall()
        conn.close()
        assert len(turns) == 0
