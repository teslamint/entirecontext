"""Retroactive decision extraction from git history."""

from __future__ import annotations

import os
import re
import subprocess
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .decision_extraction import (
    SignalBundle,
    ExtractionWeights,
    run_extraction,
)


@dataclass
class ArchaeologyResult:
    commits_scanned: int = 0
    commits_processed: int = 0
    commits_skipped: int = 0
    candidates_generated: int = 0
    warnings: list[str] = field(default_factory=list)


_DIFF_HEADER_RE = re.compile(r'^diff --git "?a/.+ "?b/(.+?)"?$', re.MULTILINE)


def _extract_files_from_patch(patch_text: str) -> list[str]:
    if not patch_text:
        return []
    return list(dict.fromkeys(_DIFF_HEADER_RE.findall(patch_text)))


def _build_signal_bundle(
    commit_sha: str, message: str, patch_text: str, pr_body: str | None
) -> SignalBundle:
    text_blocks = []
    if message:
        text_blocks.append(message)
    if pr_body:
        text_blocks.append(pr_body)
    if patch_text:
        text_blocks.append(patch_text)
    return SignalBundle(
        source_type="archaeology",
        source_id=commit_sha,
        session_id=None,
        checkpoint_id=None,
        assessment_id=None,
        text_blocks=text_blocks,
        files=_extract_files_from_patch(patch_text),
    )


def _is_processed(conn: sqlite3.Connection, commit_sha: str) -> bool:
    row = conn.execute("SELECT 1 FROM archaeology_processed WHERE commit_sha = ?", (commit_sha,)).fetchone()
    return row is not None


def _mark_processed(conn: sqlite3.Connection, commit_sha: str, candidate_count: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO archaeology_processed (commit_sha, candidate_count) VALUES (?, ?)",
        (commit_sha, candidate_count),
    )


def _looks_like_date(ref: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", ref))


def _stream_commits(
    repo_path: str,
    since: str | None,
    until: str | None,
    limit: int,
    warnings: list[str] | None = None,
) -> Iterator[tuple[str, str, str]]:
    """Yield (sha, message, patch_text) for commits in the given range.

    Note: `git log -n limit --reverse` selects the *most recent* `limit`
    commits and then reverses their order for output — it does not walk
    from the oldest commit forward. Re-running with the same `limit` can
    never advance into older history; callers must increase `limit` (or
    narrow `since`/`until`) to reach commits beyond the most recent window.
    """
    # %x1e (record separator) before each commit disambiguates patch content
    # from the next commit's header. Split on \x1e, then split each record
    # on \x00 with maxsplit=2 to get (sha, message, patch). %B (not %s) is
    # used so the full commit body reaches the bundle, not just the subject.
    cmd = ["git", "log", "--patch", "--reverse", "--format=%x1e%H%x00%B%x00"]

    since_is_date = since is not None and _looks_like_date(since)
    until_is_date = until is not None and _looks_like_date(until)
    since_is_ref = since is not None and not since_is_date
    until_is_ref = until is not None and not until_is_date

    if since_is_ref and until_is_ref:
        cmd.append(f"{since}..{until}")
    elif since_is_ref:
        cmd.append(f"{since}..HEAD")
    elif until_is_ref:
        assert until is not None  # narrowing for mypy
        cmd.append(until)

    if since_is_date:
        cmd.append(f"--since={since}")
    if until_is_date:
        cmd.append(f"--until={until}")

    if limit is not None and limit > 0:
        cmd.extend(["-n", str(limit)])

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        errors="surrogateescape",
    )
    if result.returncode != 0:
        msg = f"git log failed (exit {result.returncode}): {result.stderr.strip()}"
        if warnings is not None:
            warnings.append(msg)
        return

    records = result.stdout.split("\x1e")
    for record in records:
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00", maxsplit=2)
        if len(parts) < 2:
            continue
        sha = parts[0].strip()
        message = parts[1].strip()
        patch_text = parts[2] if len(parts) > 2 else ""
        if len(sha) == 40:
            yield sha, message, patch_text


