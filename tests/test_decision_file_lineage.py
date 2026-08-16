"""Committed Git rename lineage and decision-file propagation tests."""

from __future__ import annotations

import subprocess
import sqlite3
from pathlib import Path

import pytest

from entirecontext.core.decision_extraction import get_file_outcome_stats
from entirecontext.core.decision_file_lineage import (
    RenameLogError,
    _parse_rename_log,
    sync_decision_file_lineage,
)
from entirecontext.core.decisions import (
    create_decision,
    get_decision,
    link_decision_to_file,
    rank_related_decisions,
    record_decision_outcome,
)
from entirecontext.db import get_db


_SHA_1 = "1" * 40
_SHA_2 = "2" * 40


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _commit_file(repo: Path, relative_path: str, content: str = "content\n") -> str:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", "--", relative_path)
    _git(repo, "commit", "-m", f"add {relative_path}")
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def _commit_rename(repo: Path, old_path: str, new_path: str) -> str:
    (repo / new_path).parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "--", old_path, new_path)
    _git(repo, "commit", "-m", f"rename {old_path} to {new_path}")
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def test_parse_rename_log_preserves_commit_and_exact_paths():
    raw = (
        f"\x1e{_SHA_1}\0\0\nR100\0src/old file.py\0src/middle file.py\0"
        f"\x1e{_SHA_2}\0\0\nR087\0src/middle file.py\0\nleading.py\0"
    ).encode()

    records = _parse_rename_log(raw)

    assert [(r.old_path, r.new_path, r.commit_sha) for r in records] == [
        ("src/old file.py", "src/middle file.py", _SHA_1),
        ("src/middle file.py", "\nleading.py", _SHA_2),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"\nR100\0old.py\0new.py\0",
        b"\x1enot-a-sha\0\0\nR100\0old.py\0new.py\0",
        f"\x1e{_SHA_1}\0\0\nR100\0old.py\0".encode(),
        f"\x1e{_SHA_1}\0\0\nM\0old.py\0".encode(),
        b"\x1e" + _SHA_1.encode() + b"\0\0\nR100\0old.py\0bad-\xff.py\0",
        f"\x1e{_SHA_1}\0\0\nR100\0old.py\0partial-new.py".encode(),
    ],
)
def test_parse_rename_log_rejects_malformed_or_unpersistable_records(raw):
    with pytest.raises(RenameLogError):
        _parse_rename_log(raw)


def test_sync_preserves_ranking_outcomes_and_all_transitive_paths(ec_repo, ec_db):
    _commit_file(ec_repo, "src/old.py")
    decision = create_decision(ec_db, title="Keep rename history")
    link_decision_to_file(ec_db, decision["id"], "src/old.py")
    record_decision_outcome(ec_db, decision["id"], "accepted")

    _commit_rename(ec_repo, "src/old.py", "src/middle.py")
    final_sha = _commit_rename(ec_repo, "src/middle.py", "src/new.py")

    result = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert result.head_commit == final_sha
    assert result.full_scan is True
    assert result.renames_recorded == 2
    assert result.links_added == 2

    reopened = get_db(str(ec_repo))
    try:
        stored = get_decision(reopened, decision["id"])
        assert stored is not None
        assert set(stored["files"]) == {"src/old.py", "src/middle.py", "src/new.py"}

        ranked = rank_related_decisions(reopened, file_paths=["src/new.py"])
        item = next(row for row in ranked if row["id"] == decision["id"])
        assert item["score_breakdown"]["file_exact"] == 3.0

        old_stats = get_file_outcome_stats(reopened, ["src/old.py"], lookback_days=60)
        new_stats = get_file_outcome_stats(reopened, ["src/new.py"], lookback_days=60)
        assert old_stats == new_stats
        assert new_stats["accepted"] == 1
        assert new_stats["total"] == 1
    finally:
        reopened.close()


def test_sync_records_rename_introduced_by_merge_resolution(ec_repo, ec_db):
    initial_sha = _commit_file(ec_repo, "src/old.py")
    decision = create_decision(ec_db, title="Merge-resolution rename")
    link_decision_to_file(ec_db, decision["id"], "src/old.py")
    initial = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert initial.head_commit == initial_sha

    base_branch = _git(ec_repo, "branch", "--show-current").stdout.decode().strip()
    _git(ec_repo, "checkout", "-b", "rename-side")
    _commit_file(ec_repo, "branch-only.py", "branch content\n")
    _git(ec_repo, "checkout", base_branch)
    _git(ec_repo, "merge", "--no-ff", "--no-commit", "rename-side")
    _git(ec_repo, "mv", "--", "src/old.py", "src/merged.py")
    _git(ec_repo, "commit", "-m", "rename while resolving merge")
    merge_sha = _git(ec_repo, "rev-parse", "HEAD").stdout.decode().strip()

    result = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert result.head_commit == merge_sha
    assert result.renames_recorded == 1
    assert result.links_added == 1
    stored = get_decision(ec_db, decision["id"])
    assert stored is not None
    assert set(stored["files"]) == {"src/old.py", "src/merged.py"}
    lineage = ec_db.execute("SELECT old_path, new_path, commit_sha FROM decision_file_lineage").fetchall()
    assert [tuple(row) for row in lineage] == [
        ("src/old.py", "src/merged.py", merge_sha),
    ]


