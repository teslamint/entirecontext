"""Retroactive decision extraction from git history."""

from __future__ import annotations

import io
import os
import re
import subprocess
import sqlite3
import threading
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


_GIT_OCTAL_RE = re.compile(r"\\([0-7]{3})")


def _decode_git_quoted_path(path: str) -> str:
    if "\\" not in path:
        return path
    decoded = _GIT_OCTAL_RE.sub(lambda m: chr(int(m.group(1), 8)), path)
    try:
        return decoded.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return decoded


def _is_github_remote(url: str) -> bool:
    if url.startswith("git@"):
        host = url.split("@", 1)[1].split(":", 1)[0]
        return host == "github.com"
    for prefix in ("https://", "http://", "ssh://"):
        if url.startswith(prefix):
            host = url[len(prefix):].split("/", 1)[0].split("@")[-1].split(":")[0]
            return host == "github.com"
    return False


def _extract_files_from_patch(patch_text: str) -> list[str]:
    if not patch_text:
        return []

    def normalize(path: str, prefix: str | None = None) -> str | None:
        path = path.strip()
        if len(path) >= 2 and path[0] == path[-1] == '"':
            path = path[1:-1]
        if prefix is not None:
            marker = f"{prefix}/"
            if not path.startswith(marker):
                return None
            path = path[len(marker):]
        return _decode_git_quoted_path(path)

    def header_fallback(payload: str) -> str | None:
        for separator in re.finditer(r' (?="?b/)', payload):
            source = normalize(payload[:separator.start()], "a")
            destination = normalize(payload[separator.end():], "b")
            if source is not None and source == destination:
                return destination
        return None

    files: list[str] = []
    records = re.split(r"(?m)^diff --git ", patch_text)[1:]
    for record in records:
        header, _, body = record.partition("\n")
        path: str | None = None

        rename = re.search(r"(?m)^rename to (.+)$", body)
        if rename:
            path = normalize(rename.group(1))
        else:
            destination = re.search(r"(?m)^\+\+\+ (.+)$", body)
            if destination and destination.group(1).strip() != "/dev/null":
                path = normalize(destination.group(1), "b")
            else:
                source = re.search(r"(?m)^--- (.+)$", body)
                if source and source.group(1).strip() != "/dev/null":
                    path = normalize(source.group(1), "a")

        if path is None:
            path = header_fallback(header)
        if path is not None and path not in files:
            files.append(path)

    return files


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


@dataclass(frozen=True)
class _ProcessingState:
    patch_processed: bool = False
    pr_body_processed: bool = False
    candidate_count: int = 0


