"""Unit + integration tests for the candidate decision extraction pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from entirecontext.core.decision_candidates import (
    confirm_candidate,
    get_candidate,
    list_candidates,
    reject_candidate,
)
from entirecontext.core.decision_extraction import (
    CandidateDraft,
    DecisionExtractionError,
    DedupResult,
    SignalBundle,
    _tokenize_title_for_fts,
    collect_signals,
    compute_dedup_key,
    is_session_extracted,
    mark_session_extracted,
    normalize_title_for_dedup,
    parse_llm_response,
    persist_candidate,
    score_confidence,
)
from entirecontext.core.decisions import create_decision
from entirecontext.core.futures import create_assessment
from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_session(conn, ec_repo, session_id: str = "extraction-test-session") -> dict:
    project = get_project(str(ec_repo))
    return create_session(conn, project["id"], session_id=session_id)


def _seed_turn(conn, session_id: str, turn_number: int, summary: str, files: list[str] | None = None) -> dict:
    turn = create_turn(conn, session_id, turn_number, user_message=f"msg {turn_number}")
    conn.execute(
        "UPDATE turns SET assistant_summary = ?, files_touched = ?, turn_status = 'completed' WHERE id = ?",
        (summary, json.dumps(files) if files else None, turn["id"]),
    )
    conn.commit()
    return turn


def _seed_checkpoint(
    conn,
    session_id: str,
    diff_summary: str,
    created_at: str | None = None,
    commit_hash: str = "abc123",
) -> dict:
    import uuid

    checkpoint_id = str(uuid.uuid4())
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (checkpoint_id, session_id, commit_hash, diff_summary, created_at),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------------------
# Unit tests — normalization, dedup key, tokenization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_basic(self):
        assert normalize_title_for_dedup("Use Redis for Caching!!") == "use redis for caching"

    def test_normalize_case_invariance(self):
        assert normalize_title_for_dedup("USE REDIS") == normalize_title_for_dedup("use redis")

    def test_normalize_whitespace_collapses(self):
        assert normalize_title_for_dedup("  use   redis\nfor\tcaching  ") == "use redis for caching"

    def test_compute_dedup_key_stable(self):
        k1 = compute_dedup_key("Use Redis")
        k2 = compute_dedup_key("use redis!!")
        assert k1 == k2

    def test_dedup_key_12_chars(self):
        k = compute_dedup_key("hello world")
        assert len(k) == 12

    def test_tokenize_title(self):
        result = _tokenize_title_for_fts("Use JWT over session-based auth")
        assert result is not None
        assert "jwt" in result.lower()
        assert "auth" in result.lower()

    def test_tokenize_empty(self):
        assert _tokenize_title_for_fts("") is None


class TestNormalizeFTSScores:
    def test_single_match_returns_mid_value(self):
        """Regression: single-match must return mid-value 0.5 (matching
        core.decisions._fts_rank_decisions_from_diff convention), not
        1.0. Otherwise any single FTS hit on a shared stopword-adjacent
        token propagates as the full dedup penalty weight and zeros out
        legitimate candidates."""
        from entirecontext.core.decision_extraction import _normalize_fts_scores

        class _Row(dict):
            def __getitem__(self, key):
                return super().__getitem__(key)

        rows = [_Row({"rowid": 1, "rank": -1.5})]
        result = _normalize_fts_scores(rows)
        assert result == {"1": 0.5}

    def test_multi_match_spans_zero_to_one(self):
        from entirecontext.core.decision_extraction import _normalize_fts_scores

        rows = [
            {"rowid": 1, "rank": -1.0},  # weakest
            {"rowid": 2, "rank": -3.0},  # strongest (bm25 is negative)
            {"rowid": 3, "rank": -2.0},  # middle
        ]
        result = _normalize_fts_scores(rows)
        assert result["1"] == 0.0
        assert result["2"] == 1.0
        assert result["3"] == 0.5

    def test_empty_input(self):
        from entirecontext.core.decision_extraction import _normalize_fts_scores

        assert _normalize_fts_scores([]) == {}


# ---------------------------------------------------------------------------
# Unit tests — confidence scoring
# ---------------------------------------------------------------------------


def _mock_draft(
    source_type: str,
    *,
    rationale: str | None = None,
    rejected: list | None = None,
    files: list | None = None,
) -> CandidateDraft:
    return CandidateDraft(
        title="t",
        rationale=rationale,
        scope=None,
        rejected_alternatives=rejected or [],
        supporting_evidence=[],
        source_type=source_type,
        source_id=f"{source_type}-1",
        session_id="s1",
        checkpoint_id=None,
        assessment_id=None,
        files=files or [],
    )


class TestConfidenceScoring:
    def test_session_base_weight(self):
        draft = _mock_draft("session")
        dr = DedupResult(dedup_key="k")
        score, breakdown = score_confidence(draft, dr)
        assert abs(score - 0.30) < 1e-6
        assert breakdown["base"]["weight"] == 0.30

    def test_checkpoint_base_weight(self):
        draft = _mock_draft("checkpoint")
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.40) < 1e-6

    def test_assessment_base_weight(self):
        draft = _mock_draft("assessment")
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.55) < 1e-6

    def test_rationale_bonus(self):
        long_rationale = "this rationale is clearly longer than thirty characters"
        draft = _mock_draft("session", rationale=long_rationale)
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.45) < 1e-6

    def test_short_rationale_no_bonus(self):
        draft = _mock_draft("session", rationale="short")
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.30) < 1e-6

    def test_alts_bonus(self):
        draft = _mock_draft("session", rejected=["old approach"])
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.45) < 1e-6

    def test_files_in_band_bonus(self):
        draft = _mock_draft("session", files=["a.py", "b.py"])
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.40) < 1e-6

    def test_zero_files_no_bonus(self):
        draft = _mock_draft("session", files=[])
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.30) < 1e-6

    def test_too_many_files_no_bonus(self):
        draft = _mock_draft("session", files=[f"f{i}.py" for i in range(10)])
        dr = DedupResult(dedup_key="k")
        score, _ = score_confidence(draft, dr)
        assert abs(score - 0.30) < 1e-6

    def test_penalty_clamps_to_zero(self):
        draft = _mock_draft("session")
        dr = DedupResult(dedup_key="k", score_vs_decisions=4.0, score_vs_candidates=4.0)
        score, _ = score_confidence(draft, dr)
        assert score == 0.0

    def test_breakdown_has_expected_keys(self):
        draft = _mock_draft(
            "assessment",
            rationale="long rationale exceeding thirty characters easily",
            rejected=["alt"],
            files=["a.py"],
        )
        dr = DedupResult(dedup_key="k", score_vs_decisions=0.2)
        score, breakdown = score_confidence(draft, dr)
        assert "initial" in breakdown
        assert "penalties" in breakdown
        assert "final" in breakdown
        assert breakdown["initial"] == 0.95  # 0.55 + 0.15 + 0.15 + 0.10
        assert score < breakdown["initial"]


# ---------------------------------------------------------------------------
# Integration tests — session marker (including v12 shim)
# ---------------------------------------------------------------------------


class TestSessionMarker:
    def test_fresh_session_not_marked(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo)
        assert is_session_extracted(ec_db, session["id"]) is False

    def test_mark_session_extracted(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo)
        mark_session_extracted(ec_db, session["id"])
        assert is_session_extracted(ec_db, session["id"]) is True

    def test_v12_marker_recognized(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo)
        ec_db.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"decisions_extracted": True}), session["id"]),
        )
        ec_db.commit()
        assert is_session_extracted(ec_db, session["id"]) is True


# ---------------------------------------------------------------------------
# Integration tests — signal collection per source
# ---------------------------------------------------------------------------


class TestSignalCollection:
    def test_session_no_keyword_match(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo)
        _seed_turn(ec_db, session["id"], 1, "Just a normal status update")
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        assert all(b.source_type != "session" for b in bundles)

    def test_session_with_keyword_match(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo)
        _seed_turn(
            ec_db,
            session["id"],
            1,
            "We decided to use Redis over memcached",
            files=["src/cache.py"],
        )
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        session_bundles = [b for b in bundles if b.source_type == "session"]
        assert len(session_bundles) == 1
        assert "src/cache.py" in session_bundles[0].files

    def test_session_empty_intersection_files(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="s-empty-intersect")
        _seed_turn(ec_db, session["id"], 1, "We decided on approach A", files=["a.py"])
        _seed_turn(ec_db, session["id"], 2, "We decided approach B instead", files=["b.py"])
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        session_bundles = [b for b in bundles if b.source_type == "session"]
        assert len(session_bundles) == 1
        # Intersection of {a.py} and {b.py} is empty and must NOT fall back
        # to the union.
        assert session_bundles[0].files == []

    def test_checkpoint_single_file_skipped(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="s-cp-single")
        _seed_turn(ec_db, session["id"], 1, "refactor", files=["a.py"])
        _seed_checkpoint(ec_db, session["id"], diff_summary="a.py | 5 +++--", commit_hash="cp1")
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        assert all(b.source_type != "checkpoint" for b in bundles)

    def test_checkpoint_multi_file_included(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="s-cp-multi")
        _seed_turn(ec_db, session["id"], 1, "refactor", files=["a.py", "b.py", "c.py"])
        _seed_checkpoint(
            ec_db,
            session["id"],
            diff_summary="a.py | 5 +++--\nb.py | 3 +++\nc.py | 2 +",
            commit_hash="cp2",
        )
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        cp_bundles = [b for b in bundles if b.source_type == "checkpoint"]
        assert len(cp_bundles) == 1
        assert set(cp_bundles[0].files) == {"a.py", "b.py", "c.py"}

    def test_checkpoint_does_not_read_files_snapshot(self, ec_repo, ec_db):
        """Checkpoint files come from turn window, not from files_snapshot."""
        session = _seed_session(ec_db, ec_repo, session_id="s-no-snapshot")
        _seed_turn(ec_db, session["id"], 1, "changes", files=["x.py", "y.py"])
        # Seed checkpoint with NULL files_snapshot (matching real auto-created checkpoints).
        _seed_checkpoint(ec_db, session["id"], diff_summary="x.py | 1\ny.py | 1", commit_hash="nosnap")
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        cp_bundles = [b for b in bundles if b.source_type == "checkpoint"]
        assert len(cp_bundles) == 1
        assert set(cp_bundles[0].files) == {"x.py", "y.py"}

    def test_checkpoint_window_bridges_timestamp_format_mismatch(self, ec_repo, ec_db):
        """Regression: turns.timestamp uses ISO-8601 with 'T' separator, while
        checkpoints.created_at DEFAULT datetime('now') produces space-separated
        form. Lexicographic comparison used to silently drop the entire turn
        window. The fix wraps both sides in sqlite's datetime() normalizer."""
        session = _seed_session(ec_db, ec_repo, session_id="s-format-mismatch")
        # Seed turns via create_turn — this writes the real ISO format.
        _seed_turn(ec_db, session["id"], 1, "work on cache", files=["cache.py", "config.py"])
        _seed_turn(ec_db, session["id"], 2, "finish work", files=["cache.py", "runner.py"])
        # Use the real schema default for created_at (space-separated form)
        # instead of an ISO string, reproducing the production bug path.
        import uuid as _uuid

        checkpoint_id = str(_uuid.uuid4())
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary) VALUES (?, ?, ?, ?)",
            (checkpoint_id, session["id"], "mismatch-hash", "cache.py | 5\nconfig.py | 3\nrunner.py | 1"),
        )
        ec_db.commit()
        # Confirm the created_at is indeed space-separated (production shape).
        row = ec_db.execute("SELECT created_at FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
        assert " " in row["created_at"] and "T" not in row["created_at"]

        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        cp_bundles = [b for b in bundles if b.source_type == "checkpoint"]
        assert len(cp_bundles) == 1
        # Turn window must include both turns despite the format mismatch.
        assert set(cp_bundles[0].files) == {"cache.py", "config.py", "runner.py"}

    def test_assessment_neutral_skipped(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="s-neutral")
        _seed_turn(ec_db, session["id"], 1, "work", files=["a.py", "b.py"])
        cp = _seed_checkpoint(ec_db, session["id"], diff_summary="a.py|1\nb.py|1", commit_hash="cp-neutral")
        create_assessment(
            ec_db,
            verdict="neutral",
            impact_summary="no impact",
            roadmap_alignment="",
            tidy_suggestion="",
            diff_summary="",
            checkpoint_id=cp["id"],
        )
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        assert all(b.source_type != "assessment" for b in bundles)

    def test_assessment_expand_collected(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="s-expand")
        _seed_turn(ec_db, session["id"], 1, "work", files=["a.py", "b.py"])
        cp = _seed_checkpoint(ec_db, session["id"], diff_summary="a.py|1\nb.py|1", commit_hash="cp-expand")
        create_assessment(
            ec_db,
            verdict="expand",
            impact_summary="expands scope to cover X",
            roadmap_alignment="aligned",
            tidy_suggestion="consider extracting Y",
            diff_summary="diff",
            checkpoint_id=cp["id"],
        )
        bundles = collect_signals(ec_db, session["id"], str(ec_repo))
        assess_bundles = [b for b in bundles if b.source_type == "assessment"]
        assert len(assess_bundles) == 1
        assert set(assess_bundles[0].files) >= {"a.py", "b.py"}


# ---------------------------------------------------------------------------
# Unit tests — parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def _bundle(self) -> SignalBundle:
        return SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="sess",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["x"],
            files=["a.py"],
        )

    def test_invalid_json_raises(self):
        with pytest.raises(DecisionExtractionError):
            parse_llm_response("not json", self._bundle())

    def test_non_list_returns_empty(self):
        result = parse_llm_response('{"not": "a list"}', self._bundle())
        assert result == []

    def test_valid_array(self):
        raw = json.dumps(
            [{"title": "Use Redis", "rationale": "fast", "scope": "cache", "rejected_alternatives": ["memcached"]}]
        )
        drafts = parse_llm_response(raw, self._bundle())
        assert len(drafts) == 1
        assert drafts[0].title == "Use Redis"
        assert drafts[0].rejected_alternatives == ["memcached"]

    def test_caps_at_five(self):
        raw = json.dumps([{"title": f"D{i}"} for i in range(10)])
        drafts = parse_llm_response(raw, self._bundle())
        assert len(drafts) == 5

    def test_skips_missing_title(self):
        raw = json.dumps([{"title": "ok"}, {"no_title": "x"}, {"title": ""}])
        drafts = parse_llm_response(raw, self._bundle())
        assert len(drafts) == 1


