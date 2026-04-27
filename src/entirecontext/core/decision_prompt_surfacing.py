"""Background worker body for UserPromptSubmit async decision surfacing (F4).

Reads a pre-redacted prompt from disk, re-applies secret filters as
defense-in-depth, runs the full decision ranker with prompt+diff+commits
signals, and writes a Markdown context file that agents pick up on the
next read cycle. The tmp prompt file is always deleted — success or fail
— in a ``try/finally``.

The hook body (``hooks/turn_capture.py::_maybe_launch_prompt_surfacing_worker``)
is responsible for the initial in-memory redaction; this worker repeats
the filter so a tampered tmp file cannot leak raw secrets into the
fallback Markdown.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


_FALLBACK_BASE = "decisions-context-prompt"


def _sanitize_id_for_path(value: str) -> str:
    """Strip filesystem-unsafe characters from an identifier."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value or "unknown")


def _get_uncommitted_diff(repo_path: str) -> str | None:
    """Return uncommitted diff text, truncated to 8192 bytes. ``None`` on failure.

    Inlined from ``hooks.decision_hooks`` to avoid a core → hooks reverse
    dependency. The behavior must match the SessionStart signal exactly so
    the ranker sees the same shape across all three surfacing channels.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:8192]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_recent_commit_shas(repo_path: str, limit: int = 5) -> list[str]:
    """Return recent commit SHAs. Empty list on failure."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", f"-{limit}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [s for s in result.stdout.strip().split("\n") if s]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _fallback_name(session_id: str, turn_id: str) -> str:
    """Turn-scoped filename so concurrent prompts in one session don't race.

    Two prompts in the same session launch two workers in parallel; the
    worker that finishes second would otherwise overwrite (or in the
    no-results branch, delete) the file the other just wrote, leaving
    stale or missing guidance. Turn-scoping eliminates the race: each
    worker writes its own artifact and readers pick the one matching
    the active turn.

    Session ids and turn ids are UUIDs in normal operation; defensively
    strip anything outside ``[A-Za-z0-9_-]`` so the result is always a
    safe filename (matches ``decision_hooks._post_tool_fallback_name``).
    """
    safe_session = _sanitize_id_for_path(session_id)
    safe_turn = _sanitize_id_for_path(turn_id)
    return f"{_FALLBACK_BASE}-{safe_session}-{safe_turn}.md"


