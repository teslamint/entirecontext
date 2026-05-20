"""Tests for rejected-alternative normalization helpers and CLI (v0.6.1, #113-#118)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.decisions import (
    UNKNOWN_REASON,
    audit_rejected_alternatives,
    create_decision,
    get_decision,
    normalize_alternative,
    normalize_rejected_alternatives,
)
from entirecontext.db import get_db

runner = CliRunner()


# ---------------------------------------------------------------------------
# normalize_alternative
# ---------------------------------------------------------------------------


class TestNormalizeAlternative:
    def test_string_input_becomes_structured(self):
        result = normalize_alternative("Redis")
        assert result == {"alternative": "Redis", "reason": UNKNOWN_REASON}

    def test_string_strips_whitespace(self):
        result = normalize_alternative("  Redis  ")
        assert result["alternative"] == "Redis"

    def test_structured_input_passthrough(self):
        item = {"alternative": "Redis", "reason": "too much ops overhead"}
        result = normalize_alternative(item)
        assert result == item

    def test_structured_strips_whitespace(self):
        item = {"alternative": "  Redis  ", "reason": "  too slow  "}
        result = normalize_alternative(item)
        assert result["alternative"] == "Redis"
        assert result["reason"] == "too slow"

    def test_structured_missing_reason_fills_unknown(self):
        result = normalize_alternative({"alternative": "SQLite"})
        assert result["reason"] == UNKNOWN_REASON

    def test_structured_blank_reason_fills_unknown(self):
        result = normalize_alternative({"alternative": "SQLite", "reason": "   "})
        assert result["reason"] == UNKNOWN_REASON

    def test_structured_empty_alternative_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            normalize_alternative({"alternative": ""})

    def test_structured_missing_alternative_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            normalize_alternative({"reason": "some reason"})

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_alternative("")

    def test_blank_string_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_alternative("   ")

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize"):
            normalize_alternative(42)

    def test_none_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize"):
            normalize_alternative(None)

    def test_idempotent_on_already_structured(self):
        item = {"alternative": "Redis", "reason": "too much ops overhead"}
        first = normalize_alternative(item)
        second = normalize_alternative(first)
        assert first == second


# ---------------------------------------------------------------------------
# normalize_rejected_alternatives
# ---------------------------------------------------------------------------


class TestNormalizeRejectedAlternatives:
    def test_empty_list(self):
        assert normalize_rejected_alternatives([]) == []

    def test_all_strings(self):
        result = normalize_rejected_alternatives(["Redis", "Postgres"])
        assert all(r["reason"] == UNKNOWN_REASON for r in result)
        assert [r["alternative"] for r in result] == ["Redis", "Postgres"]

    def test_mixed_strings_and_structured(self):
        items = ["Redis", {"alternative": "Postgres", "reason": "already using SQLite"}]
        result = normalize_rejected_alternatives(items)
        assert result[0] == {"alternative": "Redis", "reason": UNKNOWN_REASON}
        assert result[1] == {"alternative": "Postgres", "reason": "already using SQLite"}

    def test_already_structured_passthrough(self):
        items = [{"alternative": "Redis", "reason": "ops overhead"}]
        assert normalize_rejected_alternatives(items) == items

    def test_non_list_raises(self):
        with pytest.raises(TypeError, match="must be a list"):
            normalize_rejected_alternatives("Redis")  # type: ignore[arg-type]

    def test_malformed_item_raises(self):
        with pytest.raises(ValueError):
            normalize_rejected_alternatives([42])

    def test_idempotent(self):
        items = ["Redis", {"alternative": "Postgres", "reason": "already using SQLite"}]
        first = normalize_rejected_alternatives(items)
        second = normalize_rejected_alternatives(first)
        assert first == second


# ---------------------------------------------------------------------------
# audit_rejected_alternatives
# ---------------------------------------------------------------------------


class TestAuditRejectedAlternatives:
    def test_empty_list(self):
        report = audit_rejected_alternatives([])
        assert report["total"] == 0
        assert report["needs_normalization"] is False

    def test_all_structured_with_reasons(self):
        items = [{"alternative": "Redis", "reason": "too heavy"}]
        report = audit_rejected_alternatives(items)
        assert report["needs_normalization"] is False
        assert report["legacy_strings"] == 0
        assert report["malformed"] == []

    def test_detects_legacy_strings(self):
        report = audit_rejected_alternatives(["Redis", "Postgres"])
        assert report["legacy_strings"] == 2
        assert report["needs_normalization"] is True

    def test_detects_missing_reasons(self):
        items = [{"alternative": "Redis"}, {"alternative": "Postgres", "reason": "too slow"}]
        report = audit_rejected_alternatives(items)
        assert report["missing_reason"] == 1
        assert report["needs_normalization"] is False

    def test_detects_unknown_reason_as_missing(self):
        items = [{"alternative": "Redis", "reason": UNKNOWN_REASON}]
        report = audit_rejected_alternatives(items)
        assert report["missing_reason"] == 1

    def test_detects_malformed_entries(self):
        items = [42, {"alternative": "Redis"}]
        report = audit_rejected_alternatives(items)
        assert 0 in report["malformed"]
        assert report["needs_normalization"] is True

    def test_malformed_index_is_correct(self):
        items = [
            {"alternative": "Redis", "reason": "too heavy"},
            42,
            {"alternative": "Postgres"},
        ]
        report = audit_rejected_alternatives(items)
        assert report["malformed"] == [1]

    def test_mixed_issues(self):
        items = ["legacy", {"alternative": "Postgres", "reason": "too slow"}, None]
        report = audit_rejected_alternatives(items)
        assert report["legacy_strings"] == 1
        assert 2 in report["malformed"]
        assert report["needs_normalization"] is True


# ---------------------------------------------------------------------------
# CLI: ec decision alternatives audit
# ---------------------------------------------------------------------------


class TestAlternativesAuditCLI:
    def test_all_structured_reports_ok(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Audit clean",
            rejected_alternatives=[{"alternative": "Redis", "reason": "ops overhead"}],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "audit", decision["id"][:12]])
        assert result.exit_code == 0
        assert "structured and complete" in result.stdout

    def test_legacy_strings_flagged(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Audit legacy",
            rejected_alternatives=["Redis", "Postgres"],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "audit", decision["id"][:12]])
        assert result.exit_code == 0
        assert "Legacy strings" in result.stdout or "legacy" in result.stdout.lower()

    def test_not_found_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["decision", "alternatives", "audit", "nonexistent"])
        assert result.exit_code != 0

    def test_empty_alternatives_shows_total_zero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="No alternatives")
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "audit", decision["id"][:12]])
        assert result.exit_code == 0
        assert "0 alternative" in result.stdout


# ---------------------------------------------------------------------------
# CLI: ec decision alternatives normalize
# ---------------------------------------------------------------------------


class TestAlternativesNormalizeCLI:
    def test_normalizes_legacy_strings(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Normalize me",
            rejected_alternatives=["Redis", "Postgres"],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        updated = get_decision(conn, decision["id"])
        conn.close()
        alts = updated["rejected_alternatives"]
        assert all(isinstance(a, dict) for a in alts)
        assert all(a["reason"] == UNKNOWN_REASON for a in alts)
        assert {a["alternative"] for a in alts} == {"Redis", "Postgres"}

    def test_fills_missing_structured_reason(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Normalize missing reason",
            rejected_alternatives=[{"alternative": "Redis"}],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        updated = get_decision(conn, decision["id"])
        conn.close()
        assert updated["rejected_alternatives"] == [{"alternative": "Redis", "reason": UNKNOWN_REASON}]

    def test_already_normalized_is_noop(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Already structured",
            rejected_alternatives=[{"alternative": "Redis", "reason": "ops overhead"}],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        assert result.exit_code == 0
        assert "nothing to do" in result.stdout.lower() or "already" in result.stdout.lower()

    def test_dry_run_does_not_write(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        original_alts = ["Redis"]
        decision = create_decision(
            conn,
            title="Dry run decision",
            rejected_alternatives=original_alts,
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "normalize", "--dry-run", decision["id"][:12]])
        assert result.exit_code == 0
        assert "dry-run" in result.stdout.lower()

        conn = get_db(str(ec_repo))
        unchanged = get_decision(conn, decision["id"])
        conn.close()
        assert unchanged["rejected_alternatives"] == original_alts

    def test_malformed_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Malformed")
        conn.close()

        conn = get_db(str(ec_repo))
        conn.execute(
            "UPDATE decisions SET rejected_alternatives = ? WHERE id = ?",
            (json.dumps([42, "valid"]), decision["id"]),
        )
        conn.commit()
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        assert result.exit_code != 0

    def test_idempotent_second_run(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Idempotent test",
            rejected_alternatives=["Redis"],
        )
        conn.close()

        runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        result2 = runner.invoke(app, ["decision", "alternatives", "normalize", decision["id"][:12]])
        assert result2.exit_code == 0
        assert "nothing to do" in result2.stdout.lower() or "already" in result2.stdout.lower()


# ---------------------------------------------------------------------------
# CLI: ec decision alternatives set
# ---------------------------------------------------------------------------


class TestAlternativesSetCLI:
    def test_set_structured_list(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Set me")
        conn.close()

        new_alts = json.dumps([{"alternative": "Redis", "reason": "ops overhead"}])
        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], new_alts])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        updated = get_decision(conn, decision["id"])
        conn.close()
        assert updated["rejected_alternatives"] == [{"alternative": "Redis", "reason": "ops overhead"}]

    def test_set_string_items_normalizes(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Set with strings")
        conn.close()

        new_alts = json.dumps(["Redis", "Postgres"])
        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], new_alts])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        updated = get_decision(conn, decision["id"])
        conn.close()
        alts = updated["rejected_alternatives"]
        assert all(isinstance(a, dict) for a in alts)

    def test_invalid_json_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Bad JSON")
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], "{bad json}"])
        assert result.exit_code != 0
        assert "Invalid JSON" in result.stdout or "json" in result.stdout.lower()

    def test_non_array_json_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Non-array")
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], '{"not": "array"}'])
        assert result.exit_code != 0

    def test_malformed_item_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Malformed item")
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], "[42]"])
        assert result.exit_code != 0
        assert "Validation error" in result.stdout or "error" in result.stdout.lower()

    def test_set_empty_list_clears_alternatives(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(
            conn,
            title="Clear me",
            rejected_alternatives=["Redis"],
        )
        conn.close()

        result = runner.invoke(app, ["decision", "alternatives", "set", decision["id"][:12], "[]"])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        updated = get_decision(conn, decision["id"])
        conn.close()
        assert updated["rejected_alternatives"] == []

    def test_not_found_exits_nonzero(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        result = runner.invoke(app, ["decision", "alternatives", "set", "nonexistent", "[]"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Extraction parser: structured format acceptance (#117)
# ---------------------------------------------------------------------------


class TestExtractionParserStructuredFormat:
    def test_structured_alternatives_parsed_correctly(self):
        from entirecontext.core.decision_extraction import SignalBundle, parse_llm_response

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["..."],
            files=set(),
        )
        raw_json = json.dumps(
            [
                {
                    "title": "Use PostgreSQL over SQLite",
                    "rationale": "Need concurrent writers",
                    "scope": "database",
                    "rejected_alternatives": [
                        {"alternative": "SQLite", "reason": "no concurrent writes"},
                        {"alternative": "MySQL", "reason": "licensing concerns"},
                    ],
                }
            ]
        )
        drafts = parse_llm_response(raw_json, bundle)
        assert len(drafts) == 1
        alts = drafts[0].rejected_alternatives
        assert len(alts) == 2
        assert alts[0] == {"alternative": "SQLite", "reason": "no concurrent writes"}
        assert alts[1] == {"alternative": "MySQL", "reason": "licensing concerns"}

    def test_legacy_string_alternatives_normalized(self):
        from entirecontext.core.decision_extraction import SignalBundle, parse_llm_response

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["..."],
            files=set(),
        )
        raw_json = json.dumps(
            [
                {
                    "title": "Use PostgreSQL",
                    "rationale": "...",
                    "scope": "database",
                    "rejected_alternatives": ["SQLite", "MySQL"],
                }
            ]
        )
        drafts = parse_llm_response(raw_json, bundle)
        assert len(drafts) == 1
        alts = drafts[0].rejected_alternatives
        assert all(isinstance(a, dict) for a in alts)
        assert all(a["reason"] == UNKNOWN_REASON for a in alts)

    def test_malformed_alternatives_dropped_silently(self):
        from entirecontext.core.decision_extraction import SignalBundle, parse_llm_response

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["..."],
            files=set(),
        )
        raw_json = json.dumps(
            [
                {
                    "title": "Use PostgreSQL",
                    "rationale": "...",
                    "scope": "db",
                    "rejected_alternatives": [42, "valid string", None],
                }
            ]
        )
        drafts = parse_llm_response(raw_json, bundle)
        assert len(drafts) == 1
        alts = drafts[0].rejected_alternatives
        assert len(alts) == 1
        assert alts[0]["alternative"] == "valid string"

    def test_structured_without_reason_fills_unknown(self):
        from entirecontext.core.decision_extraction import SignalBundle, parse_llm_response

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["..."],
            files=set(),
        )
        raw_json = json.dumps(
            [
                {
                    "title": "Use PostgreSQL",
                    "rationale": "...",
                    "scope": "db",
                    "rejected_alternatives": [{"alternative": "SQLite"}],
                }
            ]
        )
        drafts = parse_llm_response(raw_json, bundle)
        assert drafts[0].rejected_alternatives[0]["reason"] == UNKNOWN_REASON