# ---------------------------------------------------------------------------
# Integration tests — end-to-end run_extraction via shim
# ---------------------------------------------------------------------------


class TestEndToEndExtraction:
    def test_session_only_extraction(self, ec_repo, ec_db, monkeypatch):
        session = _seed_session(ec_db, ec_repo, session_id="e2e-session-only")
        _seed_turn(
            ec_db,
            session["id"],
            1,
            "We decided to use Redis instead of memcached",
            files=["src/cache.py"],
        )
        llm_response = json.dumps(
            [
                {
                    "title": "Use Redis for cache",
                    "rationale": "Redis persistence is essential for our use case",
                    "scope": "cache",
                    "rejected_alternatives": ["memcached"],
                }
            ]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        candidates = list_candidates(ec_db, session_id=session["id"])
        assert len(candidates) == 1
        assert candidates[0]["source_type"] == "session"
        assert candidates[0]["review_status"] == "pending"
        assert candidates[0]["confidence"] > 0.0

    def test_retriever_isolation(self, ec_repo, ec_db, monkeypatch):
        """Pending candidates must not leak into decision retrievers."""
        from entirecontext.core.decisions import rank_related_decisions

        # Seed a real decision the retriever should see
        create_decision(
            ec_db,
            title="Real confirmed decision",
            rationale="carry forward",
            scope="test",
        )

        # Seed a candidate with a similar title
        session = _seed_session(ec_db, ec_repo, session_id="e2e-isolation")
        _seed_turn(ec_db, session["id"], 1, "We decided to revisit the confirmed decision", files=["a.py"])
        llm_response = json.dumps(
            [
                {
                    "title": "Real confirmed decision variant",
                    "rationale": "a reasoned rationale longer than thirty characters",
                    "scope": "test",
                    "rejected_alternatives": [],
                }
            ]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        # Both tables should have data
        assert len(list_candidates(ec_db)) == 1
        # Retrievers must only see the confirmed decision, not the candidate
        ranked, _stats = rank_related_decisions(ec_db, file_paths=["a.py"], _return_stats=True)
        titles = [d.get("title") for d in ranked]
        assert "Real confirmed decision" in titles or ranked == []  # retriever may return empty if relevance low
        assert "Real confirmed decision variant" not in titles


# ---------------------------------------------------------------------------
# Confidence threshold tests
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    def test_score_below_threshold_filtered(self):
        """Session candidate with no rationale/alts/files scores 0.30 — below 0.35 threshold."""
        draft = CandidateDraft(
            title="Bare decision",
            rationale=None,
            scope=None,
            rejected_alternatives=[],
            supporting_evidence=[],
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            files=[],
        )
        dedup_result = DedupResult(dedup_key="test")
        score, _breakdown = score_confidence(draft, dedup_result)
        assert score < 0.35

    def test_score_above_threshold_passes(self):
        """Checkpoint candidate with rationale+alts scores well above 0.35."""
        draft = CandidateDraft(
            title="Use Redis for caching",
            rationale="Redis provides persistence and pub/sub which memcached lacks for our use case",
            scope=None,
            rejected_alternatives=["memcached"],
            supporting_evidence=[],
            source_type="checkpoint",
            source_id="cp1",
            session_id="s1",
            checkpoint_id="cp1",
            assessment_id=None,
            files=["src/cache.py"],
        )
        dedup_result = DedupResult(dedup_key="test")
        score, _breakdown = score_confidence(draft, dedup_result)
        assert score >= 0.35

    def test_run_extraction_skips_below_threshold(self, ec_repo, ec_db, monkeypatch):
        """run_extraction with min_confidence=1.0 should skip all candidates."""
        session = _seed_session(ec_db, ec_repo, session_id="conf-threshold-skip")
        _seed_turn(ec_db, session["id"], 1, "We decided something")
        llm_response = json.dumps(
            [
                {
                    "title": "Low confidence decision",
                    "rationale": "A rationale that is long enough to pass the 30 char check here",
                    "rejected_alternatives": ["option b"],
                }
            ]
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda *a, **kw: llm_response,
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction._load_decisions_config",
            lambda _: {"extract_keywords": ["decided"], "extract_sources": ["session"]},
        )
        from entirecontext.core.decision_extraction import run_extraction

        outcome = run_extraction(ec_db, session["id"], str(ec_repo), min_confidence=1.0)
        assert outcome.candidates_inserted == 0
        assert outcome.low_confidence_skipped >= 1


# ---------------------------------------------------------------------------
# Integration tests — confirm / reject flow
# ---------------------------------------------------------------------------


class TestConfirmRejectFlow:
    def _seed_candidate(self, ec_db, ec_repo, *, session_id="conf-session", checkpoint_id=None, assessment_id=None):
        session = _seed_session(ec_db, ec_repo, session_id=session_id)
        draft = CandidateDraft(
            title="Confirm test decision",
            rationale="a sufficiently long rationale to pass the heuristic",
            scope="test",
            rejected_alternatives=["alt"],
            supporting_evidence=[],
            source_type="session",
            source_id=session["id"],
            session_id=session["id"],
            checkpoint_id=checkpoint_id,
            assessment_id=assessment_id,
            files=["src/a.py", "src/b.py"],
        )
        dr = DedupResult(dedup_key=compute_dedup_key(draft.title))
        score, breakdown = score_confidence(draft, dr)
        result = persist_candidate(ec_db, draft, score, breakdown, dr)
        return result.candidate_id

    def test_confirm_creates_decision_with_files(self, ec_repo, ec_db):
        from entirecontext.core.decisions import get_decision

        cid = self._seed_candidate(ec_db, ec_repo)
        assert cid is not None
        result = confirm_candidate(ec_db, cid, reviewer="cli")
        assert result["promoted"] is True
        decision_id = result["decision_id"]
        decision = get_decision(ec_db, decision_id)
        assert decision is not None
        assert "src/a.py" in decision.get("files", [])
        assert "src/b.py" in decision.get("files", [])

    def test_confirm_promotes_checkpoint_and_assessment_links(self, ec_repo, ec_db):
        session = _seed_session(ec_db, ec_repo, session_id="conf-provenance")
        _seed_turn(ec_db, session["id"], 1, "work", files=["a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], diff_summary="a.py|1\nb.py|1", commit_hash="cp-prov")
        assess_id = create_assessment(
            ec_db,
            verdict="expand",
            impact_summary="x",
            checkpoint_id=cp["id"],
        )["id"]
        cid = self._seed_candidate(
            ec_db,
            ec_repo,
            session_id="conf-provenance-cand",
            checkpoint_id=cp["id"],
            assessment_id=assess_id,
        )
        result = confirm_candidate(ec_db, cid, reviewer="cli")
        decision_id = result["decision_id"]
        # decision_checkpoints link
        cp_link = ec_db.execute(
            "SELECT 1 FROM decision_checkpoints WHERE decision_id = ? AND checkpoint_id = ?",
            (decision_id, cp["id"]),
        ).fetchone()
        assert cp_link is not None
        # decision_assessments link with 'informed_by'
        assess_link = ec_db.execute(
            "SELECT relation_type FROM decision_assessments WHERE decision_id = ? AND assessment_id = ?",
            (decision_id, assess_id),
        ).fetchone()
        assert assess_link is not None
        assert assess_link["relation_type"] == "informed_by"

    def test_reject_no_decision_created(self, ec_repo, ec_db):
        cid = self._seed_candidate(ec_db, ec_repo, session_id="reject-session")
        reject_candidate(ec_db, cid, reason="not useful")
        after = get_candidate(ec_db, cid)
        assert after["review_status"] == "rejected"
        assert after["review_note"] == "not useful"
        # Decisions table remains empty
        decision_count = ec_db.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
        assert decision_count == 0

    def test_double_confirm_raises(self, ec_repo, ec_db):
        cid = self._seed_candidate(ec_db, ec_repo, session_id="double-session")
        confirm_candidate(ec_db, cid)
        with pytest.raises(ValueError):
            confirm_candidate(ec_db, cid)

    def test_confirm_claim_is_conditional_on_pending_status(self, ec_repo, ec_db):
        """Regression: the confirm path must gate on review_status='pending'
        via a conditional UPDATE, not via a separate pre-check. Manually
        flipping the row to 'rejected' between reads must cause the
        conditional UPDATE to miss and the call to raise ValueError without
        creating any decision row."""
        cid = self._seed_candidate(ec_db, ec_repo, session_id="conditional-claim")
        # Simulate a concurrent reject landing between the initial read and
        # the UPDATE. We do this by manually flipping review_status.
        ec_db.execute(
            "UPDATE decision_candidates SET review_status='rejected' WHERE id=?",
            (cid,),
        )
        ec_db.commit()
        with pytest.raises(ValueError):
            confirm_candidate(ec_db, cid)
        # Decisions table must remain untouched.
        decision_count = ec_db.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
        assert decision_count == 0

    def test_confirm_second_call_produces_exactly_one_decision(self, ec_repo, ec_db):
        """Regression: the earlier non-atomic flow could create duplicate
        decisions if confirm_candidate was invoked twice. The conditional
        UPDATE must ensure the second call raises immediately and the
        decisions table still holds exactly one row per confirmed candidate."""
        cid = self._seed_candidate(ec_db, ec_repo, session_id="exactly-one")
        confirm_candidate(ec_db, cid)
        with pytest.raises(ValueError):
            confirm_candidate(ec_db, cid)
        decision_rows = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decisions WHERE title = ?",
            ("Confirm test decision",),
        ).fetchone()
        assert decision_rows["c"] == 1

    def test_reject_is_conditional_on_pending_status(self, ec_repo, ec_db):
        """Regression: reject_candidate must use the same conditional UPDATE
        pattern as confirm_candidate so a concurrent confirm cannot race it
        into an invalid 'rejected with dangling promoted_decision_id' state."""
        cid = self._seed_candidate(ec_db, ec_repo, session_id="reject-race")
        # Simulate a concurrent confirm completing between our reject's
        # read and its UPDATE.
        confirm_candidate(ec_db, cid)
        # Now the candidate is 'confirmed'. A reject attempt must raise
        # without overwriting the status or orphaning the decision row.
        with pytest.raises(ValueError):
            reject_candidate(ec_db, cid, reason="conflict")
        fresh = get_candidate(ec_db, cid)
        assert fresh["review_status"] == "confirmed"
        assert fresh["promoted_decision_id"] is not None

    def test_reject_second_call_raises(self, ec_repo, ec_db):
        """Reject is idempotent from the caller's POV: second call raises."""
        cid = self._seed_candidate(ec_db, ec_repo, session_id="reject-double")
        reject_candidate(ec_db, cid)
        with pytest.raises(ValueError):
            reject_candidate(ec_db, cid)

    def test_confirm_rolls_back_claim_on_post_claim_failure(self, ec_repo, ec_db, monkeypatch):
        """Regression: if create_decision (or any auto-committing step after
        the claim) raises, confirm_candidate must roll the claim back to
        'pending' so the candidate can be retried later. Without the
        rollback, the candidate would stay stuck in 'confirmed' with
        promoted_decision_id=NULL and no real decision to back it."""
        cid = self._seed_candidate(ec_db, ec_repo, session_id="claim-rollback")

        def failing_create_decision(*args, **kwargs):
            raise RuntimeError("simulated post-claim failure")

        monkeypatch.setattr(
            "entirecontext.core.decisions.create_decision",
            failing_create_decision,
        )
        with pytest.raises(RuntimeError, match="simulated post-claim failure"):
            confirm_candidate(ec_db, cid)

        # After the failure, the candidate must be back to pending so that
        # a later retry (with a working create_decision) can succeed.
        after = get_candidate(ec_db, cid)
        assert after["review_status"] == "pending"
        assert after["promoted_decision_id"] is None
        # And of course, no decision row was created.
        decision_count = ec_db.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
        assert decision_count == 0

    def test_confirm_atomic_rollback_on_step3_failure(self, ec_repo, ec_db, monkeypatch):
        """Atomicity regression (S1): Step 2 (create_decision + provenance
        links + promoted_decision_id back-pointer UPDATE) is wrapped in a
        single BEGIN IMMEDIATE. If the back-pointer UPDATE fails after
        decision + links have already INSERTed, the entire transaction
        rolls back — no orphan `decisions` row, no orphan join rows.

        Pre-refactor, `create_decision` and each `link_*` helper called
        their own `conn.commit()`, so a failure between those commits and
        the Step 3 UPDATE left durable orphan state. This test fails
        under the pre-refactor code (assertions on the empty join tables
        would all see ≥1) and passes under the wrapped transaction."""
        session = _seed_session(ec_db, ec_repo, session_id="atomic-step3-fail")
        _seed_turn(ec_db, session["id"], 1, "work", files=["a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], diff_summary="a.py|1\nb.py|1", commit_hash="cp-atomic")
        assess_id = create_assessment(
            ec_db,
            verdict="expand",
            impact_summary="x",
            checkpoint_id=cp["id"],
        )["id"]
        # Seed a candidate with files + checkpoint_id + assessment_id so
        # all three link paths run before Step 3 fails — atomicity must
        # cover every join table, not just decision_files.
        cid = self._seed_candidate(
            ec_db,
            ec_repo,
            session_id="atomic-step3-fail-cand",
            checkpoint_id=cp["id"],
            assessment_id=assess_id,
        )

        # Make _now_iso fail on its 2nd call within decision_candidates.
        # Calls in confirm_candidate (the only call sites in this module):
        #   call 1: Step 1 claim UPDATE — succeeds
        #   call 2: Step 3 back-pointer UPDATE — raises
        #   call 3: outer-except claim rollback UPDATE — succeeds
        # Failure on call 2 means decisions + links have already INSERTed
        # in the wrapped transaction; the raise tears it down.
        # decisions._now_iso is a separate module-local function so the
        # helpers' updated_at timestamps are unaffected by this patch.
        import entirecontext.core.decision_candidates as dc_module

        original_now_iso = dc_module._now_iso
        call_count = {"n": 0}

        def maybe_failing_now_iso():
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated step 3 failure")
            return original_now_iso()

        monkeypatch.setattr(dc_module, "_now_iso", maybe_failing_now_iso)

        with pytest.raises(RuntimeError, match="simulated step 3 failure"):
            confirm_candidate(ec_db, cid, reviewer="cli")

        # Atomicity: every Step 2 write rolled back together.
        assert ec_db.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"] == 0
        assert ec_db.execute("SELECT COUNT(*) AS c FROM decision_files").fetchone()["c"] == 0
        assert ec_db.execute("SELECT COUNT(*) AS c FROM decision_checkpoints").fetchone()["c"] == 0
        assert ec_db.execute("SELECT COUNT(*) AS c FROM decision_assessments").fetchone()["c"] == 0
        # Outer-except's claim rollback UPDATE ran (call 3 succeeded), so
        # the candidate is retryable.
        after = get_candidate(ec_db, cid)
        assert after["review_status"] == "pending"
        assert after["promoted_decision_id"] is None


# ---------------------------------------------------------------------------
# Integration tests — dedup and noisy-input harness (Tier 1)
# ---------------------------------------------------------------------------


class TestDedupAndNoise:
    def test_duplicate_title_penalized_against_confirmed_decision(self, ec_repo, ec_db, monkeypatch):
        """Tier 1 noisy-input scenario: pre-existing confirmed decision."""
        create_decision(
            ec_db,
            title="Use Redis over memcached",
            rationale="legacy choice carried forward",
            scope="cache",
        )

        session = _seed_session(ec_db, ec_repo, session_id="noisy-preexisting")
        _seed_turn(ec_db, session["id"], 1, "We decided again on Redis over memcached", files=["cache.py"])
        llm_response = json.dumps(
            [
                {
                    "title": "Use Redis over memcached",
                    "rationale": "same as before",
                    "scope": "cache",
                    "rejected_alternatives": ["memcached"],
                }
            ]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        candidates = list_candidates(ec_db, session_id=session["id"])
        assert len(candidates) == 1
        # Dedup fuzzy hit against existing decision must reduce the score
        breakdown = candidates[0]["confidence_breakdown"]
        assert breakdown["penalties"]["vs_decisions"] > 0
        assert candidates[0]["confidence"] < 0.55

    def test_idempotent_same_title_reextraction(self, ec_repo, ec_db, monkeypatch):
        """Running extraction twice on same signals produces no duplicate rows."""
        session = _seed_session(ec_db, ec_repo, session_id="noisy-idempotent")
        _seed_turn(ec_db, session["id"], 1, "We decided to chose X", files=["x.py"])
        llm_response = json.dumps(
            [{"title": "Choose X", "rationale": "a reason long enough for the heuristic", "scope": "x"}]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        count_after_first = len(list_candidates(ec_db, session_id=session["id"]))
        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        count_after_second = len(list_candidates(ec_db, session_id=session["id"]))
        assert count_after_first == 1
        assert count_after_second == 1  # marker short-circuits second run

    def test_shim_passes_source_type_per_bundle(self, ec_repo, ec_db, monkeypatch):
        """Regression: the back-compat shim used to hardcode source_type='session'
        when invoking call_extraction_llm, so checkpoint/assessment bundles were
        sent through the wrong system prompt. The shim now dispatches through
        _invoke_get_llm_response which passes source_type to _get_llm_response."""
        session = _seed_session(ec_db, ec_repo, session_id="shim-source-type")
        _seed_turn(ec_db, session["id"], 1, "We decided to extract helpers", files=["a.py", "b.py"])
        _seed_checkpoint(
            ec_db,
            session["id"],
            diff_summary="a.py | 5\nb.py | 3",
            commit_hash="shim-cp",
        )

        captured: list[dict] = []

        def fake_llm(summaries, repo_path, source_type="session"):
            captured.append({"source_type": source_type, "text": summaries[:60]})
            return json.dumps(
                [
                    {
                        "title": f"{source_type} decision",
                        "rationale": "a long enough rationale for the heuristic bonus",
                        "scope": "x",
                    }
                ]
            )

        monkeypatch.setattr("entirecontext.cli.decisions_cmds._get_llm_response", fake_llm)
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        source_types_seen = {c["source_type"] for c in captured}
        # At minimum, both session and checkpoint source_type must reach the LLM
        # call with their own identifier.
        assert "session" in source_types_seen
        assert "checkpoint" in source_types_seen

    def test_shim_legacy_two_arg_monkeypatch_still_works(self, ec_repo, ec_db, monkeypatch):
        """Regression: pre-existing tests monkeypatch _get_llm_response with a
        2-arg lambda (no source_type). The shim's inspect-based dispatch must
        detect this and call the 2-arg version so those tests keep passing."""
        session = _seed_session(ec_db, ec_repo, session_id="shim-legacy")
        _seed_turn(ec_db, session["id"], 1, "We decided X", files=["a.py"])

        calls: list[int] = []

        def legacy_llm(summaries, repo_path):
            calls.append(1)
            return json.dumps([{"title": "Choose X", "rationale": "a reason long enough for heuristic", "scope": "x"}])

        monkeypatch.setattr("entirecontext.cli.decisions_cmds._get_llm_response", legacy_llm)
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        assert len(calls) == 1
        assert len(list_candidates(ec_db, session_id=session["id"])) == 1

    def test_low_signal_candidate_below_threshold(self, ec_repo, ec_db, monkeypatch):
        """Candidates with no rationale / alts / files sit below default filter."""
        session = _seed_session(ec_db, ec_repo, session_id="noisy-lowsignal")
        _seed_turn(ec_db, session["id"], 1, "We decided something", files=[])
        llm_response = json.dumps(
            [{"title": "Vague choice", "rationale": "", "scope": "", "rejected_alternatives": []}]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        all_candidates = list_candidates(ec_db, session_id=session["id"])
        filtered = list_candidates(ec_db, session_id=session["id"], min_confidence=0.5)
        assert len(all_candidates) == 1
        assert all_candidates[0]["confidence"] < 0.5
        assert len(filtered) == 0


# ---------------------------------------------------------------------------
# F2: outcome → extraction penalty feedback
# ---------------------------------------------------------------------------


class TestOutcomeFeedbackPenalty:
    """Outcome history on a file attenuates new-candidate confidence."""

    def _seed_decision_with_outcomes(
        self,
        ec_db,
        *,
        title: str,
        file_paths: list[str],
        outcome_types: list[str],
    ) -> str:
        """Create a decision, link files, and record outcomes. Returns decision id."""
        from entirecontext.core.decisions import (
            link_decision_to_file,
            record_decision_outcome,
        )

        decision = create_decision(
            ec_db,
            title=title,
            rationale="seed rationale for outcome-feedback test",
        )
        for fp in file_paths:
            link_decision_to_file(ec_db, decision["id"], fp)
        for ot in outcome_types:
            record_decision_outcome(ec_db, decision["id"], ot)
        return decision["id"]

    def test_outcome_feedback_penalty_on_contradicted_files(self, ec_repo, ec_db):
        """Files with majority-contradicted history get the penalty applied."""
        from entirecontext.core.decision_extraction import (
            apply_outcome_feedback_to_confidence,
            get_file_outcome_stats,
        )

        self._seed_decision_with_outcomes(
            ec_db,
            title="Prior decision on payment",
            file_paths=["src/service/payment.py"],
            outcome_types=["contradicted", "contradicted", "accepted"],
        )

        stats = get_file_outcome_stats(ec_db, ["src/service/payment.py"], lookback_days=60)
        assert stats["contradicted"] == 2
        assert stats["accepted"] == 1
        assert stats["total"] == 3

        breakdown = {"final": 0.60, "penalties": {}}
        adjusted, new_breakdown = apply_outcome_feedback_to_confidence(0.60, breakdown, stats, penalty=0.15)
        # 2/3 > 0.5 → penalty applied.
        assert adjusted == pytest.approx(0.45)
        assert new_breakdown["outcome_feedback"]["applied"] is True
        assert new_breakdown["outcome_feedback"]["ratio"] == pytest.approx(2 / 3, abs=1e-4)
        assert new_breakdown["final_before_outcome_feedback"] == 0.60
        assert new_breakdown["final"] == pytest.approx(0.45)

    def test_outcome_feedback_disabled_no_change(self, ec_repo, ec_db):
        """lookback_days<=0 short-circuits to zeros, skipping the penalty entirely."""
        from entirecontext.core.decision_extraction import (
            apply_outcome_feedback_to_confidence,
            get_file_outcome_stats,
        )

        self._seed_decision_with_outcomes(
            ec_db,
            title="Prior decision on payment",
            file_paths=["src/service/payment.py"],
            outcome_types=["contradicted", "contradicted", "contradicted"],
        )

        stats = get_file_outcome_stats(ec_db, ["src/service/payment.py"], lookback_days=0)
        assert stats == {"accepted": 0, "ignored": 0, "contradicted": 0, "total": 0}

        breakdown = {"final": 0.60, "penalties": {}}
        adjusted, new_breakdown = apply_outcome_feedback_to_confidence(0.60, breakdown, stats, penalty=0.15)
        assert adjusted == 0.60
        assert new_breakdown["outcome_feedback"]["applied"] is False
        assert new_breakdown["outcome_feedback"]["total"] == 0
        # Unchanged path does not add the "final_before_outcome_feedback" key.
        assert "final_before_outcome_feedback" not in new_breakdown

    def test_outcome_feedback_penalty_respects_ratio_gate(self, ec_repo, ec_db):
        """Contradicted ratio of exactly 0.5 must NOT trigger penalty (strict > gate)."""
        from entirecontext.core.decision_extraction import (
            apply_outcome_feedback_to_confidence,
            get_file_outcome_stats,
        )

        self._seed_decision_with_outcomes(
            ec_db,
            title="Borderline decision",
            file_paths=["src/service/payment.py"],
            outcome_types=["contradicted", "accepted"],
        )

        stats = get_file_outcome_stats(ec_db, ["src/service/payment.py"], lookback_days=60)
        assert stats["contradicted"] == 1
        assert stats["accepted"] == 1
        assert stats["total"] == 2

        breakdown = {"final": 0.60, "penalties": {}}
        adjusted, new_breakdown = apply_outcome_feedback_to_confidence(0.60, breakdown, stats, penalty=0.15)
        # 1/2 is NOT strictly > 0.5 — no penalty.
        assert adjusted == 0.60
        assert new_breakdown["outcome_feedback"]["applied"] is False
        assert new_breakdown["outcome_feedback"]["ratio"] == pytest.approx(0.5)

    def test_outcome_feedback_sql_path_normalization(self, ec_repo, ec_db):
        """Stored ``./src/...`` and backslash paths must match normalized inputs."""
        from entirecontext.core.decision_extraction import get_file_outcome_stats

        self._seed_decision_with_outcomes(
            ec_db,
            title="Decision stored with ./prefix",
            file_paths=["./src/service/payment.py"],
            outcome_types=["contradicted", "contradicted"],
        )
        self._seed_decision_with_outcomes(
            ec_db,
            title="Decision stored with backslash",
            file_paths=["src\\service\\auth.py"],
            outcome_types=["accepted"],
        )

        # Input uses the canonical ``src/...`` form; both rows must match.
        stats = get_file_outcome_stats(
            ec_db,
            ["src/service/payment.py", "src/service/auth.py"],
            lookback_days=60,
        )
        assert stats["contradicted"] == 2
        assert stats["accepted"] == 1
        assert stats["total"] == 3

    def test_outcome_feedback_lookback_cutoff(self, ec_repo, ec_db):
        """Outcomes older than the lookback window must be excluded."""
        from entirecontext.core.decision_extraction import get_file_outcome_stats
        from entirecontext.core.decisions import link_decision_to_file

        decision = create_decision(
            ec_db,
            title="Decision with old outcomes",
            rationale="seeded with both fresh and ancient outcomes",
        )
        link_decision_to_file(ec_db, decision["id"], "src/service/payment.py")

        # Recent row (within window) — written via datetime('now')
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at)"
            " VALUES (?, ?, 'contradicted', datetime('now'))",
            ("recent-1", decision["id"]),
        )
        # Old row (outside 60d window) — explicitly backdated 120 days
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at)"
            " VALUES (?, ?, 'contradicted', datetime('now', '-120 days'))",
            ("old-1", decision["id"]),
        )
        ec_db.commit()

        stats = get_file_outcome_stats(ec_db, ["src/service/payment.py"], lookback_days=60)
        assert stats["contradicted"] == 1  # only the recent one
        assert stats["total"] == 1

    def test_run_extraction_applies_outcome_feedback(self, ec_repo, ec_db, monkeypatch):
        """End-to-end: high-confidence candidate gets penalized when history is bad."""
        from entirecontext.core.decision_extraction import (
            ExtractionWeights,
            run_extraction,
        )

        self._seed_decision_with_outcomes(
            ec_db,
            title="Prior payment decision",
            file_paths=["src/service/payment.py"],
            outcome_types=["contradicted", "contradicted", "contradicted"],
        )

        session = _seed_session(ec_db, ec_repo, session_id="feedback-penalty-e2e")
        _seed_turn(
            ec_db,
            session["id"],
            1,
            "We chose approach A for payments after comparing B",
            files=["src/service/payment.py"],
        )
        llm_response = json.dumps(
            [
                {
                    "title": "Use approach A for payments",
                    "rationale": "chosen approach A over B for predictable rollback behavior",
                    "rejected_alternatives": ["approach B"],
                    "files": ["src/service/payment.py"],
                }
            ]
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda *a, **kw: llm_response,
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction._load_decisions_config",
            lambda _: {"extract_keywords": ["chose"], "extract_sources": ["session"]},
        )

        outcome = run_extraction(
            ec_db,
            session["id"],
            str(ec_repo),
            extraction_weights=ExtractionWeights(
                outcome_feedback_enabled=True,
                outcome_feedback_lookback_days=60,
                contradicted_penalty=0.15,
            ),
        )
        assert outcome.candidates_inserted == 1

        candidates = list_candidates(ec_db, session_id=session["id"])
        assert len(candidates) == 1
        breakdown = candidates[0]["confidence_breakdown"]
        assert breakdown["outcome_feedback"]["applied"] is True
        assert breakdown["outcome_feedback"]["contradicted"] == 3
        assert "final_before_outcome_feedback" in breakdown


class TestExtractionWeightsConfig:
    """Config loading for [decisions.extraction]."""

    def test_defaults_when_missing(self):
        from entirecontext.core.decision_extraction import (
            _DEFAULT_EXTRACTION_WEIGHTS,
            _load_extraction_weights,
        )

        result = _load_extraction_weights(None)
        assert result.outcome_feedback_enabled is True
        assert result.outcome_feedback_lookback_days == 60
        assert result.contradicted_penalty == 0.15
        # Must return a fresh instance (singleton contamination guard).
        assert result is not _DEFAULT_EXTRACTION_WEIGHTS

    def test_override_from_config(self):
        from entirecontext.core.decision_extraction import _load_extraction_weights

        result = _load_extraction_weights(
            {
                "decisions": {
                    "extraction": {
                        "outcome_feedback_enabled": False,
                        "outcome_feedback_lookback_days": 30,
                        "contradicted_penalty": 0.25,
                    }
                }
            }
        )
        assert result.outcome_feedback_enabled is False
        assert result.outcome_feedback_lookback_days == 30
        assert result.contradicted_penalty == 0.25

    def test_invalid_value_raises(self):
        from entirecontext.core.decision_extraction import _load_extraction_weights

        with pytest.raises(ValueError, match="contradicted_penalty"):
            _load_extraction_weights({"decisions": {"extraction": {"contradicted_penalty": "not-a-number"}}})

    def test_negative_penalty_rejected(self):
        """A negative ``contradicted_penalty`` would invert the penalty into a
        confidence boost when contradicted history dominates — that contradicts
        the penalty-only contract of this feature. Config load must refuse."""
        from entirecontext.core.decision_extraction import _load_extraction_weights

        with pytest.raises(ValueError, match=">= 0"):
            _load_extraction_weights({"decisions": {"extraction": {"contradicted_penalty": -0.15}}})

    def test_zero_penalty_accepted(self):
        """Zero is a valid penalty (effectively disables the subtraction without
        disabling the feedback path entirely — useful for breakdown-only mode)."""
        from entirecontext.core.decision_extraction import _load_extraction_weights

        result = _load_extraction_weights({"decisions": {"extraction": {"contradicted_penalty": 0.0}}})
        assert result.contradicted_penalty == 0.0


class TestRunExtractionConfigGuardrails:
    """run_extraction must degrade gracefully on malformed config."""

    def test_malformed_config_falls_back_to_defaults(self, ec_repo, ec_db, monkeypatch):
        """A TOML parse error in [decisions.extraction] must not abort the run.

        The rest of ``run_extraction`` degrades gracefully on expected failures
        (LLM unavailable, parse errors); a config read crash would be a new
        hard-fail path that breaks the graceful-degradation contract.
        """
        from entirecontext.core.decision_extraction import run_extraction

        session = _seed_session(ec_db, ec_repo, session_id="malformed-config-guard")
        _seed_turn(
            ec_db,
            session["id"],
            1,
            "We decided to use approach A after comparing B",
            files=["src/service/payment.py"],
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _p: (_ for _ in ()).throw(RuntimeError("simulated malformed TOML")),
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction._load_decisions_config",
            lambda _: {"extract_keywords": ["decided"], "extract_sources": ["session"]},
        )
        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda *a, **kw: json.dumps(
                [
                    {
                        "title": "Use approach A",
                        "rationale": "A provides better rollback behavior than B in our case",
                        "rejected_alternatives": ["B"],
                        "files": ["src/service/payment.py"],
                    }
                ]
            ),
        )

        # Should not raise — must fall back to defaults and continue.
        outcome = run_extraction(ec_db, session["id"], str(ec_repo))
        assert outcome.candidates_inserted == 1
        assert any(w.startswith("extraction_weights_load:") for w in outcome.warnings)
