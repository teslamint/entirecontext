"""MCP server for EntireContext — agent-facing search and context tools."""

from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

if FastMCP:
    mcp = FastMCP("entirecontext")
else:
    mcp = None


def _get_repo_db():
    """Get DB connection for the current repo."""
    from ..core.project import find_git_root
    from ..db import get_db, check_and_migrate

    repo_path = find_git_root()
    if not repo_path:
        return None, None

    conn = get_db(repo_path)
    check_and_migrate(conn)
    return conn, repo_path


def _detect_current_session(conn) -> str | None:
    """Detect current session by most recent activity."""
    row = conn.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


if mcp:

    @mcp.tool()
    async def ec_search(
        query: str,
        search_type: str = "regex",
        file_filter: str | None = None,
        commit_filter: str | None = None,
        agent_filter: str | None = None,
        since: str | None = None,
        limit: int = 20,
        repos: list[str] | None = None,
    ) -> str:
        """Search across sessions, turns, and checkpoints.

        Args:
            query: Search query string
            search_type: Search mode - "regex" (default), "fts", or "semantic"
            file_filter: Only include turns touching this file path
            commit_filter: Only include turns near this commit hash
            agent_filter: Only include sessions by this agent type
            since: Only include results after this ISO8601 timestamp
            limit: Maximum number of results (default 20)
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if search_type == "semantic":
            return json.dumps({"error": "Semantic search not yet available (Phase 3)"})

        is_cross_repo = repos is not None
        repo_names = None if not repos else (None if repos == ["*"] else repos)

        if is_cross_repo:
            from ..core.cross_repo import cross_repo_search

            results = cross_repo_search(
                query,
                search_type=search_type,
                repos=repo_names,
                file_filter=file_filter,
                commit_filter=commit_filter,
                agent_filter=agent_filter,
                since=since,
                limit=limit,
            )
        else:
            conn, _ = _get_repo_db()
            if not conn:
                return json.dumps({"error": "Not in an EntireContext-initialized repo"})

            try:
                if search_type == "fts":
                    from ..core.search import fts_search

                    results = fts_search(
                        conn,
                        query,
                        file_filter=file_filter,
                        commit_filter=commit_filter,
                        agent_filter=agent_filter,
                        since=since,
                        limit=limit,
                    )
                else:
                    from ..core.search import regex_search

                    results = regex_search(
                        conn,
                        query,
                        file_filter=file_filter,
                        commit_filter=commit_filter,
                        agent_filter=agent_filter,
                        since=since,
                        limit=limit,
                    )
            finally:
                conn.close()

        formatted = []
        for r in results:
            entry = {
                "id": r.get("id", ""),
                "session_id": r.get("session_id", ""),
                "summary": r.get("assistant_summary") or r.get("user_message", ""),
                "timestamp": r.get("timestamp", ""),
            }
            if is_cross_repo:
                entry["repo_name"] = r.get("repo_name", "")
                entry["repo_path"] = r.get("repo_path", "")
            formatted.append(entry)
        return json.dumps({"results": formatted, "count": len(formatted)})

    @mcp.tool()
    async def ec_checkpoint_list(
        session_id: str | None = None,
        limit: int = 20,
        since: str | None = None,
    ) -> str:
        """List checkpoints for current session or repo.

        Args:
            session_id: Filter by session ID (optional)
            limit: Maximum number of results (default 20)
            since: Only checkpoints after this ISO8601 timestamp
        """
        import json

        conn, _ = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            query = "SELECT * FROM checkpoints WHERE 1=1"
            params: list[Any] = []

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if since:
                query += " AND created_at >= ?"
                params.append(since)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            checkpoints = []
            for r in rows:
                checkpoints.append(
                    {
                        "id": r["id"],
                        "commit_hash": r["git_commit_hash"],
                        "branch": r["git_branch"],
                        "created_at": r["created_at"],
                        "diff_summary": r["diff_summary"],
                    }
                )
            return json.dumps({"checkpoints": checkpoints, "count": len(checkpoints)})
        finally:
            conn.close()

    @mcp.tool()
    async def ec_session_context(
        session_id: str | None = None,
    ) -> str:
        """Get session context with summary and recent turns.

        If session_id is omitted, uses the most recently active session.
        Returns session_id in response for use in subsequent calls.

        Args:
            session_id: Session ID (optional, auto-detects current session)
        """
        import json

        conn, _ = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            if not session_id:
                session_id = _detect_current_session(conn)

            if not session_id:
                return json.dumps({"error": "No active session found"})

            session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()

            if not session:
                return json.dumps({"error": f"Session not found: {session_id}"})

            turns = conn.execute(
                """SELECT id, turn_number, user_message, assistant_summary, timestamp
                FROM turns WHERE session_id = ? ORDER BY turn_number DESC LIMIT 10""",
                (session_id,),
            ).fetchall()

            return json.dumps(
                {
                    "session_id": session["id"],
                    "session_title": session["session_title"],
                    "session_summary": session["session_summary"],
                    "started_at": session["started_at"],
                    "ended_at": session["ended_at"],
                    "total_turns": session["total_turns"],
                    "recent_turns": [
                        {
                            "id": t["id"],
                            "turn_number": t["turn_number"],
                            "user_message": t["user_message"],
                            "assistant_summary": t["assistant_summary"],
                            "timestamp": t["timestamp"],
                        }
                        for t in turns
                    ],
                }
            )
        finally:
            conn.close()

    @mcp.tool()
    async def ec_attribution(
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Get human/agent attribution for a file.

        Args:
            file_path: Path to the file
            start_line: Start line number (optional)
            end_line: End line number (optional)
        """
        import json

        conn, _ = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            query = "SELECT * FROM attributions WHERE file_path = ?"
            params: list[Any] = [file_path]

            if start_line is not None:
                query += " AND end_line >= ?"
                params.append(start_line)
            if end_line is not None:
                query += " AND start_line <= ?"
                params.append(end_line)

            query += " ORDER BY start_line"
            rows = conn.execute(query, params).fetchall()

            attributions = []
            for r in rows:
                agent_name = None
                if r["agent_id"]:
                    agent = conn.execute(
                        "SELECT name, agent_type FROM agents WHERE id = ?", (r["agent_id"],)
                    ).fetchone()
                    if agent:
                        agent_name = agent["name"] or agent["agent_type"]

                attributions.append(
                    {
                        "start_line": r["start_line"],
                        "end_line": r["end_line"],
                        "type": r["attribution_type"],
                        "agent_name": agent_name,
                        "session_id": r["session_id"],
                        "turn_id": r["turn_id"],
                        "confidence": r["confidence"],
                    }
                )

            return json.dumps({"file_path": file_path, "attributions": attributions})
        finally:
            conn.close()

    @mcp.tool()
    async def ec_rewind(checkpoint_id: str) -> str:
        """Show state at a checkpoint.

        Args:
            checkpoint_id: The checkpoint ID to examine
        """
        import json

        conn, _ = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            cp = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()

            if not cp:
                return json.dumps({"error": f"Checkpoint not found: {checkpoint_id}"})

            session = conn.execute(
                "SELECT id, session_title, session_summary FROM sessions WHERE id = ?",
                (cp["session_id"],),
            ).fetchone()

            return json.dumps(
                {
                    "checkpoint_id": cp["id"],
                    "commit_hash": cp["git_commit_hash"],
                    "branch": cp["git_branch"],
                    "files_snapshot": json.loads(cp["files_snapshot"]) if cp["files_snapshot"] else None,
                    "diff_summary": cp["diff_summary"],
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

    @mcp.tool()
    async def ec_related(
        query: str | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Find related sessions and turns to current work.

        Args:
            query: Search query (optional)
            files: List of file paths to find related sessions (optional)
        """
        import json

        conn, _ = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            results = []

            if query:
                from ..core.search import regex_search

                turn_results = regex_search(conn, query, limit=10)
                for r in turn_results:
                    results.append(
                        {
                            "type": "turn",
                            "id": r.get("id", ""),
                            "session_id": r.get("session_id", ""),
                            "summary": r.get("assistant_summary") or r.get("user_message", ""),
                            "timestamp": r.get("timestamp", ""),
                            "relevance": "query_match",
                        }
                    )

            if files:
                for file_path in files[:5]:
                    rows = conn.execute(
                        "SELECT id, session_id, user_message, assistant_summary, timestamp, files_touched FROM turns WHERE files_touched LIKE ? ORDER BY timestamp DESC LIMIT 5",
                        (f"%{file_path}%",),
                    ).fetchall()
                    for r in rows:
                        results.append(
                            {
                                "type": "turn",
                                "id": r["id"],
                                "session_id": r["session_id"],
                                "summary": r["assistant_summary"] or r["user_message"] or "",
                                "timestamp": r["timestamp"],
                                "relevance": f"file:{file_path}",
                            }
                        )

            seen = set()
            unique_results = []
            for r in results:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    unique_results.append(r)

            return json.dumps({"related": unique_results[:20], "count": len(unique_results[:20])})
        finally:
            conn.close()


def run_server():
    """Run the MCP server (stdio transport)."""
    if mcp is None:
        print("MCP not available. Install with: pip install 'entirecontext[mcp]'")
        return
    mcp.run()
