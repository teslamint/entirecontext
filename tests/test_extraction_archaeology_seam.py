"""Tests for run_extraction archaeology seam (injected bundles, session_id=None)."""

import json
from unittest.mock import patch
from entirecontext.core.decision_extraction import (
    SignalBundle,
    run_extraction,
)


def test_run_extraction_with_injected_bundles_persists_candidate_with_null_session(ec_db):
    """Confirms the persist path (not just plumbing) works with session_id=None.

    A "[]" mock response never reaches persist_candidate, so this test uses a
    real decision JSON payload to exercise the INSERT with a NULL session_id.
    """
    bundle = SignalBundle(
        source_type="archaeology",
        source_id="commit-abc123",
        session_id=None,
        checkpoint_id=None,
        assessment_id=None,
        text_blocks=["diff --git a/foo.py b/foo.py\nSwitched from X to Y because Z."],
        files=["foo.py"],
    )

    mock_response = json.dumps(
        [
            {
                "title": "Switch from X to Y",
                "rationale": "Z requires it",
                "scope": "foo.py",
                "rejected_alternatives": [{"alternative": "X", "reason": "insufficient"}],
            }
        ]
    )
    with patch(
        "entirecontext.core.decision_extraction.call_extraction_llm",
        return_value=mock_response,
    ):
        outcome = run_extraction(
            ec_db,
            session_id=None,
            repo_path="/tmp/fake",
            bundles=[bundle],
            min_confidence=0.0,
        )

    assert outcome.candidates_inserted == 1
    assert outcome.marked is False

    row = ec_db.execute(
        "SELECT session_id, source_type FROM decision_candidates WHERE source_id = ?",
        ("commit-abc123",),
    ).fetchone()
    assert row is not None
    assert row["session_id"] is None
    assert row["source_type"] == "archaeology"
