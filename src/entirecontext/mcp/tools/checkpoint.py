"""Checkpoint MCP tools."""

from __future__ import annotations

import json

from .. import runtime


async def ec_checkpoint_list(
    session_id: str | None = None,
    limit: int = 20,
    since: str | None = None,
    repos: str | list[str] | None = None,
    retrieval_event_id: str | None = None,
) -> str:
    repo_names = runtime.normalize_repo_names(repos)
    if bool(repos):
        from ...core.cross_repo import cross_repo_checkpoints

        results, warnings = cross_repo_checkpoints(
            repos=repo_names,
            session_id=session_id,
            since=since,
            limit=limit,
            include_warnings=True,
        )
        checkpoints = [
            {
                "id": result.get("id", ""),
                "commit_hash": result.get("git_commit_hash", ""),
                "branch": result.get("git_branch", ""),
                "created_at": result.get("created_at", ""),
                "diff_summary": result.get("diff_summary", ""),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
            }
            for result in results
        ]
        return json.dumps(
            {
                "checkpoints": checkpoints,
                "count": len(checkpoints),
                "warnings": warnings,
                "telemetry_skipped": "cross_repo",
            }
        )

    (conn, _), error = runtime.resolve_repo()
    if error:
        return error

    try:
        query = "SELECT * FROM checkpoints WHERE 1=1"
        params: list = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        selection_ids = []
        checkpoints = []
        for row in rows:
            selection_id = runtime.record_selection(
                conn,
                retrieval_event_id=retrieval_event_id,
                result_type="checkpoint",
                result_id=row["id"],
                rank=len(selection_ids) + 1,
            )
            if selection_id:
                selection_ids.append(selection_id)
            checkpoints.append(
                {
                    "id": row["id"],
                    "commit_hash": row["git_commit_hash"],
                    "branch": row["git_branch"],
                    "created_at": row["created_at"],
                    "diff_summary": row["diff_summary"],
                }
            )
        return json.dumps(
            {
                "checkpoints": checkpoints,
                "count": len(checkpoints),
                "selection_id": selection_ids[0] if selection_ids else None,
                "selection_ids": selection_ids,
            }
        )
    finally:
        conn.close()


async def ec_rewind(checkpoint_id: str, repos: str | list[str] | None = None) -> str:
    repo_names = runtime.normalize_repo_names(repos)
    if bool(repos):
        from ...core.cross_repo import cross_repo_rewind

        result, warnings = cross_repo_rewind(checkpoint_id, repos=repo_names, include_warnings=True)
        if not result:
            return runtime.error_payload(f"Checkpoint not found: {checkpoint_id}", warnings=warnings)
        return json.dumps(
            {
                "checkpoint_id": result.get("id", ""),
                "commit_hash": result.get("git_commit_hash", ""),
                "branch": result.get("git_branch", ""),
                "files_snapshot": result.get("files_snapshot"),
                "diff_summary": result.get("diff_summary", ""),
                "session_id": result.get("session_id", ""),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
                "warnings": warnings,
            }
        )

    (conn, _), error = runtime.resolve_repo()
    if error:
        return error

    try:
        checkpoint = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
        if not checkpoint:
            return runtime.error_payload(f"Checkpoint not found: {checkpoint_id}")

        session = conn.execute(
            "SELECT id, session_title, session_summary FROM sessions WHERE id = ?",
            (checkpoint["session_id"],),
        ).fetchone()
        return json.dumps(
            {
                "checkpoint_id": checkpoint["id"],
                "commit_hash": checkpoint["git_commit_hash"],
                "branch": checkpoint["git_branch"],
                "files_snapshot": json.loads(checkpoint["files_snapshot"]) if checkpoint["files_snapshot"] else None,
                "diff_summary": checkpoint["diff_summary"],
                "session": {
                    "id": session["id"],
                    "title": session["session_title"],
                    "summary": session["session_summary"],
                }
                if session
                else None,
            }
        )
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (ec_checkpoint_list, ec_rewind):
        mcp.tool()(tool)
