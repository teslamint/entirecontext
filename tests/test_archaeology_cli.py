"""CLI tests for ec archaeologize."""

import re
import sqlite3
import subprocess

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_help_output():
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    out = _strip_ansi(result.stdout)
    assert "--since" in out
    assert "--until" in out
    assert "--limit" in out
    assert "--dry-run" in out
    assert "--pr-bodies" in out
    assert "--batch-size" in out


def test_dry_run_on_fixture(git_repo):
    for i in range(3):
        (git_repo / f"file{i}.py").write_text(f"x = {i}")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: add file{i}"],
            cwd=git_repo,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                "PATH": subprocess.check_output(
                    ["bash", "-c", "echo $PATH"]
                ).decode().strip(),
            },
        )
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode == 0
    assert "commits" in result.stdout.lower() or "commits" in result.stderr.lower()


def test_dry_run_does_not_create_db(git_repo):
    """PR #190 finding #5: --dry-run must not trigger a DB migration —
    no `.entirecontext/db` schema should be created as a side effect of
    a read-only preview."""
    for i in range(2):
        (git_repo / f"file{i}.py").write_text(f"x = {i}")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: add file{i}"],
            cwd=git_repo,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
            },
        )
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode == 0

    db_path = git_repo / ".entirecontext" / "db" / "local.db"
    if db_path.exists():
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        assert tables == [], f"dry-run should not migrate the schema, found tables: {tables}"


def test_read_only_v16_dry_run_reports_separate_queues_without_migration(git_repo):
    for i in range(2):
        (git_repo / f"legacy{i}.py").write_text(f"x = {i}")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", f"feat: legacy {i}"], cwd=git_repo, check=True)
    shas = subprocess.check_output(
        ["git", "log", "-2", "--format=%H"], cwd=git_repo, text=True
    ).splitlines()

    db_path = git_repo / ".entirecontext" / "db" / "local.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE archaeology_processed ("
        "commit_sha TEXT PRIMARY KEY, candidate_count INTEGER NOT NULL DEFAULT 0, "
        "processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO archaeology_processed (commit_sha, candidate_count) VALUES (?, 2)",
        (shas[0],),
    )
    conn.commit()
    conn.close()

    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--dry-run", "--pr-bodies", "--limit", "2"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode == 0, result.stderr
    output = _strip_ansi(result.stdout + result.stderr)
    normalized = " ".join(output.split())
    assert "1 patch extractions pending" in normalized
    assert "1 PR enrichments pending" in normalized

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(archaeology_processed)")]
    rows = conn.execute("SELECT commit_sha, candidate_count FROM archaeology_processed").fetchall()
    conn.close()
    assert "pr_body_processed" not in columns
    assert rows == [(shas[0], 2)]


def test_limit_zero_is_rejected(git_repo):
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--limit", "0"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode != 0


def test_limit_negative_is_rejected(git_repo):
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--limit", "-1"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode != 0
