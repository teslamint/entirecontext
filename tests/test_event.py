"""Tests for event core business logic."""

from __future__ import annotations

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.core.event import (
    create_event,
    get_event,
    list_events,
    update_event,
    link_event_session,
    link_event_checkpoint,
    get_event_sessions,
    get_event_checkpoints,
)
from entirecontext.core.session import create_session


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test-project', '/tmp/test')")
    conn.commit()
    yield conn
    conn.close()


class TestCreateEvent:
    def test_create_default(self, db):
        result = create_event(db, "Fix login bug")
        assert result["title"] == "Fix login bug"
        assert result["event_type"] == "task"
        assert result["status"] == "active"
        assert result["id"] is not None

    def test_create_with_type(self, db):
        result = create_event(db, "Sprint 5", event_type="temporal")
        assert result["event_type"] == "temporal"

    def test_create_milestone(self, db):
        result = create_event(db, "v1.0 release", event_type="milestone", description="First stable release")
        assert result["event_type"] == "milestone"
        event = get_event(db, result["id"])
        assert event["description"] == "First stable release"

    def test_create_invalid_type(self, db):
        with pytest.raises(ValueError, match="Invalid event_type"):
            create_event(db, "Bad", event_type="invalid")


class TestGetEvent:
    def test_get_existing(self, db):
        created = create_event(db, "Test event")
        fetched = get_event(db, created["id"])
        assert fetched is not None
        assert fetched["title"] == "Test event"

    def test_get_nonexistent(self, db):
        assert get_event(db, "nonexistent-id") is None


class TestListEvents:
    def test_list_all(self, db):
        create_event(db, "Event 1")
        create_event(db, "Event 2")
        events = list_events(db)
        assert len(events) == 2

    def test_list_with_status_filter(self, db):
        e1 = create_event(db, "Active event")
        create_event(db, "Another active")
        update_event(db, e1["id"], status="frozen")
        active = list_events(db, status="active")
        assert len(active) == 1
        frozen = list_events(db, status="frozen")
        assert len(frozen) == 1

    def test_list_with_type_filter(self, db):
        create_event(db, "Task event", event_type="task")
        create_event(db, "Milestone", event_type="milestone")
        tasks = list_events(db, event_type="task")
        assert len(tasks) == 1
        assert tasks[0]["event_type"] == "task"

    def test_list_limit(self, db):
        for i in range(5):
            create_event(db, f"Event {i}")
        events = list_events(db, limit=3)
        assert len(events) == 3

    def test_list_empty(self, db):
        events = list_events(db)
        assert events == []


class TestUpdateEvent:
    def test_update_title(self, db):
        e = create_event(db, "Old title")
        update_event(db, e["id"], title="New title")
        updated = get_event(db, e["id"])
        assert updated["title"] == "New title"

    def test_status_active_to_frozen(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"], status="frozen")
        assert get_event(db, e["id"])["status"] == "frozen"

    def test_status_active_to_archived(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"], status="archived")
        assert get_event(db, e["id"])["status"] == "archived"

    def test_status_frozen_to_archived(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"], status="frozen")
        update_event(db, e["id"], status="archived")
        assert get_event(db, e["id"])["status"] == "archived"

    def test_status_invalid_transition(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"], status="archived")
        with pytest.raises(ValueError, match="Cannot transition"):
            update_event(db, e["id"], status="active")

    def test_status_frozen_cannot_go_active(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"], status="frozen")
        with pytest.raises(ValueError, match="Cannot transition"):
            update_event(db, e["id"], status="active")

    def test_update_invalid_status(self, db):
        e = create_event(db, "Test")
        with pytest.raises(ValueError, match="Invalid status"):
            update_event(db, e["id"], status="deleted")

    def test_update_nonexistent(self, db):
        with pytest.raises(ValueError, match="not found"):
            update_event(db, "nonexistent-id", status="frozen")

    def test_update_noop(self, db):
        e = create_event(db, "Test")
        update_event(db, e["id"])
        assert get_event(db, e["id"])["title"] == "Test"


class TestLinkEventSession:
    def test_link_session(self, db):
        e = create_event(db, "Test event")
        create_session(db, "p1", session_id="s1")
        link_event_session(db, e["id"], "s1")
        sessions = get_event_sessions(db, e["id"])
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"

    def test_link_duplicate_ignored(self, db):
        e = create_event(db, "Test event")
        create_session(db, "p1", session_id="s1")
        link_event_session(db, e["id"], "s1")
        link_event_session(db, e["id"], "s1")
        sessions = get_event_sessions(db, e["id"])
        assert len(sessions) == 1

    def test_link_multiple_sessions(self, db):
        e = create_event(db, "Test event")
        create_session(db, "p1", session_id="s1")
        create_session(db, "p1", session_id="s2")
        link_event_session(db, e["id"], "s1")
        link_event_session(db, e["id"], "s2")
        sessions = get_event_sessions(db, e["id"])
        assert len(sessions) == 2


class TestLinkEventCheckpoint:
    def test_link_checkpoint(self, db):
        e = create_event(db, "Test event")
        create_session(db, "p1", session_id="s1")
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc123')")
        db.commit()
        link_event_checkpoint(db, e["id"], "cp1")
        checkpoints = get_event_checkpoints(db, e["id"])
        assert len(checkpoints) == 1
        assert checkpoints[0]["id"] == "cp1"

    def test_link_checkpoint_duplicate_ignored(self, db):
        e = create_event(db, "Test event")
        create_session(db, "p1", session_id="s1")
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc123')")
        db.commit()
        link_event_checkpoint(db, e["id"], "cp1")
        link_event_checkpoint(db, e["id"], "cp1")
        checkpoints = get_event_checkpoints(db, e["id"])
        assert len(checkpoints) == 1


class TestGetEventSessions:
    def test_no_linked_sessions(self, db):
        e = create_event(db, "Empty event")
        assert get_event_sessions(db, e["id"]) == []


class TestGetEventCheckpoints:
    def test_no_linked_checkpoints(self, db):
        e = create_event(db, "Empty event")
        assert get_event_checkpoints(db, e["id"]) == []
