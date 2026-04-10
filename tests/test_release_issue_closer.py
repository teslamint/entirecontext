from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_release_issue_closer_module():
    module_path = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "close_release_issues.py"
    spec = importlib.util.spec_from_file_location("close_release_issues", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = _load_release_issue_closer_module()


class TestParseClosingIssueReferences:
    def test_extracts_release_closing_line(self):
        message = """
release: v0.1.1

Closes #32, #33, #34, #35, #36, #37
"""
        refs = module.parse_closing_issue_references(message)
        assert [ref.number for ref in refs] == [32, 33, 34, 35, 36, 37]

    def test_ignores_non_closing_references(self):
        message = """
- fix(db): add context manager (#32)
- build(metadata): add project URLs (#36)
"""
        assert module.parse_closing_issue_references(message) == []

    def test_supports_multiple_closing_clauses(self):
        message = "Fixes #10 and #11. Resolves #12"
        refs = module.parse_closing_issue_references(message)
        assert [ref.number for ref in refs] == [10, 11, 12]

    def test_deduplicates_repeated_references(self):
        message = "Closes #10, #10 and #11"
        refs = module.parse_closing_issue_references(message)
        assert [ref.number for ref in refs] == [10, 11]


class TestFilterSameRepoIssues:
    def test_keeps_same_repo_and_local_refs(self):
        refs = [
            module.IssueRef(repository=None, number=37),
            module.IssueRef(repository="teslamint/entirecontext", number=38),
            module.IssueRef(repository="octo/repo", number=10),
        ]

        issue_numbers, skipped = module.filter_same_repo_issues(refs, "teslamint/entirecontext")

        assert issue_numbers == [37, 38]
        assert skipped == [module.IssueRef(repository="octo/repo", number=10)]
