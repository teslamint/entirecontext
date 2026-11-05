"""Offline semantic benchmark against an isolated project database."""

import importlib.util
import json
import sqlite3
import struct
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/semantic_ranking_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("semantic_ranking_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEmbedder:
    def encode(self, text):
        if "랭킹" in text or "semantic target" in text:
            return struct.pack("2f", 1.0, 0.0)
        return struct.pack("2f", 0.0, 1.0)


def _seed(conn):
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, created_at, updated_at) VALUES ('semantic', 'semantic target', 'unrelated', '2025-01-01', '2020-01-01')"
    )
    # 25 newer filler decisions occupy the recent-decision padding, so the semantic signal must add the candidate.
    for i in range(25):
        conn.execute(
            "INSERT INTO decisions (id, title, rationale, created_at, updated_at) VALUES (?, 'filler entry', 'none', '2025-01-01', '2030-01-01')",
            (f"filler-{i}",),
        )
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, created_at) VALUES ('english', 'english matching keyword', 'unrelated', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, created_at) VALUES ('future', 'future choice', 'unrelated', '2027-01-01')"
    )
    for did, path in (("semantic", "src/semantic.py"), ("english", "src/english.py"), ("future", "src/future.py")):
        conn.execute("INSERT INTO decision_files (decision_id, file_path) VALUES (?, ?)", (did, path))
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) VALUES ('bench', (SELECT id FROM projects LIMIT 1), 'claude', '2025-01-01', '2025-01-01')"
    )
    for number, prompt, path in (
        (1, "랭킹 개선", "src/semantic.py"),
        (2, "english matching keyword in english.py", "src/english.py"),
        (3, "future choice", "src/future.py"),
    ):
        conn.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, files_touched, content_hash, timestamp) VALUES (?, 'bench', ?, ?, ?, 'hash', '2025-02-01')",
            (str(number), number, prompt, json.dumps([path])),
        )
    conn.commit()


def test_benchmark_reports_semantic_gain_on_fixture(ec_repo, ec_db, tmp_path):
    _seed(ec_db)
    output = tmp_path / "report.json"
    report = _module().benchmark(ec_repo, k=1, output=output, embedder_factory=lambda model: FakeEmbedder())
    assert output.exists()
    assert report["counts"]["items"] == 2
    assert report["subsets"]["hangul"]["baseline"]["hit_at_k"] == 0
    assert report["subsets"]["hangul"]["semantic"]["hit_at_k"] == 1
    assert report["subsets"]["all"]["semantic"]["hit_at_k"] == 1
    assert report["subsets"]["all"]["baseline"]["hit_at_k"] == 0.5


def test_benchmark_excludes_decisions_created_after_prompt(ec_repo, ec_db, tmp_path):
    _seed(ec_db)
    report = _module().benchmark(
        ec_repo, k=1, output=tmp_path / "report.json", embedder_factory=lambda model: FakeEmbedder()
    )
    assert report["counts"]["dropped_no_relevant"] == 1


def test_benchmark_reports_no_file_mention_subset(ec_repo, ec_db, tmp_path):
    _seed(ec_db)
    report = _module().benchmark(
        ec_repo, k=1, output=tmp_path / "report.json", embedder_factory=lambda model: FakeEmbedder()
    )
    assert report["subsets"]["no_file_mention"]["count"] == 1
    assert report["subsets"]["hangul_no_file_mention"]["count"] == 1


def test_benchmark_opens_database_read_only(ec_repo, ec_db):
    _seed(ec_db)
    with _module().open_database(ec_repo) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO decisions (id, title) VALUES ('write', 'forbidden')")


def test_benchmark_matches_absolute_turn_paths_to_relative_decision_files(ec_repo, ec_db, tmp_path):
    """Hooks record absolute paths (also from linked worktrees); decision links are repo-relative."""
    _seed(ec_db)
    ec_db.execute(
        "UPDATE turns SET files_touched = ? WHERE id = '1'",
        (json.dumps(["/home/user/other-worktree/src/semantic.py"]),),
    )
    ec_db.execute("UPDATE turns SET files_touched = ? WHERE id = '2'", (json.dumps([str(ec_repo / "src/english.py")]),))
    ec_db.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, files_touched, content_hash, timestamp) VALUES ('4', 'bench', 4, 'x', ?, 'hash', '2025-02-01')",
        (json.dumps(["/elsewhere/notsrc/semantic.pyc"]),),
    )
    ec_db.commit()
    report = _module().benchmark(
        ec_repo, k=1, output=tmp_path / "report.json", embedder_factory=lambda model: FakeEmbedder()
    )
    assert report["counts"]["items"] == 2
    assert report["counts"]["dropped_no_relevant"] == 2
