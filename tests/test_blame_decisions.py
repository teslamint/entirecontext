"""Tests for blame_decisions core module."""

from __future__ import annotations

import subprocess

from entirecontext.core.blame_decisions import annotate_file
from entirecontext.core.decisions import create_decision, link_decision_to_commit


def _commit(git_repo, filename: str, content: str, message: str) -> str:
    (git_repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=git_repo, check=True, capture_output=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class TestAnnotateFile:
    def test_happy_single_decision(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "foo.py", "line1\nline2\n", "commit 1")
        _commit(ec_repo, "foo.py", "line1\nline2\nline3\nline4\n", "commit 2")

        decision = create_decision(ec_db, title="Use approach A", rationale="Because reasons")
        link_decision_to_commit(ec_db, decision["id"], sha1)

        result = annotate_file(ec_db, str(ec_repo), "foo.py")

        assert result["total_sha_count"] == 2
        assert result["annotated_sha_count"] == 1
        assert len(result["annotations"]) == 1
        ann = result["annotations"][0]
        assert ann.commit_sha == sha1
        assert ann.decision_id == decision["id"]
        assert ann.title == "Use approach A"
        assert ann.rationale_excerpt == "Because reasons"
        assert ann.line_ranges == [(1, 2)]
        assert ann.rejected_count == 0
        assert ann.staleness_status == "fresh"

    def test_happy_two_decisions_same_sha(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "bar.py", "a\nb\n", "commit 1")

        d1 = create_decision(ec_db, title="Decision one")
        d2 = create_decision(ec_db, title="Decision two")
        link_decision_to_commit(ec_db, d1["id"], sha1)
        link_decision_to_commit(ec_db, d2["id"], sha1)

        result = annotate_file(ec_db, str(ec_repo), "bar.py")

        assert result["total_sha_count"] == 1
        assert result["annotated_sha_count"] == 1
        assert len(result["annotations"]) == 2
        decision_ids = {a.decision_id for a in result["annotations"]}
        assert decision_ids == {d1["id"], d2["id"]}
        for ann in result["annotations"]:
            assert ann.commit_sha == sha1
            assert ann.line_ranges == [(1, 2)]

    def test_no_decision_commits(self, ec_repo, ec_db):
        _commit(ec_repo, "baz.py", "x\ny\n", "commit 1")

        result = annotate_file(ec_db, str(ec_repo), "baz.py")

        assert result["annotations"] == []
        assert result["total_sha_count"] > 0

    def test_uncommitted_lines_excluded(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "qux.py", "line1\nline2\n", "commit 1")
        decision = create_decision(ec_db, title="Decision for qux")
        link_decision_to_commit(ec_db, decision["id"], sha1)

        (ec_repo / "qux.py").write_text("line1\nline2\nline3-uncommitted\n")

        result = annotate_file(ec_db, str(ec_repo), "qux.py")

        assert result["uncommitted_ranges"] == [(3, 3)]
        assert len(result["annotations"]) == 1
        assert result["annotations"][0].commit_sha == sha1
        assert result["annotations"][0].line_ranges == [(1, 2)]

    def test_line_range_filter(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "range.py", "l1\nl2\n", "commit 1")
        sha2 = _commit(ec_repo, "range.py", "l1\nl2\nl3\nl4\n", "commit 2")

        d1 = create_decision(ec_db, title="D1")
        d2 = create_decision(ec_db, title="D2")
        link_decision_to_commit(ec_db, d1["id"], sha1)
        link_decision_to_commit(ec_db, d2["id"], sha2)

        result = annotate_file(ec_db, str(ec_repo), "range.py", start_line=3, end_line=4)

        shas_in_result = {a.commit_sha for a in result["annotations"]}
        assert sha1 not in shas_in_result
        assert sha2 in shas_in_result

    def test_rationale_none_and_truncation(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "rat.py", "a\n", "commit 1")
        d_none = create_decision(ec_db, title="No rationale", rationale=None)
        link_decision_to_commit(ec_db, d_none["id"], sha1)

        result = annotate_file(ec_db, str(ec_repo), "rat.py")
        assert len(result["annotations"]) == 1
        assert result["annotations"][0].rationale_excerpt == ""

        sha2 = _commit(ec_repo, "rat2.py", "b\n", "commit 2")
        long_rationale = "x" * 250
        d_long = create_decision(ec_db, title="Long rationale", rationale=long_rationale)
        link_decision_to_commit(ec_db, d_long["id"], sha2)

        result2 = annotate_file(ec_db, str(ec_repo), "rat2.py")
        assert len(result2["annotations"]) == 1
        assert result2["annotations"][0].rationale_excerpt == "x" * 200

    def test_untracked_file_raises(self, ec_repo, ec_db):
        import pytest

        with pytest.raises(ValueError):
            annotate_file(ec_db, str(ec_repo), "does-not-exist.py")

    def test_superseded_staleness_status(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "stale.py", "a\n", "commit 1")
        decision = create_decision(ec_db, title="Superseded decision")
        link_decision_to_commit(ec_db, decision["id"], sha1)
        ec_db.execute(
            "UPDATE decisions SET staleness_status = 'superseded' WHERE id = ?",
            (decision["id"],),
        )
        ec_db.commit()

        result = annotate_file(ec_db, str(ec_repo), "stale.py")
        assert len(result["annotations"]) == 1
        assert result["annotations"][0].staleness_status == "superseded"
