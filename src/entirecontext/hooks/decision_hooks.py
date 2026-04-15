"""Decision-related hook functions — stale detection, extraction, context surfacing."""

from __future__ import annotations

import re
import sqlite3
import subprocess
from typing import Any

from ..core.async_worker import launch_worker, worker_status
from .session_lifecycle import _find_git_root, _record_hook_warning

# Two distinct files so SessionStart and PostToolUse never clobber each
# other. Agents read both; PR #56 review round 3 flagged that a shared
# path lets PostToolUse cleanup destroy SessionStart context.
#
# PostToolUse further suffixes its fallback with the session id so two
# concurrent sessions in the same repo can't clobber each other (PR #56
# review round 4). SessionStart stays on a single path for backwards
# compatibility — agents that only run one session at a time still see
# the long-standing name.
_SESSION_START_FALLBACK_NAME = "decisions-context.md"
_POST_TOOL_FALLBACK_BASE = "decisions-context-tooluse"

# Tools that open/view a file without editing it. Firing mid-session
# decision surfacing on these would consume the per-turn dedup marker
# before the user's real Edit runs — the typical agent flow is Read-then-
# Edit within the same turn, and the subsequent Edit would then produce
# no Markdown block at all. PostToolUse short-circuits for these tool
# names before touching the DB or any dedup state.
_READ_ONLY_TOOLS = frozenset({"Read", "NotebookRead"})


def _post_tool_fallback_name(session_id: str) -> str:
    """Return the session-scoped filename for the PostToolUse fallback.

    Session ids are UUIDs in normal operation, but we sanitize defensively
    in case a caller passes something unusual — strip anything outside the
    ``[A-Za-z0-9_-]`` set so the result is always a safe filename.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id or "unknown")
    return f"{_POST_TOOL_FALLBACK_BASE}-{safe}.md"


def _load_decisions_config(repo_path: str) -> dict:
    from ..core.config import load_config

    config = load_config(repo_path)
    return config.get("decisions", {})


def maybe_check_stale_decisions(repo_path: str) -> None:
    """Auto-detect stale decisions on SessionEnd. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_stale_check", False):
            return

        from ..core.decisions import check_staleness, list_decisions, update_decision_staleness
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            decisions = list_decisions(conn, staleness_status="fresh", limit=50)
            for d in decisions:
                result = check_staleness(conn, d["id"], repo_path)
                if result["stale"]:
                    update_decision_staleness(conn, d["id"], "stale")
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_stale_check", exc)


