from __future__ import annotations

from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import (
    detect_current_context,
    record_context_application,
    record_retrieval_event,
    record_retrieval_selection,
)
from entirecontext.core.turn import create_turn


class TestTelemetryHelpers:
    def test_detect_current_context(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-session")
        create_turn(ec_db, session["id"], 1, user_message="look up auth", assistant_summary="found auth history")

        session_id, turn_id = detect_current_context(ec_db)
        assert session_id == session["id"]
        assert turn_id is not None

    def test_record_selection_and_apply_from_selection(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-selection")
        turn = create_turn(ec_db, session["id"], 1, user_message="search auth", assistant_summary="returned results")

        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="regex",
            target="turn",
            query="auth",
            result_count=2,
            latency_ms=7,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "turn", "t-source", rank=1)
        application = record_context_application(
            ec_db,
            application_type="reference",
            selection_id=selection["id"],
        )

        row = ec_db.execute("SELECT * FROM context_applications WHERE id = ?", (application["id"],)).fetchone()
        assert row["retrieval_selection_id"] == selection["id"]
        assert row["source_type"] == "turn"
        assert row["source_id"] == "t-source"

    def test_direct_application_requires_source(self, ec_db):
        try:
            record_context_application(ec_db, application_type="reference")
        except ValueError as exc:
            assert "source_type and source_id are required" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_invalid_application_type_rejected(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-invalid")
        create_turn(ec_db, session["id"], 1, user_message="search auth", assistant_summary="returned results")

        try:
            record_context_application(
                ec_db,
                application_type="invalid",
                source_type="assessment",
                source_id="asmt-1",
            )
        except ValueError as exc:
            assert "Invalid application_type" in str(exc)
        else:
            raise AssertionError("expected ValueError")