def _cleanup_older_session_fallbacks(repo_path: str, session_id: str, keep_name: str) -> None:
    """Best-effort delete of prior prompt fallbacks for the same session.

    Turn-scoped filenames remove the write race, but without cleanup a
    long session accumulates N files per N prompts. This sweep runs
    after the current turn's file is written and silently removes the
    session's other ``decisions-context-prompt-<session>-*.md`` files.
    Best-effort: any OSError is swallowed so a cleanup failure never
    fails the primary write path.
    """
    try:
        base_dir = Path(repo_path) / ".entirecontext"
        if not base_dir.is_dir():
            return
        safe_session = _sanitize_id_for_path(session_id)
        prefix = f"{_FALLBACK_BASE}-{safe_session}-"
        for entry in base_dir.iterdir():
            if entry.name == keep_name:
                continue
            if entry.name.startswith(prefix) and entry.name.endswith(".md"):
                try:
                    entry.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` via tmp+rename under the target's parent directory.

    Mode is applied to the tmp file before the rename so the final file
    lands with the restrictive permissions in a single filesystem step.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, mode)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def _format_decision_entry(decision: dict[str, Any], rank: int) -> str:
    parts = [f"### {rank}. {decision.get('title', '(untitled)')}"]
    if decision.get("id"):
        parts.append(f"  ID: `{decision['id'][:12]}`")
    if decision.get("staleness_status"):
        parts.append(f"  Status: {decision['staleness_status']}")
    if decision.get("score") is not None:
        parts.append(f"  Score: {decision['score']:.2f}")
    if decision.get("rationale"):
        rationale = decision["rationale"]
        if len(rationale) > 200:
            rationale = rationale[:200] + "…"
        parts.append(f"\n  {rationale}")
    if decision.get("selection_id"):
        parts.append(f"  Selection: {decision['selection_id']}")
    return "\n".join(parts)


def run_prompt_surface_worker(
    repo_path: str,
    session_id: str,
    turn_id: str,
    prompt_file: str | Path,
) -> dict[str, Any]:
    """Rank decisions relevant to the redacted prompt and write fallback Markdown.

    Returns a result dict for testability:
        {"wrote": bool, "output_path": str | None, "deleted_tmp": bool,
         "count": int, "warnings": [str]}

    Never raises: on internal failure, captures a warning and still
    attempts tmp-file cleanup. Tests assert both the happy path and the
    cleanup guarantee.
    """
    result: dict[str, Any] = {
        "wrote": False,
        "output_path": None,
        "deleted_tmp": False,
        "count": 0,
        "warnings": [],
    }
    prompt_path = Path(prompt_file)

    try:
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            result["warnings"].append(f"read_prompt_file:{exc}")
            return result

        # Defense-in-depth redaction. The hook writes an already-redacted
        # payload; run the filters again so a tampered or externally-written
        # tmp file still cannot leak raw secrets through the Markdown.
        from .config import load_config
        from .content_filter import redact_for_query
        from .security import filter_secrets

        try:
            config = load_config(repo_path)
        except Exception as exc:
            result["warnings"].append(f"load_config:{exc}")
            config = {}

        redacted = filter_secrets(prompt_text)
        redacted = redact_for_query(redacted, config)

        # Signal assembly — uses module-local git helpers (see
        # ``_get_uncommitted_diff`` / ``_get_recent_commit_shas`` above)
        # so ``core.decision_prompt_surfacing`` has no reverse edge on
        # ``hooks.decision_hooks``. The helpers mirror SessionStart's
        # shape exactly so the ranker sees consistent signals across
        # all three surfacing channels.
        diff_text = _get_uncommitted_diff(repo_path)
        commit_shas = _get_recent_commit_shas(repo_path, limit=5)

        # Combined signal for FTS: prompt text + diff. _tokenize_diff_for_fts
        # already handles plain-text input (no +/- lines) alongside real diff
        # hunks, so concatenation is a clean no-refactor integration.
        combined_diff = redacted
        if diff_text:
            combined_diff = f"{redacted}\n\n{diff_text}"

        from ..db import get_db

        conn = get_db(repo_path)
        try:
            from .decisions import (
                _load_quality_weights,
                _load_ranking_weights,
                get_decision,
                rank_related_decisions,
            )

            limit = int(config.get("decisions", {}).get("surface_on_user_prompt_limit", 3))
            ranking_weights = _load_ranking_weights(config)
            quality_weights = _load_quality_weights(config)

            ranked = rank_related_decisions(
                conn,
                file_paths=[],
                diff_text=combined_diff,
                commit_shas=commit_shas,
                assessment_ids=[],
                limit=limit,
                include_contradicted=False,
                ranking=ranking_weights,
                quality=quality_weights,
            )

            surfaced: list[dict] = []
            for idx, d in enumerate(ranked, start=1):
                full = get_decision(conn, d["id"])
                if not full:
                    continue
                full["score"] = d.get("score")
                full["rank"] = idx
                surfaced.append(full)

            # Retrieval telemetry — keep the same event/selection shape that
            # SessionStart and PostToolUse use so aggregation downstream sees
            # a single consistent schema across all three channels. Wrapped
            # in ``transaction(conn)`` so the commit boundary is owned here
            # (per core/ transaction policy) instead of via a raw commit.
            if surfaced:
                try:
                    from .context import transaction
                    from .telemetry import record_retrieval_event, record_retrieval_selection

                    with transaction(conn):
                        event = record_retrieval_event(
                            conn,
                            source="hook",
                            search_type="user_prompt",
                            target="decision",
                            query="",
                            result_count=len(surfaced),
                            latency_ms=0,
                            session_id=session_id,
                            file_filter=None,
                        )
                        for d in surfaced:
                            sel = record_retrieval_selection(
                                conn,
                                event["id"],
                                result_type="decision",
                                result_id=d["id"],
                                rank=d["rank"],
                            )
                            d["selection_id"] = sel["id"]
                except Exception as exc:
                    result["warnings"].append(f"telemetry:{exc}")
                    for d in surfaced:
                        d.pop("selection_id", None)
        finally:
            conn.close()

        result["count"] = len(surfaced)

        fallback_name = _fallback_name(session_id, turn_id)
        fallback_path = Path(repo_path) / ".entirecontext" / fallback_name
        if surfaced:
            entries = [_format_decision_entry(d, d["rank"]) for d in surfaced]
            body = (
                "## Related Decisions (from prompt)\n\n"
                "The following decisions are ranked against the current user prompt:\n\n" + "\n\n".join(entries)
            )
            try:
                _atomic_write_text(fallback_path, body)
                result["wrote"] = True
                result["output_path"] = str(fallback_path)
                # After the current turn's file is durable, sweep older
                # prompt fallbacks for this session so a long session
                # doesn't leak N files per N prompts. Runs AFTER the
                # write so readers never see a "everything deleted,
                # nothing written yet" intermediate state.
                _cleanup_older_session_fallbacks(repo_path, session_id, keep_name=fallback_name)
            except OSError as exc:
                result["warnings"].append(f"write_fallback:{exc}")
        else:
            # No ranked decisions for this turn — remove only this turn's
            # file if it somehow exists from a prior run. Older turns'
            # files (from the same session) are left alone: a newer turn
            # with no hits shouldn't erase guidance the user may still
            # be acting on from an earlier prompt.
            if fallback_path.exists():
                try:
                    fallback_path.unlink()
                except OSError:
                    pass

    except Exception as exc:
        result["warnings"].append(f"worker:{exc}")
    finally:
        try:
            prompt_path.unlink()
            result["deleted_tmp"] = True
        except OSError:
            pass

    return result
