"""Map blamed commit SHAs in a file to linked decisions. Read-only."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from typing import Any

_ZERO_SHAS = {"0" * 40, "0" * 64}
_HEADER_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64}) (\d+) (\d+)(?: (\d+))?$")


@dataclass
class BlameAnnotation:
    commit_sha: str
    line_ranges: list[tuple[int, int]]
    decision_id: str
    title: str
    rationale_excerpt: str
    rejected_count: int
    staleness_status: str


def _parse_blame_porcelain(output: str) -> dict[int, str]:
    final_line_to_sha: dict[int, str] = {}
    for line in output.splitlines():
        match = _HEADER_RE.match(line)
        if not match:
            continue
        final_line_to_sha[int(match.group(3))] = match.group(1)
    return final_line_to_sha


def _collapse_ranges(line_numbers: list[int]) -> list[tuple[int, int]]:
    if not line_numbers:
        return []
    sorted_lines = sorted(line_numbers)
    ranges: list[tuple[int, int]] = []
    start = prev = sorted_lines[0]
    for n in sorted_lines[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev))
            start = prev = n
    ranges.append((start, prev))
    return ranges


def _rejected_count(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def _resolve_blamed_sha(repo_path: str, stored_sha: str, blamed_shas: set[str]) -> str | None:
    normalized_sha = stored_sha.lower()
    if normalized_sha in blamed_shas:
        return normalized_sha
    if not re.fullmatch(r"[0-9a-f]{4,63}", normalized_sha):
        return None

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{normalized_sha}^{{commit}}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None

    resolved_sha = result.stdout.strip()
    return resolved_sha if resolved_sha in blamed_shas else None


def annotate_file(
    conn: sqlite3.Connection,
    repo_path: str,
    file: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    cmd = ["git", "blame", "--porcelain"]
    if start_line is not None and end_line is not None:
        cmd += ["-L", f"{start_line},{end_line}"]
    cmd += ["--", file]

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise ValueError(str(exc)) from exc

    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "git blame failed")

    final_line_to_sha = _parse_blame_porcelain(result.stdout)

    sha_to_lines: dict[str, list[int]] = {}
    uncommitted_lines: list[int] = []
    for final_line, sha in final_line_to_sha.items():
        if sha in _ZERO_SHAS:
            uncommitted_lines.append(final_line)
        else:
            sha_to_lines.setdefault(sha, []).append(final_line)

    shas = list(sha_to_lines)
    annotations: list[BlameAnnotation] = []
    annotated_shas: set[str] = set()

    if shas:
        placeholders = ",".join("?" * len(shas))
        prefix_conditions = " OR ".join("? LIKE dc.commit_sha || '%'" for _ in shas)
        rows = conn.execute(
            f"""SELECT dc.commit_sha, d.id, d.title, d.rationale, d.rejected_alternatives, d.staleness_status
            FROM decision_commits dc JOIN decisions d ON d.id = dc.decision_id
            WHERE dc.commit_sha IN ({placeholders})
               OR (length(dc.commit_sha) >= 4 AND ({prefix_conditions}))""",  # noqa: S608
            [*shas, *shas],
        ).fetchall()
        blamed_sha_set = set(shas)
        resolved_links: dict[str, str | None] = {}
        annotation_keys: set[tuple[str, str]] = set()
        for row in rows:
            stored_sha = row["commit_sha"]
            if stored_sha not in resolved_links:
                resolved_links[stored_sha] = _resolve_blamed_sha(repo_path, stored_sha, blamed_sha_set)
            resolved_sha = resolved_links[stored_sha]
            if resolved_sha is None:
                continue
            annotated_shas.add(resolved_sha)
            annotation_key = (resolved_sha, row["id"])
            if annotation_key in annotation_keys:
                continue
            annotation_keys.add(annotation_key)
            rationale = row["rationale"]
            annotations.append(
                BlameAnnotation(
                    commit_sha=resolved_sha,
                    line_ranges=_collapse_ranges(sha_to_lines[resolved_sha]),
                    decision_id=row["id"],
                    title=row["title"],
                    rationale_excerpt=rationale[:200] if rationale else "",
                    rejected_count=_rejected_count(row["rejected_alternatives"]),
                    staleness_status=row["staleness_status"],
                )
            )

    unlinked_lines = [
        line_number
        for sha, line_numbers in sha_to_lines.items()
        if sha not in annotated_shas
        for line_number in line_numbers
    ]

    return {
        "annotations": annotations,
        "unlinked_ranges": _collapse_ranges(unlinked_lines),
        "uncommitted_ranges": _collapse_ranges(uncommitted_lines),
        "annotated_sha_count": len(annotated_shas),
        "total_sha_count": len(sha_to_lines),
    }