def test_sync_normalizes_literal_backslashes_consistently(ec_repo, ec_db):
    _commit_file(ec_repo, r"src\old.py")
    decision = create_decision(ec_db, title="Backslash-path rename")
    link_decision_to_file(ec_db, decision["id"], r"src\old.py")
    _commit_rename(ec_repo, r"src\old.py", r"src\new.py")

    result = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert result.links_added == 1
    stored = get_decision(ec_db, decision["id"])
    assert stored is not None
    assert set(stored["files"]) == {r"src\old.py", r"src\new.py"}


def test_sync_terminates_cyclic_lineage_with_set_semantics(ec_repo, ec_db):
    _commit_file(ec_repo, "src/a.py")
    decision = create_decision(ec_db, title="Cyclic rename evidence")
    link_decision_to_file(ec_db, decision["id"], "src/a.py")
    ec_db.executemany(
        """INSERT INTO decision_file_lineage
        (old_path, new_path, commit_sha) VALUES (?, ?, ?)""",
        [
            ("src/a.py", "src/b.py", _SHA_1),
            ("src/b.py", "src/a.py", _SHA_2),
        ],
    )
    ec_db.commit()

    result = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert result.links_added == 1
    stored = get_decision(ec_db, decision["id"])
    assert stored is not None
    assert set(stored["files"]) == {"src/a.py", "src/b.py"}
    assert sync_decision_file_lineage(ec_db, str(ec_repo)).links_added == 0


def test_sync_uses_incremental_range_after_initial_watermark(ec_repo, ec_db):
    initial_sha = _commit_file(ec_repo, "src/old.py")
    decision = create_decision(ec_db, title="Incremental rename")
    link_decision_to_file(ec_db, decision["id"], "src/old.py")

    initial = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert initial.full_scan is True
    assert initial.head_commit == initial_sha
    assert initial.renames_recorded == 0

    renamed_sha = _commit_rename(ec_repo, "src/old.py", "src/new.py")
    incremental = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert incremental.full_scan is False
    assert incremental.scanned_from == initial_sha
    assert incremental.head_commit == renamed_sha
    assert incremental.renames_recorded == 1
    assert incremental.links_added == 1


def test_sync_same_head_replays_lineage_for_later_decision(ec_repo, ec_db):
    _commit_file(ec_repo, "src/old.py")
    _commit_rename(ec_repo, "src/old.py", "src/middle.py")
    _commit_rename(ec_repo, "src/middle.py", "src/new.py")
    first = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert first.renames_recorded == 2
    assert first.links_added == 0

    decision = create_decision(ec_db, title="Linked after history scan")
    link_decision_to_file(ec_db, decision["id"], "./src/old.py")

    replay = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert replay.full_scan is False
    assert replay.renames_recorded == 0
    assert replay.links_added == 2

    again = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert again.renames_recorded == 0
    assert again.links_added == 0
    stored = get_decision(ec_db, decision["id"])
    assert stored is not None
    assert set(stored["files"]) == {"./src/old.py", "src/middle.py", "src/new.py"}


def test_sync_full_rescans_when_watermark_is_not_an_ancestor(ec_repo, ec_db):
    _commit_file(ec_repo, "src/old.py")
    sync_decision_file_lineage(ec_db, str(ec_repo))
    final_sha = _commit_rename(ec_repo, "src/old.py", "src/new.py")
    ec_db.execute(
        "UPDATE decision_file_lineage_state SET last_scanned_commit = ? WHERE id = 1",
        ("f" * 40,),
    )
    ec_db.commit()

    result = sync_decision_file_lineage(ec_db, str(ec_repo))

    assert result.full_scan is True
    assert result.scanned_from is None
    assert result.renames_recorded == 1
    row = ec_db.execute("SELECT last_scanned_commit FROM decision_file_lineage_state WHERE id = 1").fetchone()
    assert row["last_scanned_commit"] == final_sha


def test_db_error_rolls_back_lineage_links_and_watermark(ec_repo, ec_db, monkeypatch):
    initial_sha = _commit_file(ec_repo, "src/old.py")
    decision = create_decision(ec_db, title="Transactional rename")
    link_decision_to_file(ec_db, decision["id"], "src/old.py")
    sync_decision_file_lineage(ec_db, str(ec_repo))
    _commit_rename(ec_repo, "src/old.py", "src/new.py")

    def fail_propagation(_conn):
        raise sqlite3.OperationalError("injected propagation failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            "entirecontext.core.decision_file_lineage._propagate_destination_links",
            fail_propagation,
        )
        with pytest.raises(sqlite3.OperationalError, match="injected propagation failure"):
            sync_decision_file_lineage(ec_db, str(ec_repo))

    assert ec_db.execute("SELECT COUNT(*) FROM decision_file_lineage").fetchone()[0] == 0
    stored = get_decision(ec_db, decision["id"])
    assert stored is not None
    assert stored["files"] == ["src/old.py"]
    row = ec_db.execute("SELECT last_scanned_commit FROM decision_file_lineage_state WHERE id = 1").fetchone()
    assert row["last_scanned_commit"] == initial_sha

    retry = sync_decision_file_lineage(ec_db, str(ec_repo))
    assert retry.renames_recorded == 1
    assert retry.links_added == 1
    repaired = get_decision(ec_db, decision["id"])
    assert repaired is not None
    assert set(repaired["files"]) == {"src/old.py", "src/new.py"}


def test_sync_rejects_nonpositive_time_budget(ec_repo, ec_db):
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        sync_decision_file_lineage(ec_db, str(ec_repo), timeout_seconds=0)
