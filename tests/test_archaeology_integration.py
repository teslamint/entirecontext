"""Integration test: ec archaeologize end-to-end pipeline."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from entirecontext.core.archaeology import archaeologize


@pytest.fixture
def arch_repo(ec_repo):
    """ec_repo with 5 additional commits, each adding a module."""
    for i in range(5):
        f = ec_repo / f"mod{i}.py"
        f.write_text(f"def func_{i}():\n    return {i}\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", f"feat: add module {i} with func_{i}"],
            check=True,
            capture_output=True,
        )
    return ec_repo


def test_full_pipeline(arch_repo, ec_db):
    mock_response = (
        '[{"title": "Use function pattern for module", '
        '"rationale": "Simple function pattern chosen over class-based", '
        '"scope": "module design", '
        '"rejected_alternatives": [{"alternative": "class-based", "reason": "unnecessary complexity"}]}]'
    )

    with patch(
        "entirecontext.core.decision_extraction.call_extraction_llm",
        return_value=mock_response,
    ):
        result = archaeologize(
            ec_db,
            str(arch_repo),
            limit=5,
            batch_size=2,
        )

    assert result.commits_scanned == 5
    assert result.commits_processed == 5
    assert result.commits_skipped == 0
    assert result.candidates_generated >= 1

    rows = ec_db.execute("SELECT source_type, session_id FROM decision_candidates").fetchall()
    assert rows
    for row in rows:
        assert row["source_type"] == "archaeology"
        assert row["session_id"] is None


def test_rerun_skips_all(arch_repo, ec_db):
    mock_response = "[]"
    with patch(
        "entirecontext.core.decision_extraction.call_extraction_llm",
        return_value=mock_response,
    ):
        archaeologize(ec_db, str(arch_repo), limit=5)
        result2 = archaeologize(ec_db, str(arch_repo), limit=5)

    assert result2.commits_skipped == 5
    assert result2.commits_processed == 0


def test_dry_run_no_writes(arch_repo, ec_db):
    result = archaeologize(ec_db, str(arch_repo), limit=5, dry_run=True)
    assert result.commits_scanned == 5
    assert result.commits_processed == 0

    processed = ec_db.execute("SELECT COUNT(*) FROM archaeology_processed").fetchone()[0]
    assert processed == 0

    candidates = ec_db.execute("SELECT COUNT(*) FROM decision_candidates").fetchone()[0]
    assert candidates == 0


def test_source_type_archaeology_on_candidates(arch_repo, ec_db):
    mock_response = (
        '[{"title": "Test decision", "rationale": "Test", "scope": "test", '
        '"rejected_alternatives": []}]'
    )
    with patch(
        "entirecontext.core.decision_extraction.call_extraction_llm",
        return_value=mock_response,
    ):
        archaeologize(ec_db, str(arch_repo), limit=1)

    row = ec_db.execute("SELECT source_type FROM decision_candidates LIMIT 1").fetchone()
    assert row is not None
    assert row["source_type"] == "archaeology"
