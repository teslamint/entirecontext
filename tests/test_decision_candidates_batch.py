"""Tests for confirm_candidates_batch() — filtered batch promotion with dry-run distribution."""

from __future__ import annotations

import pytest

from entirecontext.core.decision_candidates import (
    confirm_candidate,
    confirm_candidates_batch,
    get_candidate,
)
from entirecontext.core.decision_extraction import (
    CandidateDraft,
    DedupResult,
    compute_dedup_key,
    persist_candidate,
    score_confidence,
)


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


class TestHappyPath:
    def test_all_eligible_archaeology_candidates_promoted_with_commit_links(self, ec_repo, ec_db):
        source_ids = [_hex_sha(i) for i in (1, 2, 3)]
        for sid in source_ids:
            _seed_candidate(ec_db, source_type="archaeology", source_id=sid, confidence=0.9)

        result = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)

        assert result["failed"] == []
        assert len(result["confirmed"]) == 3
        assert result["skipped_below_threshold"] == 0

        for sid in source_ids:
            row = ec_db.execute(
                "SELECT decision_id FROM decision_commits WHERE commit_sha = ?", (sid,)
            ).fetchone()
            assert row is not None
            assert row["decision_id"] in result["confirmed"]

    def test_dry_run_returns_distribution_without_mutating(self, ec_repo, ec_db):
        confidences = [0.05, 0.15, 0.25, 0.95]
        ids = [
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i + 1), confidence=c)
            for i, c in enumerate(confidences)
        ]

        result = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.2, dry_run=True
        )

        assert result["dry_run"] is True
        assert result["total_pending"] == 4
        assert result["eligible"] == 2
        assert result["distribution"] == {
            "0.0-0.1": 1,
            "0.1-0.2": 1,
            "0.2-0.3": 1,
            "0.9-1.0": 1,
        }

        for cid in ids:
            row = get_candidate(ec_db, cid)
            assert row["review_status"] == "pending"


class TestEdgeCases:
    @pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_min_confidence_is_rejected_without_mutation(
        self, ec_repo, ec_db, threshold
    ):
        candidate_id = _seed_candidate(
            ec_db,
            source_type="archaeology",
            source_id=_hex_sha(99),
            confidence=0.9,
        )

        with pytest.raises(ValueError, match="finite"):
            confirm_candidates_batch(
                ec_db,
                source_type="archaeology",
                min_confidence=threshold,
            )

        assert get_candidate(ec_db, candidate_id)["review_status"] == "pending"

    def test_confidence_equal_to_min_confidence_is_confirmed(self, ec_repo, ec_db):
        cid = _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.5)

        result = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)

        assert cid not in result["failed"]
        assert len(result["confirmed"]) == 1

    def test_source_type_filter_leaves_other_types_untouched(self, ec_repo, ec_db):
        arch_id = _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.9)
        assessment_id = _seed_candidate(
            ec_db, source_type="assessment", source_id="assessment-1", confidence=0.9
        )
        checkpoint_id = _seed_candidate(
            ec_db, source_type="checkpoint", source_id="checkpoint-1", confidence=0.9
        )

        result = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.0)

        assert len(result["confirmed"]) == 1
        arch_row = get_candidate(ec_db, arch_id)
        assert arch_row["review_status"] == "confirmed"

        for cid in (assessment_id, checkpoint_id):
            row = get_candidate(ec_db, cid)
            assert row["review_status"] == "pending"

    def test_pagination_promotes_all_eligible_candidates(self, ec_repo, ec_db):
        ids = [
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)
            for i in range(1, 13)
        ]

        result = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, page_size=5
        )

        assert result["failed"] == []
        assert sorted(result["confirmed"]) == sorted(result["confirmed"])
        assert len(result["confirmed"]) == 12
        for cid in ids:
            row = get_candidate(ec_db, cid)
            assert row["review_status"] == "confirmed"