def _get_processing_state(conn: sqlite3.Connection, commit_sha: str) -> _ProcessingState:
    try:
        row = conn.execute(
            "SELECT candidate_count, pr_body_processed "
            "FROM archaeology_processed WHERE commit_sha = ?",
            (commit_sha,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such column: pr_body_processed" not in str(exc):
            raise
        row = conn.execute(
            "SELECT candidate_count FROM archaeology_processed WHERE commit_sha = ?",
            (commit_sha,),
        ).fetchone()
        return _ProcessingState(bool(row), False, row[0] if row else 0)
    return _ProcessingState(bool(row), bool(row[1]) if row else False, row[0] if row else 0)


def _is_processed(conn: sqlite3.Connection, commit_sha: str) -> bool:
    return _get_processing_state(conn, commit_sha).patch_processed


def _mark_processed(
    conn: sqlite3.Connection,
    commit_sha: str,
    candidate_count: int,
    *,
    pr_body_processed: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO archaeology_processed
            (commit_sha, candidate_count, pr_body_processed)
        VALUES (?, ?, ?)
        ON CONFLICT(commit_sha) DO UPDATE SET
            candidate_count = archaeology_processed.candidate_count + excluded.candidate_count,
            pr_body_processed = MAX(
                archaeology_processed.pr_body_processed,
                excluded.pr_body_processed
            )
        """,
        (commit_sha, candidate_count, int(pr_body_processed)),
    )


def _looks_like_date(ref: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", ref))


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
    cmd = [
        "git", "log", "--patch", "--reverse", "--no-merges",
        "--no-color", "--src-prefix=a/", "--dst-prefix=b/",
        "--format=%x1e%H%x00%B%x00",
    ]

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

    proc = subprocess.Popen(
        cmd,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="surrogateescape",
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    stdout = proc.stdout
    stderr = proc.stderr

    stderr_buf = io.StringIO()
    stderr_thread = threading.Thread(
        target=lambda: stderr_buf.write(stderr.read()),
        daemon=True,
    )
    stderr_thread.start()

    try:
        buf = ""
        for line in stdout:
            buf += line
            while "\x1e" in buf:
                idx = buf.index("\x1e")
                record = buf[:idx].strip()
                buf = buf[idx + 1:]
                if not record:
                    continue
                parts = record.split("\x00", maxsplit=2)
                if len(parts) < 2:
                    continue
                sha = parts[0].strip()
                message = parts[1].strip()
                patch_text = parts[2] if len(parts) > 2 else ""
                if len(sha) in (40, 64):
                    yield sha, message, patch_text

        # Process trailing buffer after EOF
        record = buf.strip()
        if record:
            parts = record.split("\x00", maxsplit=2)
            if len(parts) >= 2:
                sha = parts[0].strip()
                message = parts[1].strip()
                patch_text = parts[2] if len(parts) > 2 else ""
                if len(sha) in (40, 64):
                    yield sha, message, patch_text
    finally:
        if proc.stdout:
            proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        proc.wait()
        stderr_thread.join(timeout=5)

    if proc.returncode not in (0, None):
        stderr_text = stderr_buf.getvalue().strip()
        msg = f"git log failed (exit {proc.returncode}): {stderr_text}"
        if warnings is not None:
            warnings.append(msg)


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
    if not _is_github_remote(url):
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
        if result.returncode == 0:
            return result.stdout.strip() or ""
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
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
    min_confidence: float = 0.35,
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

    commits_scanned = 0
    already_processed = 0
    commit_iter = _stream_commits(repo_path, since, until, limit, warnings=result.warnings)

    if dry_run:
        for sha, _, _ in commit_iter:
            commits_scanned += 1
            try:
                if _is_processed(conn, sha):
                    already_processed += 1
            except sqlite3.OperationalError:
                # archaeology_processed table doesn't exist yet (e.g. dry-run
                # before migration has ever run) — nothing has been processed.
                pass
        result.commits_scanned = commits_scanned
        result.commits_skipped = already_processed
        to_process = commits_scanned - already_processed
        est_tokens_low = to_process * 2500
        est_tokens_high = to_process * 3000
        if progress_callback:
            msg = (
                f"Found {commits_scanned} commits, "
                f"{already_processed} already processed, "
                f"{to_process} to process.\n"
                f"Estimated token cost: ~{est_tokens_low:,}-{est_tokens_high:,} tokens"
            )
            # `git log -n limit --reverse` selects the most recent `limit`
            # commits, not the oldest `limit` — re-runs at the same limit
            # can never reach older history. Surface this when the scan
            # looks capped by the limit rather than by actual history size.
            if limit and commits_scanned >= limit:
                msg += (
                    f"\nNote: --limit {limit} may be capping results to the most "
                    "recent commits; increase --limit to reach older history."
                )
            progress_callback(msg)
        return result

    batch: list[tuple[str, str, str]] = []
    pr_fail_count = 0
    try:
        for sha, message, patch_text in commit_iter:
            commits_scanned += 1
            if _is_processed(conn, sha):
                result.commits_skipped += 1
                continue
            batch.append((sha, message, patch_text))
            if len(batch) >= batch_size:
                pr_fail_count = _process_batch(
                    conn,
                    repo_path,
                    batch,
                    result,
                    pr_bodies=pr_bodies,
                    token=token,
                    min_confidence=min_confidence,
                    extraction_weights=extraction_weights,
                    progress_callback=progress_callback,
                    consecutive_pr_failures=pr_fail_count,
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
                min_confidence=min_confidence,
                extraction_weights=extraction_weights,
                progress_callback=progress_callback,
                consecutive_pr_failures=pr_fail_count,
            )
    except KeyboardInterrupt:
        # Commits already marked processed (via _mark_processed, autocommit)
        # are durable. Do NOT re-run _process_batch here — the interrupt may
        # have landed mid-batch, and re-processing would duplicate work
        # already committed. A re-run of archaeologize resumes via dedup.
        result.warnings.append(
            f"Interrupted by user after {result.commits_processed} commits. Progress saved — re-run to resume."
        )

    result.commits_scanned = commits_scanned
    return result


_PR_BODY_FAIL_THRESHOLD = 3


def _process_batch(
    conn: sqlite3.Connection,
    repo_path: str,
    batch: list[tuple[str, str, str]],
    result: ArchaeologyResult,
    *,
    pr_bodies: bool,
    token: str | None,
    min_confidence: float,
    extraction_weights: ExtractionWeights | None,
    progress_callback: Callable[[str], None] | None,
    consecutive_pr_failures: int = 0,
) -> int:
    """Returns updated consecutive_pr_failures count."""
    for sha, message, patch_text in batch:
        pr_body = None
        if pr_bodies and token and consecutive_pr_failures < _PR_BODY_FAIL_THRESHOLD:
            raw_pr = _fetch_pr_body(sha, repo_path, token)
            if raw_pr is None:
                consecutive_pr_failures += 1
                if consecutive_pr_failures >= _PR_BODY_FAIL_THRESHOLD:
                    result.warnings.append(
                        f"PR body fetch failed {_PR_BODY_FAIL_THRESHOLD} times consecutively — disabling for remaining commits"
                    )
            else:
                consecutive_pr_failures = 0
                pr_body = raw_pr or None

        bundle = _build_signal_bundle(sha, message, patch_text, pr_body)
        try:
            outcome = run_extraction(
                conn,
                session_id=None,
                repo_path=repo_path,
                bundles=[bundle],
                min_confidence=min_confidence,
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
    return consecutive_pr_failures