def _get_recently_changed_files(repo_path: str) -> list[str]:
    """Get files changed in recent commits. Falls back to git log if both fail, records warning."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~5..HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-5"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return list({f for f in result.stdout.strip().split("\n") if f})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _record_hook_warning(repo_path, "get_recently_changed_files", RuntimeError("both git diff and git log failed"))
    return []


def _format_decision_entry(d: dict, stale: bool = False) -> str:
    id_prefix = d["id"][:8]
    title = d.get("title", "")
    status = "STALE" if stale else d.get("staleness_status", "fresh")
    rationale = d.get("rationale", "") or ""
    rationale_short = rationale[:120] + "..." if len(rationale) > 120 else rationale
    files = ", ".join(d.get("files", [])[:3])
    parts = [f"- [{id_prefix}] {title}"]
    parts.append(f"  Status: {status}")
    if files:
        parts.append(f"  Files: {files}")
    if rationale_short:
        parts.append(f"  Rationale: {rationale_short}")
    return "\n".join(parts)


def on_session_start_decisions(data: dict[str, Any]) -> str | None:
    """Surface related and stale decisions at session start. Never raises."""
    try:
        cwd = data.get("cwd", ".")
        repo_path = _find_git_root(cwd)
        if not repo_path:
            return None

        config = _load_decisions_config(repo_path)
        if not config.get("show_related_on_start", False):
            return None

        from ..core.decisions import (
            _apply_staleness_policy,
            get_decision,
            list_decisions,
            resolve_successor_chain,
        )
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            sections = []
            seen_ids: set[str] = set()
            display_limit = 5

            # 1. Recently changed files → linked decisions.
            # Use `list_decisions(file_path=f)` per changed file so path matching
            # preserves the existing LIKE-contains semantics (handles `./src/app.py`
            # vs `src/app.py` divergence between git output and stored decision_files).
            # Staleness policy: contradicted rows are dropped by the policy filter,
            # but superseded rows are intentionally kept so the loop below can walk
            # their supersession chain and substitute the terminal successor.
            changed_files = _get_recently_changed_files(repo_path)
            file_related = []
            if changed_files:
                raw_seen: set[str] = set()
                for f in changed_files:
                    if len(seen_ids) >= display_limit:
                        break

                    # Push contradicted-exclusion down to SQL so the limit=10
                    # row cap can't hide fresh/superseded candidates behind a
                    # wall of contradicted rows (PR #55 Codex review).
                    file_rows: list[dict] = []
                    for d in list_decisions(conn, file_path=f, limit=10, include_contradicted=False):
                        if d["id"] in raw_seen:
                            continue
                        raw_seen.add(d["id"])
                        file_rows.append(d)

                    if not file_rows:
                        continue

                    # SQL already dropped contradicted rows; the policy call
                    # still enforces `include_superseded=True` so the chain
                    # collapse branch below can substitute each one with its
                    # terminal successor.
                    kept, _stats = _apply_staleness_policy(
                        file_rows,
                        include_stale=True,
                        include_superseded=True,
                        include_contradicted=False,
                    )
                    for row in kept:
                        if row["id"] in seen_ids:
                            continue
                        effective_id = row["id"]
                        if row.get("staleness_status") == "superseded":
                            if not row.get("superseded_by_id"):
                                # No successor pointer — hide this orphaned record.
                                continue
                            terminal_id, terminal_status = resolve_successor_chain(conn, row["id"])
                            if terminal_id == row["id"] or terminal_status in ("contradicted", "superseded"):
                                # Unresolved chain or terminal is also filtered — skip.
                                continue
                            effective_id = terminal_id
                            if effective_id in seen_ids:
                                continue
                        full = get_decision(conn, effective_id)
                        if full:
                            file_related.append(full)
                            seen_ids.add(effective_id)
                        if len(seen_ids) >= display_limit:
                            break

                if file_related:
                    entries = [_format_decision_entry(d) for d in file_related[:display_limit]]
                    sections.append(
                        "## Related Decisions\n\n"
                        "The following decisions are linked to recently changed files:\n\n" + "\n\n".join(entries)
                    )

            # 2. Stale decisions — explicit status filter; separate from default policy.
            stale = list_decisions(conn, staleness_status="stale", limit=10)
            stale_new = [d for d in stale if d["id"] not in seen_ids]
            remaining = display_limit - len(seen_ids)
            if stale_new and remaining > 0:
                stale_entries = []
                for d in stale_new[:remaining]:
                    full = get_decision(conn, d["id"]) or d
                    stale_entries.append(_format_decision_entry(full, stale=True))
                    seen_ids.add(d["id"])
                sections.append(
                    "## Stale Decisions (action needed)\n\n"
                    + "\n\n".join(stale_entries)
                    + "\n\nConsider updating stale decisions or marking them as superseded."
                )

            # Write fallback file for agents that don't capture stdout
            from pathlib import Path

            fallback_path = Path(repo_path) / ".entirecontext" / _SESSION_START_FALLBACK_NAME
            if sections:
                output = "\n\n".join(sections)
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_path.write_text(output, encoding="utf-8")
                # Cross-channel dedup: record surfaced IDs on the session row so
                # PostToolUse can't re-surface the same decision later in the
                # same session (issue #42 cross-channel dedup).
                surfacing_session_id = data.get("session_id")
                if surfacing_session_id and seen_ids:
                    try:
                        prior = _load_session_metadata(conn, surfacing_session_id)
                        prior_set = set(prior.get("surfaced_decisions") or [])
                        merged = sorted(prior_set | set(seen_ids))
                        _write_session_metadata_patch(
                            conn,
                            surfacing_session_id,
                            {"$.surfaced_decisions": merged},
                        )
                        conn.commit()
                    except Exception:
                        pass
                return output
            else:
                # Clean up stale fallback file
                if fallback_path.exists():
                    try:
                        fallback_path.unlink()
                    except OSError:
                        pass
                return None
        finally:
            conn.close()
    except Exception as exc:
        try:
            repo_path = _find_git_root(data.get("cwd", "."))
            if repo_path:
                _record_hook_warning(repo_path, "session_start_decisions", exc)
        except Exception:
            pass
        return None


def _gather_exact_file_matches(conn: sqlite3.Connection, normalized_files: list[str]) -> set[str]:
    """Return decision IDs that have an EXACT file link to one of the inputs.

    Unlike ``_gather_candidates_by_files`` (which the full ranker uses),
    this helper deliberately skips ancestor/proximity matches so the
    PostToolUse hook surfaces decisions linked directly to the edited file
    rather than sibling decisions under the same directory. Proximity is
    the full ranker's job; the hook is the fast exact-match path.
    """
    if not normalized_files:
        return set()
    placeholders = ",".join("?" for _ in normalized_files)
    rows = conn.execute(
        f"SELECT DISTINCT decision_id FROM decision_files "  # noqa: S608
        f"WHERE REPLACE("
        f"  CASE WHEN file_path LIKE './%' THEN SUBSTR(file_path, 3) ELSE file_path END, "
        f"  '\\', '/') IN ({placeholders})",
        normalized_files,
    ).fetchall()
    return {r["decision_id"] for r in rows}


def _find_ec_repo_root(start: str) -> str | None:
    """Walk up from ``start`` looking for ``.entirecontext/db/local.db``.

    Used by ``on_post_tool_use_decisions`` to recover the repo root without
    invoking ``git`` (which is too expensive inside the 3-second PostToolUse
    hook budget — ``_find_git_root`` has its own 5-second subprocess timeout
    that would blow the budget). Pure filesystem walk; no subprocess.
    """
    from pathlib import Path as _Path

    try:
        current = _Path(start).resolve()
    except (OSError, RuntimeError):
        return None
    for parent in (current, *current.parents):
        if (parent / ".entirecontext" / "db" / "local.db").exists():
            return str(parent)
    return None


def _extract_tool_files(tool_input: Any, config: dict) -> list[str]:
    """Extract file paths from a PostToolUse tool_input payload.

    Handles the single-file case (`file_path`, `path`, `notebook_path`) and
    the MultiEdit case (`edits[].file_path`). Skips any files the capture
    config marks as skippable.
    """
    from ..core.content_filter import should_skip_file
    from ..core.decisions import _normalize_path

    if not isinstance(tool_input, dict):
        return []

    collected: list[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        if should_skip_file(value, config):
            return
        normalized = _normalize_path(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        collected.append(normalized)

    for key in ("file_path", "path", "notebook_path"):
        if key in tool_input:
            _add(tool_input[key])

    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                _add(edit.get("file_path"))

    return collected


def _load_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict:
    """Load sessions.metadata JSON; return empty dict on NULL/parse failure."""
    import json as _json

    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["metadata"]:
        return {}
    try:
        parsed = _json.loads(row["metadata"])
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _write_session_metadata_patch(conn: sqlite3.Connection, session_id: str, patch: dict) -> None:
    """Merge patch into sessions.metadata via json_set + COALESCE null-safe pattern.

    We intentionally write one key at a time using json_set so we don't lose
    unrelated keys in a concurrent update. patch is ``{json_path: python_value}``.
    """
    import json as _json

    if not patch:
        return
    for json_path, value in patch.items():
        conn.execute(
            "UPDATE sessions SET metadata = json_set(COALESCE(metadata, '{}'), ?, json(?)) WHERE id = ?",
            (json_path, _json.dumps(value), session_id),
        )


def on_post_tool_use_decisions(data: dict[str, Any]) -> str | None:
    """Surface decisions linked to just-edited files mid-session.

    Fires on PostToolUse. Must stay within the 3-second hook budget; uses a
    lightweight direct path (``_gather_exact_file_matches`` — exact-match
    only, deliberately narrower than the full ranker's
    ``_gather_candidates_by_files`` which also returns ancestor/proximity
    hits) and avoids ``_find_git_root``.

    Primary delivery is the file fallback
    ``.entirecontext/decisions-context-tooluse-<session_id>.md`` — the
    session-qualified suffix keeps concurrent sessions in the same repo
    from clobbering each other, and the file is also distinct from the
    SessionStart fallback so the two writers never collide. Stdout is
    a secondary, non-guaranteed convenience channel.
    """
    try:
        cwd = data.get("cwd") or "."
        session_id = data.get("session_id")
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if not session_id or not tool_name:
            return None

        # Read-only tools must never fire mid-session surfacing: the typical
        # agent flow is Read-then-Edit within one turn, and letting the Read
        # consume the per-turn dedup marker would suppress the real Edit's
        # Markdown block. Short-circuit before any DB open or state mutation.
        if tool_name in _READ_ONLY_TOOLS:
            return None

        # Resolve the repo root by walking up from cwd looking for
        # `.entirecontext/db/local.db`. Using `cwd` directly would make nested
        # subdirectory invocations silently miss `<repo>/.entirecontext/config.toml`
        # (PR #56 Codex review P1). Pure filesystem walk — no `_find_git_root`
        # subprocess which would blow the 3-second hook budget.
        repo_path = _find_ec_repo_root(cwd)
        if repo_path is None:
            return None

        from ..core.config import load_config
        from ..core.content_filter import should_skip_tool
        from ..core.decisions import _normalize_path, resolve_successor_chain
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            config = load_config(repo_path)
            if not config.get("capture", {}).get("auto_capture", True):
                return None
            decisions_cfg = config.get("decisions", {})
            if not decisions_cfg.get("surface_on_tool_use", False):
                return None
            if should_skip_tool(tool_name, config):
                return None

            files = _extract_tool_files(tool_input, config)
            if not files:
                return None

            # Fast exit: no decisions at all.
            row = conn.execute("SELECT 1 FROM decisions LIMIT 1").fetchone()
            if not row:
                return None

            # Find the in-progress turn for this session.
            turn_row = conn.execute(
                "SELECT id, turn_number FROM turns "
                "WHERE session_id = ? AND turn_status = 'in_progress' "
                "ORDER BY turn_number DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if not turn_row:
                return None
            turn_id = turn_row["id"]
            turn_number = turn_row["turn_number"] or 0

            # Load session metadata for dedup and per-turn markers.
            meta = _load_session_metadata(conn, session_id)
            post_tool_turns = meta.get("post_tool_surfaced_turns") or {}
            if not isinstance(post_tool_turns, dict):
                post_tool_turns = {}
            if turn_id in post_tool_turns:
                # Already surfaced for this user turn — one event per turn.
                return None

            interval = max(int(decisions_cfg.get("surface_on_tool_use_turn_interval", 1) or 1), 1)
            if turn_number % interval != 0:
                return None

            surfaced_session_wide = set(meta.get("surfaced_decisions") or [])
            if not isinstance(surfaced_session_wide, set):
                surfaced_session_wide = set(surfaced_session_wide)

            # fallback_root is the repo root recovered above; write the
            # rolling Markdown there so nested-cwd invocations still land at
            # `<repo>/.entirecontext/decisions-context-tooluse-<session_id>.md`.
            fallback_root = repo_path

            # Exact-match only (PR #56 Codex review P2): sibling/proximity
            # candidates belong to the full ranker, not this 3-result hook
            # path. Ordering by proximity without scoring would let same-
            # directory siblings outrank direct hits when the limit is small.
            normalized_files = [_normalize_path(f) for f in files if _normalize_path(f)]
            candidate_ids = _gather_exact_file_matches(conn, normalized_files)
            if not candidate_ids:
                _cleanup_post_tool_fallback(fallback_root, session_id)
                return None

            # Fetch candidates INCLUDING superseded rows (PR #56 Codex review P1):
            # we need to walk each superseded decision to its terminal successor
            # before applying the limit, rather than dropping the chain outright.
            # Contradicted rows are still hard-excluded.
            #
            # NOTE: do NOT subtract `surfaced_session_wide` from candidate_ids
            # here. A superseded ancestor may be in that set (SessionStart
            # already showed it), but we still need to resolve its chain to
            # expose the fresh successor. Dedup is applied per-entry inside
            # the loop below, after chain resolution.
            limit = max(int(decisions_cfg.get("surface_on_tool_use_limit", 3) or 3), 1)
            placeholders = ",".join("?" for _ in candidate_ids)
            raw_rows = conn.execute(
                f"SELECT id, title, rationale, staleness_status, updated_at, superseded_by_id "  # noqa: S608
                f"FROM decisions "
                f"WHERE id IN ({placeholders}) "
                f"  AND staleness_status != 'contradicted' "
                f"ORDER BY "
                f"  CASE staleness_status WHEN 'fresh' THEN 0 WHEN 'stale' THEN 1 WHEN 'superseded' THEN 2 ELSE 3 END, "
                f"  updated_at DESC",
                tuple(candidate_ids),
            ).fetchall()

            if not raw_rows:
                _cleanup_post_tool_fallback(fallback_root, session_id)
                return None

            # Chain-collapse: substitute superseded rows with their terminal
            # successor so migration states (old linked, new not yet linked)
            # still surface the live decision. Terminal must be fresh/stale
            # and must not already be in the session-wide dedup set.
            decisions_out: list[dict] = []
            emitted: set[str] = set()
            for r in raw_rows:
                if len(decisions_out) >= limit:
                    break
                status = r["staleness_status"] or "fresh"
                if status == "superseded":
                    if not r["superseded_by_id"]:
                        continue
                    try:
                        terminal_id, terminal_status = resolve_successor_chain(conn, r["id"])
                    except Exception:
                        continue
                    if terminal_id == r["id"] or terminal_status in ("superseded", "contradicted"):
                        continue
                    if terminal_id in emitted or terminal_id in surfaced_session_wide:
                        continue
                    term_row = conn.execute(
                        "SELECT id, title, rationale, staleness_status, updated_at FROM decisions WHERE id = ?",
                        (terminal_id,),
                    ).fetchone()
                    if not term_row:
                        continue
                    decisions_out.append(
                        {
                            "id": term_row["id"],
                            "title": term_row["title"],
                            "rationale": term_row["rationale"],
                            "staleness_status": term_row["staleness_status"],
                            "updated_at": term_row["updated_at"],
                            "files": [],
                        }
                    )
                    emitted.add(term_row["id"])
                    continue
                # Non-superseded path: enforce session-wide dedup here, after
                # the (now-skipped) superseded branch. This keeps the chain
                # discovery path reachable for superseded ancestors whose IDs
                # are in surfaced_session_wide, while still suppressing repeat
                # surfacing of already-shown fresh/stale rows.
                if r["id"] in emitted or r["id"] in surfaced_session_wide:
                    continue
                decisions_out.append(
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "rationale": r["rationale"],
                        "staleness_status": status,
                        "updated_at": r["updated_at"],
                        "files": [],
                    }
                )
                emitted.add(r["id"])

            if not decisions_out:
                _cleanup_post_tool_fallback(fallback_root, session_id)
                return None
            entries = [_format_decision_entry(d) for d in decisions_out]
            header = "## Related Decisions (current edit)\n\nThe file(s) you just edited are linked to the following prior decisions:\n\n"
            body = header + "\n\n".join(entries)

            # Write the PostToolUse-specific fallback file. A separate path
            # from the SessionStart fallback keeps the two writers independent
            # — deleting our file on empty results can never destroy the
            # SessionStart context the agent may still be reading (PR #56
            # Codex review round 3).
            from pathlib import Path as _Path

            fallback_path = _Path(fallback_root) / ".entirecontext" / _post_tool_fallback_name(session_id)
            try:
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_path.write_text(body, encoding="utf-8")
            except OSError:
                pass  # never block tool execution

            # Persist the dedup state + telemetry event atomically (PR #56
            # review round 4). If any of these writes raise, we must NOT
            # leave the fallback file on disk — otherwise the next tool
            # call in the same turn sees stale metadata and re-surfaces
            # the same decisions, violating the documented per-turn guarantee.
            new_ids = [d["id"] for d in decisions_out]
            new_session_wide = sorted(surfaced_session_wide | set(new_ids))
            post_tool_turns[turn_id] = new_ids
            try:
                from ..core.telemetry import record_retrieval_event

                # _write_session_metadata_patch MUST run before
                # record_retrieval_event: the latter commits internally
                # (telemetry.record_retrieval_event ends with conn.commit),
                # so reversing this order would leave an orphaned telemetry
                # row on disk if the metadata write then fails — the
                # rollback in the except handler cannot undo an already-
                # committed row. With this ordering, the metadata UPDATE
                # is still pending when record_retrieval_event commits,
                # so both writes flush together in one transaction.
                _write_session_metadata_patch(
                    conn,
                    session_id,
                    {
                        "$.surfaced_decisions": new_session_wide,
                        "$.post_tool_surfaced_turns": post_tool_turns,
                    },
                )
                record_retrieval_event(
                    conn,
                    source="hook",
                    search_type="post_tool_use",
                    target="decision",
                    query=",".join(files),
                    result_count=len(decisions_out),
                    latency_ms=0,
                    session_id=session_id,
                    turn_id=turn_id,
                    file_filter=",".join(files),
                )
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                # Keep dedup state and the fallback file in sync: if the
                # dedup write failed, remove the fallback so the next call
                # re-surfaces cleanly instead of reading a file that no
                # metadata record anchors.
                _cleanup_post_tool_fallback(fallback_root, session_id)
                return None

            return body
        finally:
            conn.close()
    except Exception as exc:
        try:
            _record_hook_warning(data.get("cwd", "."), "post_tool_use_decisions", exc)
        except Exception:
            pass
        return None


def _cleanup_session_start_fallback(root: str) -> None:
    """Delete the SessionStart-written ``decisions-context.md`` if it exists.

    Used only by ``on_session_start_decisions``. The PR #55 cleanup-on-empty
    semantics apply to the SessionStart writer's own file — never to the
    PostToolUse file (see ``_cleanup_post_tool_fallback``).
    """
    from pathlib import Path as _Path

    try:
        path = _Path(root) / ".entirecontext" / _SESSION_START_FALLBACK_NAME
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _cleanup_post_tool_fallback(root: str, session_id: str) -> None:
    """Delete the session-scoped PostToolUse fallback file if it exists.

    Takes the session id so each session only touches its own file —
    concurrent sessions in the same repo cannot clobber one another
    (PR #56 review round 4). The SessionStart file is also untouched,
    preserving the round-3 writer-separation fix.
    """
    from pathlib import Path as _Path

    try:
        path = _Path(root) / ".entirecontext" / _post_tool_fallback_name(session_id)
        if path.exists():
            path.unlink()
    except OSError:
        pass


# Backwards-compatible alias — external callers that may have imported the
# old name still work. Points at the SessionStart cleanup, which is the
# pre-split semantics everyone expected.
_cleanup_fallback_file = _cleanup_session_start_fallback


def _session_has_extraction_marker(conn, session_id: str) -> bool:
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["metadata"]:
        return False
    try:
        import json

        meta = json.loads(row["metadata"])
        if not isinstance(meta, dict):
            return False
        # v13 marker is authoritative; v12 marker shim means sessions already
        # processed by the old pipeline are not re-extracted.
        if meta.get("candidates_extracted", False) is True:
            return True
        if meta.get("decisions_extracted", False) is True:
            return True
        return False
    except (ValueError, TypeError):
        return False


def _summaries_match_keywords(summaries: list[str], keywords: list[str]) -> bool:
    if not keywords:
        return False
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    return any(pattern.search(s) for s in summaries)


def _session_has_checkpoint_signal(conn, session_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM checkpoints "
        "WHERE session_id = ? AND diff_summary IS NOT NULL AND TRIM(diff_summary) != '' "
        "LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def _session_has_assessment_signal(conn, session_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM assessments a JOIN checkpoints c ON a.checkpoint_id = c.id "
        "WHERE c.session_id = ? AND a.verdict IN ('expand', 'narrow') "
        "LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def maybe_extract_decisions(repo_path: str, session_id: str) -> None:
    """Launch background candidate extraction if any of the three source gates fire. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_extract", False):
            return

        from ..db import get_db

        conn = get_db(repo_path)
        try:
            if _session_has_extraction_marker(conn, session_id):
                return

            keywords = config.get("extract_keywords", [])
            rows = conn.execute(
                "SELECT assistant_summary FROM turns "
                "WHERE session_id = ? AND assistant_summary IS NOT NULL "
                "ORDER BY turn_number ASC",
                (session_id,),
            ).fetchall()
            summaries = [r["assistant_summary"] for r in rows if r["assistant_summary"]]

            # Gate: any one of the three source signals is enough to launch.
            session_signal = bool(summaries) and _summaries_match_keywords(summaries, keywords)
            checkpoint_signal = _session_has_checkpoint_signal(conn, session_id)
            assessment_signal = _session_has_assessment_signal(conn, session_id)

            if not (session_signal or checkpoint_signal or assessment_signal):
                return

            if worker_status(repo_path, pid_name="worker-decision").get("running"):
                return

            import sys

            launch_worker(
                repo_path,
                [
                    sys.executable,
                    "-m",
                    "entirecontext.cli",
                    "decision",
                    "extract-candidates",
                    "--session",
                    session_id,
                ],
                pid_name="worker-decision",
            )
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_extract_decisions", exc)
