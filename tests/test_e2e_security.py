"""E2E tests for security filtering."""

from __future__ import annotations

from entirecontext.core.security import filter_secrets, scan_for_secrets
from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_start
from entirecontext.hooks.turn_capture import on_stop, on_user_prompt
from entirecontext.sync.security import filter_export_data


class TestFilterSecrets:
    def test_api_key(self):
        text = "Config: API_KEY=sk-abc123xyz"
        filtered = filter_secrets(text)
        assert "sk-abc123xyz" not in filtered
        assert "[REDACTED]" in filtered

    def test_bearer_token(self):
        text = "Header: Bearer eyJhbGciOiJIUzI1NiJ9.test"
        filtered = filter_secrets(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in filtered
        assert "[REDACTED]" in filtered

    def test_github_pat(self):
        pat = "ghp_" + "a" * 36
        text = f"Token: {pat}"
        filtered = filter_secrets(text)
        assert pat not in filtered
        assert "[REDACTED]" in filtered

    def test_no_secrets_unchanged(self):
        text = "This is normal text with no secrets"
        assert filter_secrets(text) == text

    def test_scan_finds_secrets(self):
        text = "API_KEY=secret123 and password=abc"
        findings = scan_for_secrets(text)
        assert len(findings) >= 1


class TestExportFiltering:
    def test_filter_export_data(self):
        text = "password=my-secret-pw rest of line"
        filtered = filter_export_data(text)
        assert "my-secret-pw" not in filtered
        assert "[REDACTED]" in filtered

    def test_disabled(self):
        text = "password=my-secret-pw rest of line"
        assert filter_export_data(text, enabled=False) == text


class TestSecurityWithCapturedData:
    def test_db_stores_unredacted(self, ec_repo, transcript_file):
        cwd = str(ec_repo)
        sid = "security-session"
        secret_prompt = "Set API_KEY=sk-secret123abc for the auth service"

        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": secret_prompt})
        t1 = transcript_file(
            [
                {"role": "user", "content": secret_prompt},
                {"role": "assistant", "content": "Configured the API key"},
            ]
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})

        conn = get_db(cwd)
        row = conn.execute("SELECT user_message FROM turns WHERE session_id = ?", (sid,)).fetchone()
        conn.close()

        assert row["user_message"] == secret_prompt

        filtered = filter_secrets(secret_prompt)
        assert "[REDACTED]" in filtered
        assert "sk-secret123abc" not in filtered
