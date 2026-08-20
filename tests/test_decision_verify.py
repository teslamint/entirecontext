"""Tests for core.decision_verify — doc UUID scanning, verification, and promotion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from entirecontext.core.decision_verify import (
    DocRef,
    open_source_db_readonly,
    promote_decisions,
    scan_doc_decision_refs,
    verify_decisions,
)


SAMPLE_UUID_A = "aaaaaaaa-1111-2222-3333-444444444444"
SAMPLE_UUID_B = "bbbbbbbb-1111-2222-3333-444444444444"
SAMPLE_UUID_C = "cccccccc-1111-2222-3333-444444444444"


def _write_doc(repo: Path, rel_path: str, content: str) -> None:
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _insert_decision(conn: sqlite3.Connection, decision_id: str, title: str = "test") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO decisions (id, title, staleness_status, created_at, updated_at) "
        "VALUES (?, ?, 'fresh', datetime('now'), datetime('now'))",
        (decision_id, title),
    )


class TestScanDocDecisionRefs:
    def test_finds_uuids_in_adr(self, ec_repo):
        _write_doc(ec_repo, "docs/adr/0001-test.md", f"**EC Decision:** `{SAMPLE_UUID_A}`\n")
        refs = scan_doc_decision_refs(str(ec_repo))
        assert len(refs) == 1
        assert refs[0].uuid == SAMPLE_UUID_A
        assert refs[0].file == "docs/adr/0001-test.md"
        assert refs[0].line == 1

    def test_finds_uuids_in_roadmap(self, ec_repo):
        _write_doc(ec_repo, "ROADMAP.md", f"line1\nsome ref {SAMPLE_UUID_A}\nline3\n")
        refs = scan_doc_decision_refs(str(ec_repo))
        assert len(refs) == 1
        assert refs[0].line == 2

    def test_multiple_uuids_same_file(self, ec_repo):
        content = f"ref1: {SAMPLE_UUID_A}\nref2: {SAMPLE_UUID_B}\n"
        _write_doc(ec_repo, "docs/adr/0002-multi.md", content)
        refs = scan_doc_decision_refs(str(ec_repo))
        uuids = {r.uuid for r in refs}
        assert uuids == {SAMPLE_UUID_A, SAMPLE_UUID_B}

    def test_case_insensitive(self, ec_repo):
        upper = SAMPLE_UUID_A.upper()
        _write_doc(ec_repo, "docs/adr/0003-upper.md", f"ref: {upper}\n")
        refs = scan_doc_decision_refs(str(ec_repo))
        assert refs[0].uuid == SAMPLE_UUID_A  # lowercased

    def test_no_match_in_missing_dirs(self, ec_repo):
        refs = scan_doc_decision_refs(str(ec_repo))
        assert refs == []

    def test_custom_dirs(self, ec_repo):
        _write_doc(ec_repo, "custom/doc.md", f"ref: {SAMPLE_UUID_A}\n")
        refs = scan_doc_decision_refs(str(ec_repo), dirs=("custom",))
        assert len(refs) == 1

    def test_absolute_dir_rejected(self, ec_repo):
        with pytest.raises(ValueError, match="relative to repo root"):
            scan_doc_decision_refs(str(ec_repo), dirs=("/srv/docs",))

    def test_absolute_file_rejected(self, ec_repo):
        with pytest.raises(ValueError, match="relative to repo root"):
            scan_doc_decision_refs(str(ec_repo), files=("/etc/passwd",))


class TestVerifyDecisions:
    def test_all_found(self, ec_db):
        _insert_decision(ec_db, SAMPLE_UUID_A)
        refs = [DocRef(file="test.md", line=1, uuid=SAMPLE_UUID_A)]
        result = verify_decisions(ec_db, refs)
        assert len(result.found) == 1
        assert len(result.missing) == 0

    def test_missing(self, ec_db):
        refs = [DocRef(file="test.md", line=1, uuid=SAMPLE_UUID_A)]
        result = verify_decisions(ec_db, refs)
        assert len(result.found) == 0
        assert len(result.missing) == 1
        assert result.missing[0].uuid == SAMPLE_UUID_A

    def test_mixed(self, ec_db):
        _insert_decision(ec_db, SAMPLE_UUID_A)
        refs = [
            DocRef(file="a.md", line=1, uuid=SAMPLE_UUID_A),
            DocRef(file="b.md", line=2, uuid=SAMPLE_UUID_B),
        ]
        result = verify_decisions(ec_db, refs)
        assert len(result.found) == 1
        assert len(result.missing) == 1

    def test_empty_refs(self, ec_db):
        result = verify_decisions(ec_db, [])
        assert result.found == []
        assert result.missing == []


class TestOpenSourceDbReadonly:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            open_source_db_readonly(tmp_path / "nonexistent.db")

    def test_opens_readonly(self, ec_repo):
        db_path = ec_repo / ".entirecontext" / "db" / "local.db"
        conn = open_source_db_readonly(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE test_rw (id TEXT)")
        finally:
            conn.close()

    def test_hash_in_path(self, ec_repo, tmp_path):
        db_path = ec_repo / ".entirecontext" / "db" / "local.db"
        hash_dir = tmp_path / "repo#2"
        hash_dir.mkdir()
        dest = hash_dir / "local.db"
        import shutil

        shutil.copy2(db_path, dest)
        conn = open_source_db_readonly(dest)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE test_rw (id TEXT)")
        finally:
            conn.close()

    def test_corrupt_file(self, tmp_path):
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_text("not a database")
        conn = open_source_db_readonly(corrupt)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute("SELECT 1 FROM sqlite_master")
        finally:
            conn.close()


class TestPromoteDecisions:
    @pytest.fixture
    def two_dbs(self, ec_repo, tmp_path):
        """Source and target DB connections with matching schemas."""
        from entirecontext.core.project import init_project
        from entirecontext.db import check_and_migrate, get_db

        source_repo = tmp_path / "source_repo"
        source_repo.mkdir()
        import subprocess

        subprocess.run(["git", "init", str(source_repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "user.email", "t@t.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "user.name", "T"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "commit.gpgsign", "false"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source_repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
        )
        init_project(str(source_repo))

        source_conn = get_db(str(source_repo))
        check_and_migrate(source_conn)

        target_conn = get_db(str(ec_repo))
        check_and_migrate(target_conn)

        yield source_conn, target_conn
        source_conn.close()
        target_conn.close()

    def test_promote_basic(self, two_dbs):
        source, target = two_dbs
        _insert_decision(source, SAMPLE_UUID_A, "Decision A")
        result = promote_decisions(source, target, [SAMPLE_UUID_A])
        assert result.promoted == [SAMPLE_UUID_A]
        row = target.execute("SELECT title FROM decisions WHERE id = ?", (SAMPLE_UUID_A,)).fetchone()
        assert row["title"] == "Decision A"

    def test_promote_idempotent(self, two_dbs):
        source, target = two_dbs
        _insert_decision(source, SAMPLE_UUID_A, "Decision A")
        promote_decisions(source, target, [SAMPLE_UUID_A])
        result = promote_decisions(source, target, [SAMPLE_UUID_A])
        assert result.already_present == [SAMPLE_UUID_A]
        assert result.promoted == []

    def test_promote_missing_in_source(self, two_dbs):
        source, target = two_dbs
        result = promote_decisions(source, target, [SAMPLE_UUID_A])
        assert result.missing_in_source == [SAMPLE_UUID_A]

    def test_promote_with_files(self, two_dbs):
        source, target = two_dbs
        _insert_decision(source, SAMPLE_UUID_A)
        source.execute(
            "INSERT INTO decision_files (decision_id, file_path) VALUES (?, ?)",
            (SAMPLE_UUID_A, "src/foo.py"),
        )
        result = promote_decisions(source, target, [SAMPLE_UUID_A])
        assert result.promoted == [SAMPLE_UUID_A]
        row = target.execute(
            "SELECT file_path FROM decision_files WHERE decision_id = ?",
            (SAMPLE_UUID_A,),
        ).fetchone()
        assert row["file_path"] == "src/foo.py"

    def test_promote_superseded_by_in_batch(self, two_dbs):
        source, target = two_dbs
        _insert_decision(source, SAMPLE_UUID_A, "Old")
        _insert_decision(source, SAMPLE_UUID_B, "New")
        source.execute(
            "UPDATE decisions SET superseded_by_id = ?, staleness_status = 'superseded' WHERE id = ?",
            (SAMPLE_UUID_B, SAMPLE_UUID_A),
        )
        result = promote_decisions(source, target, [SAMPLE_UUID_A, SAMPLE_UUID_B])
        assert set(result.promoted) == {SAMPLE_UUID_A, SAMPLE_UUID_B}
        row = target.execute("SELECT superseded_by_id FROM decisions WHERE id = ?", (SAMPLE_UUID_A,)).fetchone()
        assert row["superseded_by_id"] == SAMPLE_UUID_B

    def test_promote_superseded_by_not_in_batch(self, two_dbs):
        source, target = two_dbs
        _insert_decision(source, SAMPLE_UUID_A, "Old")
        _insert_decision(source, SAMPLE_UUID_B, "New")
        source.execute(
            "UPDATE decisions SET superseded_by_id = ? WHERE id = ?",
            (SAMPLE_UUID_B, SAMPLE_UUID_A),
        )
        result = promote_decisions(source, target, [SAMPLE_UUID_A])
        assert result.promoted == [SAMPLE_UUID_A]
        row = target.execute("SELECT superseded_by_id FROM decisions WHERE id = ?", (SAMPLE_UUID_A,)).fetchone()
        assert row["superseded_by_id"] is None  # successor not in target

    def test_schema_version_mismatch(self, two_dbs):
        source, target = two_dbs
        with pytest.raises(ValueError, match="Schema version mismatch"):
            promote_decisions(source, target, [SAMPLE_UUID_A], target_schema_version=999)


class TestVerifyDocsCLI:
    def test_all_resolved(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app as ec_app

        _insert_decision(ec_db, SAMPLE_UUID_A)
        _write_doc(ec_repo, "docs/adr/0001.md", f"EC Decision: `{SAMPLE_UUID_A}`\n")
        monkeypatch.chdir(ec_repo)

        runner = CliRunner()
        result = runner.invoke(ec_app, ["decision", "verify-docs"])
        assert result.exit_code == 0
        assert "All decision references verified" in result.output

    def test_missing_exits_nonzero(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app as ec_app

        _write_doc(ec_repo, "docs/adr/0001.md", f"EC Decision: `{SAMPLE_UUID_A}`\n")
        monkeypatch.chdir(ec_repo)

        runner = CliRunner()
        result = runner.invoke(ec_app, ["decision", "verify-docs"])
        assert result.exit_code != 0
        assert "Missing" in result.output

    def test_no_uuids(self, ec_repo, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app as ec_app

        monkeypatch.chdir(ec_repo)

        runner = CliRunner()
        result = runner.invoke(ec_app, ["decision", "verify-docs"])
        assert result.exit_code == 0
        assert "No UUIDs found" in result.output

    def test_promote_from_cli(self, ec_repo, ec_db, tmp_path, monkeypatch, isolated_global_db):
        import subprocess

        from typer.testing import CliRunner

        from entirecontext.cli import app as ec_app
        from entirecontext.core.project import init_project
        from entirecontext.db import check_and_migrate, get_db

        source_repo = tmp_path / "src_repo"
        source_repo.mkdir()
        subprocess.run(["git", "init", str(source_repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "user.email", "t@t.com"], check=True, capture_output=True
        )
        subprocess.run(["git", "-C", str(source_repo), "config", "user.name", "T"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "commit.gpgsign", "false"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(source_repo), "commit", "--allow-empty", "-m", "init"], check=True, capture_output=True
        )
        init_project(str(source_repo))
        src_conn = get_db(str(source_repo))
        check_and_migrate(src_conn)
        _insert_decision(src_conn, SAMPLE_UUID_A, "From worktree")
        src_conn.close()

        _write_doc(ec_repo, "docs/adr/0001.md", f"EC Decision: `{SAMPLE_UUID_A}`\n")
        monkeypatch.chdir(ec_repo)

        src_db_path = str(source_repo / ".entirecontext" / "db" / "local.db")
        runner = CliRunner()
        result = runner.invoke(ec_app, ["decision", "verify-docs", "--promote-from", src_db_path])
        assert result.exit_code == 0
        assert "Promoted 1" in result.output
        assert "verified after promotion" in result.output
