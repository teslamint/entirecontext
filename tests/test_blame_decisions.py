"""Tests for blame_decisions core module."""

from __future__ import annotations

import re
import sqlite3
import subprocess

from entirecontext.core.blame_decisions import annotate_file
from entirecontext.core.decisions import create_decision, link_decision_to_commit


def _commit(git_repo, filename: str, content: str, message: str) -> str:
    (git_repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=git_repo, check=True, capture_output=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _annotate_high_distinct_sha_file(ec_repo, ec_db, monkeypatch, traced_statements=None):
    shas = [f"{index:08x}{index:032x}" for index in range(1, 1201)]
    exact_decision = create_decision(ec_db, title="Exact SHA decision")
    abbreviated_decision = create_decision(ec_db, title="Abbreviated SHA decision")
    link_decision_to_commit(ec_db, exact_decision["id"], shas[0])
    link_decision_to_commit(ec_db, abbreviated_decision["id"], shas[-1][:8])
    blame_output = "".join(
        f"{sha} {line_number} {line_number} 1\n\tline {line_number}\n"
        for line_number, sha in enumerate(shas, start=1)
    )

    def fake_run(command, **kwargs):
        if command[:3] == ["git", "blame", "--porcelain"]:
            return subprocess.CompletedProcess(command, 0, blame_output, "")
        if command[:3] == ["git", "rev-parse", "--verify"]:
            assert command[3] == f"{shas[-1][:8]}^{{commit}}"
            return subprocess.CompletedProcess(command, 0, f"{shas[-1]}\n", "")
        raise AssertionError(f"Unexpected subprocess command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    previous_limit = ec_db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 1000)
    if traced_statements is not None:
        ec_db.set_trace_callback(traced_statements.append)
    try:
        result = annotate_file(ec_db, str(ec_repo), "large-history.py")
    finally:
        ec_db.set_trace_callback(None)
        ec_db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, previous_limit)

    return result, shas, exact_decision, abbreviated_decision


class TestAnnotateFile:
    def test_high_distinct_sha_count_survives_expression_depth_limit(
        self, ec_repo, ec_db, monkeypatch
    ):
        result, shas, exact_decision, abbreviated_decision = _annotate_high_distinct_sha_file(
            ec_repo, ec_db, monkeypatch
        )

        assert result["total_sha_count"] == 1200
        assert result["annotated_sha_count"] == 2
        assert {(annotation.commit_sha, annotation.decision_id) for annotation in result["annotations"]} == {
            (shas[0], exact_decision["id"]),
            (shas[-1], abbreviated_decision["id"]),
        }

    def test_high_distinct_sha_query_count_is_bounded(self, ec_repo, ec_db, monkeypatch):
        traced_statements = []

        _annotate_high_distinct_sha_file(ec_repo, ec_db, monkeypatch, traced_statements)

        candidate_queries = [
            statement
            for statement in traced_statements
            if "FROM decision_commits dc JOIN decisions d" in statement
        ]
        exact_queries = [
            statement for statement in candidate_queries if "WHERE dc.commit_sha IN (" in statement
        ]
        abbreviated_queries = [
            statement for statement in candidate_queries if "length(dc.commit_sha) >= 4" in statement
        ]

        assert len(exact_queries) == 3
        assert len(abbreviated_queries) == 1
        for statement in exact_queries:
            match = re.search(r"WHERE dc\.commit_sha IN \((.*?)\)", statement, re.DOTALL)
            assert match is not None
            assert len(match.group(1).split(",")) <= 400

    def test_unrelated_abbreviated_links_do_not_invoke_git_resolution(
        self, ec_repo, ec_db, monkeypatch
    ):
        full_sha = "abcdef0123" * 4
        relevant_abbreviation = full_sha[:8]
        decision = create_decision(ec_db, title="Relevant abbreviated SHA decision")
        commit_links = [relevant_abbreviation, *(f"b{index:07x}" for index in range(1000))]
        ec_db.executemany(
            "INSERT INTO decision_commits (decision_id, commit_sha) VALUES (?, ?)",
            ((decision["id"], commit_sha) for commit_sha in commit_links),
        )
        ec_db.commit()
        blame_output = f"{full_sha} 1 1 1\n\tline1\n"
        resolved_arguments = []

        def fake_run(command, **kwargs):
            if command[:3] == ["git", "blame", "--porcelain"]:
                return subprocess.CompletedProcess(command, 0, blame_output, "")
            if command[:3] == ["git", "rev-parse", "--verify"]:
                resolved_arguments.append(command[3])
                if command[3] == f"{relevant_abbreviation}^{{commit}}":
                    return subprocess.CompletedProcess(command, 0, f"{full_sha}\n", "")
                return subprocess.CompletedProcess(command, 1, "", "unknown revision")
            raise AssertionError(f"Unexpected subprocess command: {command}")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = annotate_file(ec_db, str(ec_repo), "abbreviated-candidates.py")

        assert result["annotated_sha_count"] == 1
        assert resolved_arguments == [f"{relevant_abbreviation}^{{commit}}"]

    def test_non_utf8_file_is_parsed_without_decode_error(self, ec_repo, ec_db):
        (ec_repo / "binary.dat").write_bytes(b"\xff\n")
        subprocess.run(["git", "add", "binary.dat"], cwd=ec_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add non-utf8 file"],
            cwd=ec_repo,
            check=True,
            capture_output=True,
        )

        result = annotate_file(ec_db, str(ec_repo), "binary.dat")

        assert result["total_sha_count"] == 1
        assert result["annotations"] == []

    def test_sha256_porcelain_header_is_annotated(self, ec_repo, ec_db, monkeypatch):
        sha256 = "a" * 64
        decision = create_decision(ec_db, title="SHA-256 decision")
        link_decision_to_commit(ec_db, decision["id"], sha256)
        blame_output = f"{sha256} 1 1 1\n\tline1\n"

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, blame_output, ""),
        )

        result = annotate_file(ec_db, str(ec_repo), "sha256.py")

        assert result["total_sha_count"] == 1
        assert result["annotated_sha_count"] == 1
        assert result["annotations"][0].commit_sha == sha256
        assert result["annotations"][0].decision_id == decision["id"]

    def test_sha256_zero_header_is_uncommitted(self, ec_repo, ec_db, monkeypatch):
        zero_sha256 = "0" * 64
        blame_output = f"{zero_sha256} 1 7 1\n\tline7\n"

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, blame_output, ""),
        )

        result = annotate_file(ec_db, str(ec_repo), "sha256.py")

        assert result["total_sha_count"] == 0
        assert result["annotated_sha_count"] == 0
        assert result["uncommitted_ranges"] == [(7, 7)]

    def test_abbreviated_commit_link_resolves_to_full_blame_sha(self, ec_repo, ec_db):
        full_sha = _commit(ec_repo, "abbrev.py", "line1\n", "commit with abbreviated link")
        decision = create_decision(ec_db, title="Abbreviated SHA decision")
        link_decision_to_commit(ec_db, decision["id"], full_sha[:8])

        result = annotate_file(ec_db, str(ec_repo), "abbrev.py")

        assert result["annotated_sha_count"] == 1
        assert result["annotations"][0].commit_sha == full_sha
        assert result["annotations"][0].decision_id == decision["id"]

    def test_uppercase_abbreviated_commit_link_is_normalized(self, ec_repo, ec_db):
        full_sha = _commit(ec_repo, "uppercase.py", "line1\n", "commit with uppercase link")
        decision = create_decision(ec_db, title="Uppercase SHA decision")
        link_decision_to_commit(ec_db, decision["id"], full_sha[:8].upper())

        result = annotate_file(ec_db, str(ec_repo), "uppercase.py")

        assert result["annotated_sha_count"] == 1
        assert result["annotations"][0].commit_sha == full_sha
        assert result["annotations"][0].decision_id == decision["id"]

    def test_uppercase_full_commit_link_is_normalized(self, ec_repo, ec_db):
        full_sha = _commit(ec_repo, "uppercase-full.py", "line1\n", "commit with uppercase full link")
        decision = create_decision(ec_db, title="Uppercase full SHA decision")
        link_decision_to_commit(ec_db, decision["id"], full_sha.upper())

        result = annotate_file(ec_db, str(ec_repo), "uppercase-full.py")

        assert result["annotated_sha_count"] == 1
        assert result["annotations"][0].commit_sha == full_sha
        assert result["annotations"][0].decision_id == decision["id"]

    def test_mixed_case_full_commit_link_is_normalized(self, ec_repo, ec_db, monkeypatch):
        full_sha = "abcdef0123" * 4
        mixed_case_sha = "AbCdEf0123" * 4
        decision = create_decision(ec_db, title="Mixed-case full SHA decision")
        link_decision_to_commit(ec_db, decision["id"], mixed_case_sha)
        blame_output = f"{full_sha} 1 1 1\n\tline1\n"

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, blame_output, ""),
        )

        result = annotate_file(ec_db, str(ec_repo), "mixed-case-full.py")

        assert result["annotated_sha_count"] == 1
        assert result["annotations"][0].commit_sha == full_sha
        assert result["annotations"][0].decision_id == decision["id"]

    def test_equivalent_full_and_abbreviated_links_are_deduplicated(self, ec_repo, ec_db):
        full_sha = _commit(ec_repo, "duplicate.py", "line1\n", "commit with duplicate links")
        decision = create_decision(ec_db, title="One decision, two link forms")
        link_decision_to_commit(ec_db, decision["id"], full_sha)
        link_decision_to_commit(ec_db, decision["id"], full_sha[:8])

        result = annotate_file(ec_db, str(ec_repo), "duplicate.py")

        assert result["annotated_sha_count"] == 1
        assert len(result["annotations"]) == 1
        assert result["annotations"][0].decision_id == decision["id"]

    def test_happy_single_decision(self, ec_repo, ec_db):
        sha1 = _commit(ec_repo, "foo.py", "line1\nline2\n", "commit 1")
        _commit(ec_repo, "foo.py", "line1\nline2\nline3\nline4\n", "commit 2")

        decision = create_decision(ec_db, title="Use approach A", rationale="Because reasons")
        link_decision_to_commit(ec_db, decision["id"], sha1)

        result = annotate_file(ec_db, str(ec_repo), "foo.py")

        assert result["total_sha_count"] == 2
        assert result["annotated_sha_count"] == 1
        assert result["unlinked_ranges"] == [(3, 4)]
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
