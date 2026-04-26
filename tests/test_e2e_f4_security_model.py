"""F4 security-model E2E coverage — closes the v0.4.0 retrospective gap.

``tests/test_e2e_feed_the_loop.py`` exercises F4's worker in-process by
patching ``entirecontext.core.async_worker.launch_worker``, which erases
the very subprocess boundary that F4's security model is built on.
This file adds four invariant assertions over the
hook → tmp → subprocess → worker chain:

1. ``test_hook_tmp_file_uses_o_excl_and_0600`` — hook creates the tmp
   file with ``O_EXCL`` and mode ``0o600``.
2. ``test_hook_rejects_symlink_at_tmp_path`` — pre-planted symlink at
   the tmp path is rejected by ``O_EXCL``; the symlink target is never
   written.
3. ``test_worker_subprocess_re_redacts_tampered_tmp`` — when the tmp
   file contains raw secrets (simulating tampering after the hook), a
   real ``ec decision surface-prompt`` subprocess re-redacts before
   anything reaches the fallback Markdown.
4. ``test_worker_subprocess_cleans_up_tmp_in_success_and_failure`` —
   the worker's ``try/finally`` removes the tmp on per-repo DB
   corruption, proving cleanup is from ``finally`` and not from a
   coincidental success-path branch.

Invariants 1, 4 are hook-side and run in-process with a mocked
``launch_worker``. Invariants 2, 3 spawn a real ``ec decision
surface-prompt`` subprocess. Tracks ec decision ``03ab3e25``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from entirecontext.core.decisions import create_decision, link_decision_to_file
from entirecontext.hooks.turn_capture import (
    _maybe_launch_prompt_surfacing_worker,
    _sanitize_id_for_path,
)


# Pytest is launched via ``uv run pytest``, so ``sys.executable`` is
# ``.venv/bin/python`` and the installed CLI entry point lives next to
# it. Avoids PATH/ambient-venv assumptions.
EC_BIN = str(Path(sys.executable).parent / "ec")


class TestF4SecurityModelE2E:
    """End-to-end coverage of F4's hook→tmp→subprocess→worker security chain."""

    def test_hook_tmp_file_uses_o_excl_and_0600(self, ec_repo, ec_db, monkeypatch):
        """Invariant 1: hook creates the tmp file with ``O_EXCL`` + ``0o600``."""
        captured_launches: list[dict] = []

        def _fake_launch(repo_path, cmd, pid_name="worker"):
            captured_launches.append({"cmd": list(cmd), "pid_name": pid_name})
            return 12345

        monkeypatch.setattr("entirecontext.core.async_worker.launch_worker", _fake_launch)

        session_id = "test-session-001"
        turn_id = "test-turn-001"
        prompt_text = "Adopt TOML for configuration storage given Python stdlib parsers"

        _maybe_launch_prompt_surfacing_worker(str(ec_repo), session_id, turn_id, prompt_text, config={})

        assert len(captured_launches) == 1
        cmd = captured_launches[0]["cmd"]
        tmp_path = Path(cmd[cmd.index("--prompt-file") + 1])

        assert tmp_path.exists()

        mode = tmp_path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"

        # No secret patterns in the prompt — content is unchanged after redaction.
        content = tmp_path.read_text(encoding="utf-8")
        assert content == prompt_text

    def test_hook_rejects_symlink_at_tmp_path(self, ec_repo, ec_db, monkeypatch, tmp_path):
        """Invariant 4: ``O_EXCL`` rejects a pre-planted symlink; target untouched."""
        victim_target = tmp_path / "victim.txt"
        victim_target.write_text("MUST_NOT_CHANGE", encoding="utf-8")

        session_id = "session-symlink-test"
        turn_id = "turn-symlink-test"
        safe_session = _sanitize_id_for_path(session_id)
        safe_turn = _sanitize_id_for_path(turn_id)
        tmp_dir = ec_repo / ".entirecontext" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        expected_tmp = tmp_dir / f"prompt-{safe_session}-{safe_turn}.txt"

        os.symlink(victim_target, expected_tmp)

        captured_launches: list[dict] = []

        def _fake_launch(repo_path, cmd, pid_name="worker"):
            captured_launches.append({"cmd": list(cmd), "pid_name": pid_name})
            return 12345

        monkeypatch.setattr("entirecontext.core.async_worker.launch_worker", _fake_launch)

        # Hook contract: never raises — exception is swallowed.
        _maybe_launch_prompt_surfacing_worker(str(ec_repo), session_id, turn_id, "Inject malicious data", config={})

        # ``os.open(O_CREAT | O_EXCL)`` raised before reaching ``launch_worker``.
        assert captured_launches == []

        # The symlink's target is untouched — ``O_EXCL`` did not follow the link.
        assert victim_target.read_text(encoding="utf-8") == "MUST_NOT_CHANGE"

    def test_worker_subprocess_re_redacts_tampered_tmp(self, ec_repo, ec_db, subprocess_isolated_home):
        """Invariant 3: worker re-redacts when tmp contains raw secrets.

        Bypasses the hook (which redacts in-memory before the disk write)
        to simulate a tampered tmp file, then verifies the worker's
        defense-in-depth ``filter_secrets`` + ``redact_for_query`` pass
        keeps the raw pattern out of the fallback Markdown.
        """
        decision = create_decision(
            ec_db,
            title="Adopt TOML for configuration storage",
            rationale="TOML parsers ship with Python 3.11+ stdlib which simplifies installation",
            scope="config",
        )
        link_decision_to_file(ec_db, decision["id"], "src/config.py")

        # Built programmatically — same approach as
        # ``test_e2e_feed_the_loop.py:311`` to avoid CodeQL's
        # clear-text-storage heuristic on identifiers like API_KEY.
        pattern_payload = "sk" + "-" + ("SEC" * 48)[:48]

        tmp_dir = ec_repo / ".entirecontext" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        session_id = "tamper-session"
        turn_id = "tamper-turn"
        tmp_file = tmp_dir / f"prompt-{session_id}-{turn_id}.txt"
        tmp_file.write_text(
            f"api_key={pattern_payload} TOML configuration storage Python stdlib decision",
            encoding="utf-8",
        )

        proc = subprocess.run(
            [
                EC_BIN,
                "decision",
                "surface-prompt",
                "--repo-path",
                str(ec_repo),
                "--session",
                session_id,
                "--turn",
                turn_id,
                "--prompt-file",
                str(tmp_file),
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            f"subprocess failed (rc={proc.returncode})\n"
            f"stdout: {proc.stdout.decode('utf-8', errors='replace')}\n"
            f"stderr: {proc.stderr.decode('utf-8', errors='replace')}"
        )

        # Worker's ``finally`` removed the tmp.
        assert not tmp_file.exists()

        markdown_path = ec_repo / ".entirecontext" / f"decisions-context-prompt-{session_id}-{turn_id}.md"
        assert markdown_path.exists(), f"expected Markdown at {markdown_path}"

        body = markdown_path.read_text(encoding="utf-8")
        assert pattern_payload not in body

    def test_worker_subprocess_cleans_up_tmp_in_success_and_failure(self, ec_repo, ec_db, subprocess_isolated_home):
        """Invariant 2: ``try/finally`` cleanup holds for both success and failure.

        Two sub-scenarios share one method:

        * **Success** — normal tmp + valid args. tmp is deleted; this path
          alone cannot prove the cleanup comes from ``finally`` (the
          success branch deletes too), so it serves as a sanity baseline.
        * **Failure** — corrupt the per-repo DB so the worker's first
          ``PRAGMA journal_mode=WAL`` raises ``sqlite3.DatabaseError``.
          The outer ``except Exception`` catches, then the ``finally``
          (``decision_prompt_surfacing.py:329-333``) deletes the tmp.
          Without this scenario, the cleanup invariant could regress to
          a success-only deletion and the tests would still pass.
        """
        tmp_dir = ec_repo / ".entirecontext" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        success_tmp = tmp_dir / "prompt-success-001.txt"
        success_tmp.write_text("Should we use Redis or memcached for caching?", encoding="utf-8")

        proc = subprocess.run(
            [
                EC_BIN,
                "decision",
                "surface-prompt",
                "--repo-path",
                str(ec_repo),
                "--session",
                "success-session",
                "--turn",
                "success-turn",
                "--prompt-file",
                str(success_tmp),
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"success scenario failed: {proc.stderr.decode('utf-8', errors='replace')}"
        assert not success_tmp.exists(), "success path: tmp should be deleted"
        # Inverse of the failure-scenario oracle — confirms ``worker:`` is
        # specific to the outer ``except Exception`` path (the only branch
        # whose warning starts with ``worker:``). If this leaks into the
        # success path, the failure-path assertion's specificity is
        # compromised.
        assert b"worker:" not in proc.stdout, (
            "success path: 'worker:' warning should be exclusive to the "
            f"failure scenario; stdout: {proc.stdout.decode('utf-8', errors='replace')!r}"
        )

        failure_tmp = tmp_dir / "prompt-failure-001.txt"
        failure_tmp.write_text("Some prompt content here", encoding="utf-8")

        # First 16 bytes lack the SQLite magic header — the worker's
        # first PRAGMA query raises ``sqlite3.DatabaseError`` before any
        # decision lookup runs.
        db_path = ec_repo / ".entirecontext" / "db" / "local.db"
        db_path.write_bytes(b"NOT A SQLITE DB" * 1000)

        proc = subprocess.run(
            [
                EC_BIN,
                "decision",
                "surface-prompt",
                "--repo-path",
                str(ec_repo),
                "--session",
                "failure-session",
                "--turn",
                "failure-turn",
                "--prompt-file",
                str(failure_tmp),
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        # CLI handler swallows worker errors via ``run_prompt_surface_worker``
        # collecting warnings and returning normally — exit code stays 0.
        assert proc.returncode == 0
        # Oracle that the worker actually entered the failure path. Without
        # it, ``returncode == 0`` and ``not failure_tmp.exists()`` could
        # both pass via the success branch (e.g., if a future SQLite/loader
        # change stops raising on this corruption shape, or if DB access
        # gets bypassed), and the cleanup-from-``finally`` invariant could
        # regress silently. ``warning: worker:...`` is what the CLI prints
        # only when ``run_prompt_surface_worker``'s outer ``except Exception``
        # catches — i.e., the same path that runs the ``finally`` block
        # which deletes the tmp.
        assert b"worker:" in proc.stdout, (
            "expected 'warning: worker:...' in stdout proving the DB error "
            "reached the worker's outer except (and thus the finally cleanup); "
            f"stdout: {proc.stdout.decode('utf-8', errors='replace')!r}\n"
            f"stderr: {proc.stderr.decode('utf-8', errors='replace')!r}"
        )
        assert not failure_tmp.exists(), (
            "failure path: tmp must be deleted by run_prompt_surface_worker's "
            "try/finally (decision_prompt_surfacing.py:329-333)"
        )
