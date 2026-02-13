"""Shared fixtures for E2E tests."""

from __future__ import annotations

import json
import subprocess

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo in a temp directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


@pytest.fixture
def isolated_global_db(tmp_path, monkeypatch):
    """Isolate global DB to temp dir to avoid polluting user's real DB."""
    global_dir = tmp_path / "global_ec" / "db"
    global_dir.mkdir(parents=True)
    monkeypatch.setattr("entirecontext.db.connection._GLOBAL_DB_DIR", global_dir)
    monkeypatch.setattr("entirecontext.db.connection._GLOBAL_DB_PATH", global_dir / "ec.db")
    return global_dir


@pytest.fixture
def isolated_global_config(tmp_path, monkeypatch):
    """Isolate global config to temp dir."""
    config_path = tmp_path / "global_ec" / "config.toml"
    monkeypatch.setattr("entirecontext.core.config._GLOBAL_CONFIG_PATH", config_path)
    return config_path


@pytest.fixture
def ec_repo(git_repo, isolated_global_db):
    """Git repo with EntireContext initialized."""
    from entirecontext.core.project import init_project

    init_project(str(git_repo))
    return git_repo


@pytest.fixture
def ec_db(ec_repo):
    """DB connection to initialized EC repo."""
    from entirecontext.db import get_db

    conn = get_db(str(ec_repo))
    yield conn
    conn.close()


@pytest.fixture
def multi_ec_repos(tmp_path, isolated_global_db):
    """Create two git repos with EntireContext initialized and seeded data."""
    from entirecontext.core.project import init_project
    from entirecontext.db import get_db, check_and_migrate
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn

    repos = {}
    for name in ("frontend", "backend"):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
        )

        project = init_project(str(repo))
        conn = get_db(str(repo))
        check_and_migrate(conn)

        session = create_session(conn, project["id"], session_id=f"{name}-session-1")
        create_turn(
            conn,
            session["id"],
            turn_number=1,
            user_message=f"implement auth module for {name}",
            assistant_summary=f"Added authentication logic to {name} service",
            turn_status="completed",
        )
        create_turn(
            conn,
            session["id"],
            turn_number=2,
            user_message=f"add tests for {name} api",
            assistant_summary=f"Created test suite for {name} API endpoints",
            turn_status="completed",
        )
        conn.close()
        repos[name] = repo

    return repos


@pytest.fixture
def transcript_file(tmp_path):
    """Factory to create sample Claude Code transcript JSONL files."""

    def _make(messages, name="transcript.jsonl"):
        path = tmp_path / name
        lines = [json.dumps(m) for m in messages]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    return _make
