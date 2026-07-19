"""CLI tests for `ec decision candidates confirm-batch`."""

from __future__ import annotations

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.decision_candidates import get_candidate
from entirecontext.core.decision_extraction import (
    CandidateDraft,
    DedupResult,
    compute_dedup_key,
    persist_candidate,
    score_confidence,
)
from entirecontext.db import get_db

runner = CliRunner()


def _seed_candidate(ec_db, *, source_type, source_id, confidence=0.9, title=None):
    draft = CandidateDraft(
        title=title or f"{source_type} decision {source_id}",
        rationale="a sufficiently long rationale to pass the heuristic",
        scope="test",
        rejected_alternatives=["alt"],
        supporting_evidence=[],
        source_type=source_type,
        source_id=source_id,
        session_id=None,
        checkpoint_id=None,
        assessment_id=None,
        files=["src/a.py"],
    )
    dr = DedupResult(dedup_key=compute_dedup_key(draft.title))
    _, breakdown = score_confidence(draft, dr)
    result = persist_candidate(ec_db, draft, confidence, breakdown, dr)
    assert result.inserted, result.reason
    return result.candidate_id


def _hex_sha(i):
    return f"{i:040x}"


class TestConfirmBatchCLI:
    def test_happy_path_confirms_and_prints_count(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        ids = [
            _seed_candidate(conn, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)
            for i in (1, 2, 3)
        ]
        conn.close()

        result = runner.invoke(app, ["decision", "candidates", "confirm-batch", "--min-confidence", "0.5"])

        assert result.exit_code == 0
        assert "Confirmed" in result.stdout
        assert "3" in result.stdout

        conn = get_db(str(ec_repo))
        try:
            for cid in ids:
                row = get_candidate(conn, cid)
                assert row["review_status"] == "confirmed"
        finally:
            conn.close()

    def test_dry_run_prints_distribution_and_does_not_mutate(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        ids = [
            _seed_candidate(conn, source_type="archaeology", source_id=_hex_sha(i), confidence=c)
            for i, c in enumerate([0.15, 0.55, 0.95], start=1)
        ]
        conn.close()

        result = runner.invoke(
            app, ["decision", "candidates", "confirm-batch", "--min-confidence", "0.5", "--dry-run"]
        )

        assert result.exit_code == 0
        assert "Total pending: 3" in result.stdout
        assert "eligible" in result.stdout.lower()

        conn = get_db(str(ec_repo))
        try:
            for cid in ids:
                row = get_candidate(conn, cid)
                assert row["review_status"] == "pending"
        finally:
            conn.close()

    def test_no_matching_candidates_prints_empty_state(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)

        result = runner.invoke(app, ["decision", "candidates", "confirm-batch", "--min-confidence", "0.5"])

        assert result.exit_code == 0
        assert "No pending candidates match." in result.stdout

    def test_missing_min_confidence_is_usage_error(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)

        result = runner.invoke(app, ["decision", "candidates", "confirm-batch"])

        assert result.exit_code == 2