class TestErrorHandling:
    def test_single_candidate_failure_rolls_back_and_batch_continues(self, ec_repo, ec_db, monkeypatch):
        ids = [
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)
            for i in (1, 2, 3)
        ]
        fail_id = ids[1]
        fail_title = get_candidate(ec_db, fail_id)["title"]

        from entirecontext.core import decisions as decisions_module

        original_create_decision = decisions_module.create_decision

        def flaky_create_decision(conn, **kwargs):
            if kwargs.get("title") == fail_title:
                raise RuntimeError("simulated create_decision failure")
            return original_create_decision(conn, **kwargs)

        monkeypatch.setattr(decisions_module, "create_decision", flaky_create_decision)

        result = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)

        assert result["failed"] == [fail_id]
        assert len(result["confirmed"]) == 2

        row = get_candidate(ec_db, fail_id)
        assert row["review_status"] == "pending"
        assert row["promoted_decision_id"] is None

    def test_already_confirmed_candidate_lands_in_failed_and_batch_continues(
        self, ec_repo, ec_db, monkeypatch
    ):
        pre_id = _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.9)
        confirm_candidate(ec_db, pre_id, reviewer="pre")
        pre_row = get_candidate(ec_db, pre_id)
        assert pre_row["review_status"] == "confirmed"

        other_id = _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(2), confidence=0.9)

        from entirecontext.core import decision_candidates as dc_module

        original_list_candidates = dc_module.list_candidates
        calls = {"n": 0}

        def fake_list_candidates(conn, **kwargs):
            calls["n"] += 1
            real_page = original_list_candidates(conn, **kwargs)
            if calls["n"] == 1:
                return [pre_row] + real_page
            return real_page

        monkeypatch.setattr(dc_module, "list_candidates", fake_list_candidates)

        result = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)

        assert pre_id in result["failed"]
        assert len(result["confirmed"]) == 1

        other_row = get_candidate(ec_db, other_id)
        assert other_row["review_status"] == "confirmed"

    def test_small_page_size_with_failures_does_not_starve_low_confidence_candidate(
        self, ec_repo, ec_db, monkeypatch
    ):
        fail_ids = [
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)
            for i in (1, 2, 3)
        ]
        fail_titles = {get_candidate(ec_db, cid)["title"] for cid in fail_ids}
        low_id = _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(4), confidence=0.5)

        from entirecontext.core import decisions as decisions_module

        original_create_decision = decisions_module.create_decision

        def flaky_create_decision(conn, **kwargs):
            if kwargs.get("title") in fail_titles:
                raise RuntimeError("simulated create_decision failure")
            return original_create_decision(conn, **kwargs)

        monkeypatch.setattr(decisions_module, "create_decision", flaky_create_decision)

        result = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, page_size=2
        )

        assert sorted(result["failed"]) == sorted(fail_ids)
        assert len(result["confirmed"]) == 1
        assert len(result["confirmed"]) + len(result["failed"]) == 4

        low_row = get_candidate(ec_db, low_id)
        assert low_row["review_status"] == "confirmed"
        assert low_row["promoted_decision_id"] in result["confirmed"]

        for cid in fail_ids:
            row = get_candidate(ec_db, cid)
            assert row["review_status"] == "pending"
            assert row["promoted_decision_id"] is None