def _get_github_token() -> str | None:
    token = os.environ.get("EC_GITHUB_TOKEN")
    if token:
        return token.strip()
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _fetch_pr_body(commit_sha: str, repo_path: str, token: str) -> str | None:
    remote_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if remote_url.returncode != 0:
        return None
    url = remote_url.stdout.strip()
    if "github.com" not in url:
        return None
    match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        return None
    owner_repo = match.group(1)

    env = {**os.environ, "GH_TOKEN": token} if token else None
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner_repo}/commits/{commit_sha}/pulls",
                "--jq",
                ".[0].body // empty",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def archaeologize(
    conn: sqlite3.Connection,
    repo_path: str,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    pr_bodies: bool = False,
    dry_run: bool = False,
    batch_size: int = 10,
    extraction_weights: ExtractionWeights | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> ArchaeologyResult:
    result = ArchaeologyResult()
    token = None
    if pr_bodies:
        token = _get_github_token()
        if not token:
            result.warnings.append(
                "No GitHub token found. Set EC_GITHUB_TOKEN or install gh CLI. Proceeding without PR bodies."
            )
            pr_bodies = False

    commits = list(_stream_commits(repo_path, since, until, limit, warnings=result.warnings))
    result.commits_scanned = len(commits)

    try:
        already_processed = sum(1 for sha, _, _ in commits if _is_processed(conn, sha))
    except sqlite3.OperationalError:
        # archaeology_processed table doesn't exist yet (e.g. dry-run before
        # migration has ever run) — nothing has been processed.
        already_processed = 0
    to_process = result.commits_scanned - already_processed

    if dry_run:
        result.commits_skipped = already_processed
        est_tokens_low = to_process * 2500
        est_tokens_high = to_process * 3000
        if progress_callback:
            msg = (
                f"Found {result.commits_scanned} commits, "
                f"{already_processed} already processed, "
                f"{to_process} to process.\n"
                f"Estimated token cost: ~{est_tokens_low:,}-{est_tokens_high:,} tokens"
            )
            # `git log -n limit --reverse` selects the most recent `limit`
            # commits, not the oldest `limit` — re-runs at the same limit
            # can never reach older history. Surface this when the scan
            # looks capped by the limit rather than by actual history size.
            if limit and result.commits_scanned >= limit:
                msg += (
                    f"\nNote: --limit {limit} may be capping results to the most "
                    "recent commits; increase --limit to reach older history."
                )
            progress_callback(msg)
        return result

    batch: list[tuple[str, str, str]] = []
    try:
        for sha, message, patch_text in commits:
            if _is_processed(conn, sha):
                result.commits_skipped += 1
                continue
            batch.append((sha, message, patch_text))
            if len(batch) >= batch_size:
                _process_batch(
                    conn,
                    repo_path,
                    batch,
                    result,
                    pr_bodies=pr_bodies,
                    token=token,
                    extraction_weights=extraction_weights,
                    progress_callback=progress_callback,
                )
                batch = []

        if batch:
            _process_batch(
                conn,
                repo_path,
                batch,
                result,
                pr_bodies=pr_bodies,
                token=token,
                extraction_weights=extraction_weights,
                progress_callback=progress_callback,
            )
    except KeyboardInterrupt:
        # Commits already marked processed (via _mark_processed, autocommit)
        # are durable. Do NOT re-run _process_batch here — the interrupt may
        # have landed mid-batch, and re-processing would duplicate work
        # already committed. A re-run of archaeologize resumes via dedup.
        result.warnings.append(
            f"Interrupted by user after {result.commits_processed} commits. Progress saved — re-run to resume."
        )

    return result


def _process_batch(
    conn: sqlite3.Connection,
    repo_path: str,
    batch: list[tuple[str, str, str]],
    result: ArchaeologyResult,
    *,
    pr_bodies: bool,
    token: str | None,
    extraction_weights: ExtractionWeights | None,
    progress_callback: Callable[[str], None] | None,
) -> None:
    for sha, message, patch_text in batch:
        pr_body = None
        if pr_bodies and token:
            pr_body = _fetch_pr_body(sha, repo_path, token)
            if pr_body is None:
                result.warnings.append(f"commit {sha[:12]}: PR body fetch returned empty (rate limit, permissions, or no associated PR)")

        bundle = _build_signal_bundle(sha, message, patch_text, pr_body)
        try:
            outcome = run_extraction(
                conn,
                session_id=None,
                repo_path=repo_path,
                bundles=[bundle],
                extraction_weights=extraction_weights,
            )
            if outcome.parsed_ok or outcome.candidates_inserted > 0:
                _mark_processed(conn, sha, outcome.candidates_inserted)
                result.commits_processed += 1
                result.candidates_generated += outcome.candidates_inserted
            else:
                result.warnings.append(f"commit {sha[:12]}: extraction did not parse; will retry next run")
            if outcome.warnings:
                result.warnings.extend(outcome.warnings)
        except Exception as exc:
            result.warnings.append(f"commit {sha[:12]}: {exc}")

    if progress_callback:
        progress_callback(
            f"Processed {result.commits_processed}/{result.commits_scanned - result.commits_skipped} commits, "
            f"{result.candidates_generated} candidates"
        )
