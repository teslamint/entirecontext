"""Decision MCP tools."""

from __future__ import annotations

import json
import time

from .. import runtime


def _ensure_list(value: str | dict | list | None, field_name: str) -> list | None:
    """Coerce common agent input shapes for list fields into proper lists."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError(f"'{field_name}' must be a list, string, or null. Got {type(value).__name__}.")


async def ec_decision_get(decision_id: str) -> str:
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import get_decision

        decision = get_decision(conn, decision_id)
        if not decision:
            return runtime.error_payload(f"Decision '{decision_id}' not found")
        return json.dumps(decision)
    finally:
        conn.close()


async def ec_decision_related(
    files: list[str] | None = None,
    assessment_ids: list[str] | None = None,
    diff_text: str | None = None,
    commit_shas: list[str] | None = None,
    limit: int = 10,
    retrieval_event_id: str | None = None,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
    include_filter_stats: bool = False,
) -> str:
    """Rank decisions related to current change context.

    Staleness policy (issue #39):
    - Superseded and contradicted decisions are excluded by default.
    - Superseded candidates collapse to their terminal successor when it passes the filter.
    - Set include_filter_stats=True to receive a breakdown of what was filtered.
    """
    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.config import load_config
        from ...core.decisions import _load_quality_weights, _load_ranking_weights, rank_related_decisions

        full_config = load_config(repo_path)
        ranking_weights = _load_ranking_weights(full_config)
        quality_weights = _load_quality_weights(full_config)

        started_at = time.perf_counter()
        decisions, filter_stats = rank_related_decisions(
            conn,
            file_paths=files or [],
            assessment_ids=assessment_ids or [],
            diff_text=diff_text,
            commit_shas=commit_shas or [],
            limit=limit,
            include_stale=include_stale,
            include_superseded=include_superseded,
            include_contradicted=include_contradicted,
            ranking=ranking_weights,
            quality=quality_weights,
            _return_stats=True,
        )
        tracked_event_id = runtime.record_search_event(
            conn,
            query=diff_text or "decision-related",
            search_type="decision_related",
            target="decision",
            result_count=len(decisions),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            file_filter=",".join(files or []) or None,
            since=None,
        )
        for idx, item in enumerate(decisions, start=1):
            runtime.record_selection(
                conn,
                retrieval_event_id=tracked_event_id or retrieval_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
        payload = {
            "decisions": decisions,
            "count": len(decisions),
            "retrieval_event_id": tracked_event_id,
        }
        if include_filter_stats:
            payload["filter_stats"] = filter_stats
        return json.dumps(payload)
    finally:
        conn.close()


async def ec_decision_context(
    limit: int = 5,
    recent_turns: int = 5,
    include_stale: bool = True,
    include_filter_stats: bool = False,
    session_id: str | None = None,
) -> str:
    """Proactive one-call decision retrieval from the current session context.

    Auto-assembles signals from the active session (files_touched from recent
    turns + files changed in the uncommitted git diff + the most recent
    checkpoint SHA) and ranks decisions via the full scorer. Agents should
    prefer this over ec_decision_related for generic "what's relevant to my
    current work" queries — it's the closest to a zero-argument proactive
    retrieval path.

    Degrades gracefully when there's no active session: falls back to
    git-diff-only signals and returns ``signal_summary.active_session=false``
    with a warning. A warning is also added when ``git diff HEAD`` is
    unavailable (bare repo, pre-first-commit, subprocess failure).

    Each returned decision carries a ``selection_id`` that can be passed
    directly to ``ec_decision_outcome`` or ``ec_context_apply`` without a
    follow-up lookup.

    Args:
        limit: Maximum number of decisions to return.
        recent_turns: How many recent turns to union files_touched from.
        include_stale: Include stale-marked decisions (demoted but visible).
        include_filter_stats: Include filter breakdown in the response.
        session_id: Optional explicit session to pull turn/checkpoint signals
            from. When omitted, the tool falls back to
            ``detect_current_context(conn)``. Pass this whenever two agent
            sessions are open in the same repo so the caller can be sure
            signals come from the right workflow (PR #56 review).
    """
    import subprocess

    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.config import load_config
        from ...core.decisions import (
            _load_quality_weights,
            _load_ranking_weights,
            _normalize_path,
            rank_related_decisions,
        )
        from ...core.telemetry import detect_current_context

        full_config = load_config(repo_path)
        ranking_weights = _load_ranking_weights(full_config)
        quality_weights = _load_quality_weights(full_config)

        # Track whether the caller explicitly pinned a session. When they
        # did, we must NOT fold repo-wide signals (like `git diff HEAD`)
        # into the ranking — those reflect the working tree state across
        # all concurrent sessions and would leak files from other sessions
        # into this query. Multi-session correctness beats coverage here.
        is_session_overridden = session_id is not None
        turn_id: str | None = None

        if session_id:
            # Explicit override: verify the session exists before trusting it.
            row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return runtime.error_payload(f"Session not found: {session_id}")
            # Anchor telemetry to the latest turn of the overridden session
            # so retrieval_events / retrieval_selections are attributed
            # correctly regardless of what `detect_current_context` would
            # return for the connection's own active session.
            turn_row = conn.execute(
                "SELECT id FROM turns WHERE session_id = ? ORDER BY turn_number DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if turn_row:
                turn_id = turn_row["id"]
        else:
            session_id, turn_id = detect_current_context(conn)
        warnings: list[str] = []
        if is_session_overridden:
            warnings.append("session_id override: repo-wide git diff signal skipped to avoid cross-session pollution.")

        # --- 1. files_touched from recent turns (session-scoped) ---
        file_paths: list[str] = []
        seen_files: set[str] = set()
        if session_id:
            rows = conn.execute(
                "SELECT files_touched FROM turns "
                "WHERE session_id = ? AND files_touched IS NOT NULL "
                "ORDER BY turn_number DESC LIMIT ?",
                (session_id, recent_turns),
            ).fetchall()
            for row in rows:
                raw = row["files_touched"]
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(parsed, list):
                    continue
                for f in parsed:
                    if not isinstance(f, str):
                        continue
                    normalized = _normalize_path(f)
                    if normalized and normalized not in seen_files:
                        seen_files.add(normalized)
                        file_paths.append(normalized)
        else:
            warnings.append("No active session; falling back to repo-state signals only.")

        # --- 2. Git diff (diff_text + file union) ---
        # Both git calls use `check=False`, so non-zero exits (e.g. a
        # pre-first-commit repo where `HEAD` doesn't exist, a broken
        # worktree, or a missing `.git` directory) surface here as
        # `returncode != 0` rather than as exceptions. Detect that case
        # explicitly and attach a warning — otherwise callers see
        # `signal_summary.has_diff=False` with no indication of *why*
        # the diff path was skipped, which can produce unexpectedly
        # empty rankings that look like a bug in the ranker.
        diff_text: str | None = None
        has_diff = False
        git_diff_available = False
        # ``is_session_overridden`` suppresses the repo-wide git diff path
        # entirely: the diff reflects the working tree for ALL concurrent
        # sessions in this repo and would pollute a session-pinned query
        # with files touched by unrelated sessions. Override callers rely
        # on exact session isolation, so we accept the loss of diff-based
        # coverage (already surfaced as a warning above) in exchange.
        if repo_path and not is_session_overridden:
            try:
                diff_result = subprocess.run(
                    ["git", "diff", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if diff_result.returncode != 0:
                    warnings.append(
                        "git diff HEAD returned non-zero; commit/diff signal skipped "
                        "(typical in a pre-first-commit repo or broken worktree)."
                    )
                else:
                    git_diff_available = True
                    if diff_result.stdout:
                        diff_text = diff_result.stdout[:8192]
                        has_diff = True

                # Only run the --name-only pass when the first call was
                # healthy; otherwise we already recorded a warning and
                # there's nothing new to learn.
                if git_diff_available:
                    name_result = subprocess.run(
                        ["git", "diff", "--name-only", "HEAD"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    if name_result.returncode != 0:
                        warnings.append(
                            "git diff --name-only HEAD returned non-zero; diff-derived file signals skipped."
                        )
                    elif name_result.stdout:
                        for line in name_result.stdout.strip().splitlines():
                            normalized = _normalize_path(line.strip())
                            if normalized and normalized not in seen_files:
                                seen_files.add(normalized)
                                file_paths.append(normalized)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                warnings.append("git diff HEAD unavailable; commit/diff signal skipped.")

        # --- 3. Latest single checkpoint SHA (bounded commit signal) ---
        # `checkpoints.git_commit_hash` is schema-level NOT NULL (see
        # db/schema.py:102), so no nullness filter is needed here.
        commit_shas: list[str] = []
        if session_id:
            row = conn.execute(
                "SELECT git_commit_hash FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row:
                commit_shas.append(row["git_commit_hash"])

        # --- 4. Rank via full scorer ---
        started_at = time.perf_counter()
        decisions, filter_stats = rank_related_decisions(
            conn,
            file_paths=file_paths,
            diff_text=diff_text,
            commit_shas=commit_shas,
            limit=limit,
            include_stale=include_stale,
            ranking=ranking_weights,
            quality=quality_weights,
            _return_stats=True,
        )

        # --- 5. Telemetry: event + per-decision selection ---
        # Pass the resolved session_id/turn_id explicitly so the event
        # is attributed to the caller-pinned session, not re-detected
        # via `detect_current_context` inside the wrapper. Per-selection
        # rows inherit from the event row by default, so no selection-
        # level override is needed here.
        tracked_event_id = runtime.record_search_event(
            conn,
            query="decision-context",
            search_type="decision_context",
            target="decision",
            result_count=len(decisions),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            file_filter=",".join(file_paths) or None,
            since=None,
            session_id=session_id,
            turn_id=turn_id,
        )
        for idx, item in enumerate(decisions, start=1):
            selection_id = runtime.record_selection(
                conn,
                retrieval_event_id=tracked_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
            item["selection_id"] = selection_id

        payload = {
            "decisions": decisions,
            "count": len(decisions),
            "retrieval_event_id": tracked_event_id,
            "signal_summary": {
                "file_count": len(file_paths),
                "has_diff": has_diff,
                "commit_count": len(commit_shas),
                "turn_window": recent_turns,
                "active_session": session_id is not None,
            },
        }
        if warnings:
            payload["warnings"] = warnings
        if include_filter_stats:
            payload["filter_stats"] = filter_stats
        return json.dumps(payload)
    finally:
        conn.close()


async def ec_decision_outcome(
    decision_id: str,
    outcome_type: str,
    selection_id: str | None = None,
    note: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    """Record the outcome of a decision (accepted, ignored, contradicted, refined, or replaced).

    Links the outcome to a retrieval selection when selection_id is provided,
    enabling quality tracking. Falls back to the current session context when
    session_id and turn_id are not explicitly provided.
    """
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import record_decision_outcome
        from ...core.telemetry import detect_current_context

        current_session_id, current_turn_id = detect_current_context(conn)
        if current_turn_id is None:
            current_session_id = None
        if session_id is not None or turn_id is not None:
            effective_session_id, effective_turn_id = session_id, turn_id
        else:
            effective_session_id, effective_turn_id = current_session_id, current_turn_id
        outcome = record_decision_outcome(
            conn,
            decision_id,
            outcome_type,
            retrieval_selection_id=selection_id,
            note=note,
            session_id=effective_session_id,
            turn_id=effective_turn_id,
        )
        return json.dumps(outcome)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_create(
    title: str,
    rationale: str | None = None,
    scope: str | None = None,
    rejected_alternatives: list[str] | str | dict | None = None,
    supporting_evidence: list | str | dict | None = None,
) -> str:
    """Create a new decision record.

    Args:
        title: Short name for the decision
        rationale: Reasoning behind the decision
        scope: Scope or area this decision applies to
        rejected_alternatives: List of alternatives that were considered and rejected
        supporting_evidence: Evidence supporting the decision
    """
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        rejected_alternatives = _ensure_list(rejected_alternatives, "rejected_alternatives")
        supporting_evidence = _ensure_list(supporting_evidence, "supporting_evidence")

        from ...core.decisions import create_decision

        d = create_decision(
            conn,
            title=title,
            rationale=rationale,
            scope=scope,
            rejected_alternatives=rejected_alternatives,
            supporting_evidence=supporting_evidence,
        )
        return json.dumps(d)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_list(
    staleness_status: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
    include_contradicted: bool = False,
) -> str:
    """List decisions with optional filters.

    Args:
        staleness_status: Filter by status (fresh/stale/superseded/contradicted)
        file_path: Filter by linked file path
        limit: Maximum results (default 20)
        include_contradicted: Include contradicted decisions (default False)
    """
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import list_decisions

        decisions = list_decisions(
            conn,
            staleness_status=staleness_status,
            file_path=file_path,
            limit=limit,
            include_contradicted=include_contradicted,
        )
        return json.dumps({"decisions": decisions, "count": len(decisions)})
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_stale(decision_id: str) -> str:
    """Check if a decision's linked files have changed recently (read-only).

    Returns staleness info without persisting the result. Use the CLI
    ``ec decision stale-all`` command to detect and persist staleness.

    Args:
        decision_id: Decision ID (supports prefix)
    """
    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import check_staleness

        result = check_staleness(conn, decision_id, repo_path)
        return json.dumps(result)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_search(
    query: str,
    search_type: str = "fts",
    since: str | None = None,
    limit: int = 20,
    repos: str | list[str] | None = None,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
) -> str:
    """Search decisions by keyword using FTS5 full-text search.

    Searches decision title and rationale fields. Use this when you need to find
    decisions by keyword rather than by file/assessment context.

    Args:
        query: FTS5 search query (supports AND, OR, NOT, prefix*, "phrase")
        search_type: "fts" for relevance-ranked or "hybrid" for relevance+recency
        since: ISO date filter — only return decisions updated after this date
        limit: Maximum results (default 20)
        repos: Repo filter — null for current repo, "*" or ["*"] for all repos,
               or a plain repo name string (coerced to a single-element list)
        include_stale: Include decisions marked stale (default True)
        include_superseded: Include decisions that have been superseded (default False)
        include_contradicted: Include contradicted decisions (default False)
    """
    if search_type not in ("fts", "hybrid"):
        return runtime.error_payload(f"Invalid search_type '{search_type}'. Use 'fts' or 'hybrid'.")

    repo_names = runtime.normalize_repo_names(repos)
    is_cross_repo = repos is not None and repos != ""
    if is_cross_repo:
        from ...core.cross_repo import _for_each_repo
        from ...core.decisions import fts_search_decisions, hybrid_search_decisions

        def _query(conn, _repo):
            if search_type == "hybrid":
                return hybrid_search_decisions(
                    conn,
                    query,
                    since=since,
                    limit=limit,
                    include_stale=include_stale,
                    include_superseded=include_superseded,
                    include_contradicted=include_contradicted,
                )
            return fts_search_decisions(
                conn,
                query,
                since=since,
                limit=limit,
                include_stale=include_stale,
                include_superseded=include_superseded,
                include_contradicted=include_contradicted,
            )

        cross_sort_key = "hybrid_score" if search_type == "hybrid" else "relevance_score"
        try:
            all_results, _warnings = _for_each_repo(_query, repos=repo_names, sort_key=cross_sort_key, limit=limit)
        except ValueError as exc:
            return runtime.error_payload(str(exc))
        formatted = _format_decision_results(all_results)
        return json.dumps({"decisions": formatted, "count": len(formatted), "retrieval_event_id": None})

    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import fts_search_decisions, hybrid_search_decisions

        started_at = time.perf_counter()
        if search_type == "hybrid":
            results = hybrid_search_decisions(
                conn,
                query,
                since=since,
                limit=limit,
                include_stale=include_stale,
                include_superseded=include_superseded,
                include_contradicted=include_contradicted,
            )
        else:
            results = fts_search_decisions(
                conn,
                query,
                since=since,
                limit=limit,
                include_stale=include_stale,
                include_superseded=include_superseded,
                include_contradicted=include_contradicted,
            )

        tracked_event_id = runtime.record_search_event(
            conn,
            query=query,
            search_type=f"decision_{search_type}",
            target="decision",
            result_count=len(results),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            since=since,
        )
        for idx, item in enumerate(results, start=1):
            runtime.record_selection(
                conn,
                retrieval_event_id=tracked_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
        formatted = _format_decision_results(results)
        return json.dumps(
            {
                "decisions": formatted,
                "count": len(formatted),
                "retrieval_event_id": tracked_event_id,
            }
        )
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def _format_decision_results(results: list[dict]) -> list[dict]:
    formatted = []
    for r in results:
        entry: dict = {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "rationale_excerpt": _truncate(r.get("rationale") or "", 200),
            "scope": r.get("scope", ""),
            "staleness_status": r.get("staleness_status", ""),
            "updated_at": r.get("updated_at", ""),
        }
        if "hybrid_score" in r:
            entry["hybrid_score"] = r["hybrid_score"]
        if "rank" in r:
            entry["rank"] = r["rank"]
        if "repo_name" in r:
            entry["repo_name"] = r["repo_name"]
        formatted.append(entry)
    return formatted


def register_tools(mcp, services=None) -> None:
    for tool in (
        ec_decision_get,
        ec_decision_related,
        ec_decision_context,
        ec_decision_outcome,
        ec_decision_create,
        ec_decision_list,
        ec_decision_stale,
        ec_decision_search,
    ):
        mcp.tool()(tool)