class TestRerunSemantics:
    def test_second_batch_call_promotes_previously_failed_candidate_without_touching_confirmed(
        self, ec_repo, ec_db, monkeypatch
    ):
        ids = [
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)
            for i in (1, 2, 3)
        ]
        fail_id = ids[1]
        fail_title = get_candidate(ec_db, fail_id)["title"]

        from entirecontext.core import decisions as decisions_module

        original_create_decision = decisions_module.create_decision

        def flaky_create_decision(conn, **kwargs):
            if kwargs.get("title") == fail_title:
                raise RuntimeError("simulated create_decision failure")
            return original_create_decision(conn, **kwargs)

        monkeypatch.setattr(decisions_module, "create_decision", flaky_create_decision)

        result1 = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)
        assert result1["failed"] == [fail_id]
        assert len(result1["confirmed"]) == 2

        stable_ids = [ids[0], ids[2]]
        promoted_before = {
            cid: (
                get_candidate(ec_db, cid)["promoted_decision_id"],
                get_candidate(ec_db, cid)["reviewed_at"],
            )
            for cid in stable_ids
        }

        monkeypatch.setattr(decisions_module, "create_decision", original_create_decision)

        result2 = confirm_candidates_batch(ec_db, source_type="archaeology", min_confidence=0.5)

        assert result2["failed"] == []
        assert len(result2["confirmed"]) == 1

        fail_row_after = get_candidate(ec_db, fail_id)
        assert fail_row_after["review_status"] == "confirmed"
        assert fail_row_after["promoted_decision_id"] in result2["confirmed"]

        for cid in stable_ids:
            row_after = get_candidate(ec_db, cid)
            decision_id_before, reviewed_at_before = promoted_before[cid]
            assert row_after["promoted_decision_id"] == decision_id_before
            assert row_after["reviewed_at"] == reviewed_at_before


class TestEmbeddingIntegration:
    def test_embedding_called_once_for_batch_when_auto_embed_and_repo_path(
        self, ec_repo, ec_db, monkeypatch
    ):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda path=None: {"decisions": {"auto_embed": True}},
        )
        calls = []
        monkeypatch.setattr(
            "entirecontext.core.embedding.generate_embeddings",
            lambda conn, repo_path, **kwargs: calls.append((repo_path, kwargs)) or 0,
        )

        for i in (1, 2, 3):
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)

        result = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, repo_path=str(ec_repo)
        )

        assert len(result["confirmed"]) == 3
        assert len(calls) == 1
        assert calls[0][0] == str(ec_repo)
        assert calls[0][1].get("decisions_only") is True

    def test_embedding_not_called_on_dry_run(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda path=None: {"decisions": {"auto_embed": True}},
        )
        calls = []
        monkeypatch.setattr(
            "entirecontext.core.embedding.generate_embeddings",
            lambda conn, repo_path, **kwargs: calls.append(1) or 0,
        )

        _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.9)

        confirm_candidates_batch(
            ec_db,
            source_type="archaeology",
            min_confidence=0.5,
            dry_run=True,
            repo_path=str(ec_repo),
        )

        assert calls == []

    def test_embedding_not_called_without_repo_path(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda path=None: {"decisions": {"auto_embed": True}},
        )
        calls = []
        monkeypatch.setattr(
            "entirecontext.core.embedding.generate_embeddings",
            lambda conn, repo_path, **kwargs: calls.append(1) or 0,
        )

        _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.9)

        confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, repo_path=None
        )

        assert calls == []

    def test_embedding_failure_during_batch_is_swallowed(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda path=None: {"decisions": {"auto_embed": True}},
        )

        def boom(conn, repo_path, **kwargs):
            raise RuntimeError("simulated embedding failure")

        monkeypatch.setattr("entirecontext.core.embedding.generate_embeddings", boom)

        for i in (1, 2, 3):
            _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(i), confidence=0.9)

        result = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, repo_path=str(ec_repo)
        )

        assert len(result["confirmed"]) == 3
        assert result["failed"] == []

    def test_embedding_called_once_per_confirming_batch_invocation(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda path=None: {"decisions": {"auto_embed": True}},
        )
        calls = []
        monkeypatch.setattr(
            "entirecontext.core.embedding.generate_embeddings",
            lambda conn, repo_path, **kwargs: calls.append(1) or 0,
        )

        _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(1), confidence=0.9)
        result1 = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, repo_path=str(ec_repo)
        )
        assert len(result1["confirmed"]) == 1
        assert len(calls) == 1

        _seed_candidate(ec_db, source_type="archaeology", source_id=_hex_sha(2), confidence=0.9)
        result2 = confirm_candidates_batch(
            ec_db, source_type="archaeology", min_confidence=0.5, repo_path=str(ec_repo)
        )
        assert len(result2["confirmed"]) == 1
        assert len(calls) == 2
