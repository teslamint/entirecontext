from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from urllib import error, request


_ISSUE_REF = r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?\#(?P<number>\d+)"
_ISSUE_REF_CLAUSE = r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?\#\d+"
_CLOSING_CLAUSE_RE = re.compile(
    rf"(?ix)\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b\s*:?\s*"
    rf"(?P<refs>{_ISSUE_REF_CLAUSE}(?:\s*(?:,|and)\s*{_ISSUE_REF_CLAUSE})*)"
)
_ISSUE_REF_RE = re.compile(_ISSUE_REF)


@dataclass(frozen=True)
class IssueRef:
    repository: str | None
    number: int


def parse_closing_issue_references(message: str) -> list[IssueRef]:
    seen: set[tuple[str | None, int]] = set()
    refs: list[IssueRef] = []

    for match in _CLOSING_CLAUSE_RE.finditer(message):
        for ref_match in _ISSUE_REF_RE.finditer(match.group("refs")):
            repository = ref_match.group("repo")
            number = int(ref_match.group("number"))
            key = (repository, number)
            if key in seen:
                continue
            seen.add(key)
            refs.append(IssueRef(repository=repository, number=number))

    return refs


def _run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def resolve_tagged_commit(ref_name: str) -> str:
    return _run_git("rev-list", "-n", "1", ref_name)


def get_commit_message(commit_sha: str) -> str:
    return _run_git("show", "-s", "--format=%B", commit_sha)


def _close_issue(repository: str, issue_number: int, token: str) -> dict:
    api_url = f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    payload = json.dumps({"state": "closed", "state_reason": "completed"}).encode()
    api_request = request.Request(
        api_url,
        data=payload,
        method="PATCH",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with request.urlopen(api_request) as response:
        return json.loads(response.read().decode())


def filter_same_repo_issues(refs: Iterable[IssueRef], repository: str) -> tuple[list[int], list[IssueRef]]:
    same_repo: list[int] = []
    skipped: list[IssueRef] = []

    for ref in refs:
        if ref.repository is None or ref.repository == repository:
            same_repo.append(ref.number)
            continue
        skipped.append(ref)

    return same_repo, skipped


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    ref_name = os.environ["GITHUB_REF_NAME"]
    token = os.environ["GITHUB_TOKEN"]

    commit_sha = resolve_tagged_commit(ref_name)
    commit_message = get_commit_message(commit_sha)
    refs = parse_closing_issue_references(commit_message)
    issue_numbers, skipped = filter_same_repo_issues(refs, repository)

    print(f"Tagged commit: {commit_sha}")
    if not issue_numbers and not skipped:
        print("No closing issue references found in release commit message.")
        return 0

    if skipped:
        skipped_refs = ", ".join(f"{ref.repository}#{ref.number}" for ref in skipped)
        print(f"Skipping cross-repository issue references: {skipped_refs}")

    if not issue_numbers:
        print("No same-repository issues to close.")
        return 0

    print(f"Closing issues in {repository}: {', '.join(f'#{number}' for number in issue_numbers)}")
    failures: list[str] = []
    for issue_number in issue_numbers:
        try:
            response = _close_issue(repository, issue_number, token)
        except error.HTTPError as exc:
            body = exc.read().decode()
            failures.append(f"#{issue_number}: HTTP {exc.code} {body}")
            continue

        print(f"Closed #{issue_number}: {response['html_url']}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
