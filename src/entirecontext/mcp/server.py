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
                if search_type == "semantic":
                    try:
                        from ..core.embedding import semantic_search

                        results = semantic_search(
                            conn,
                            query,
                            file_filter=file_filter,
                            commit_filter=commit_filter,
                            agent_filter=agent_filter,
                            since=since,
                            limit=limit,
                        )
                    except ImportError as e:
                        return json.dumps({"error": f"sentence-transformers is required: {e}"})
                elif search_type == "fts":
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
        repos: list[str] | None = None,
    ) -> str:
        """List checkpoints for current session or repo.

        Args:
            session_id: Filter by session ID (optional)
            limit: Maximum number of results (default 20)
            since: Only checkpoints after this ISO8601 timestamp
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_checkpoints

            repo_names = None if repos == ["*"] else repos
            results, warnings = cross_repo_checkpoints(
                repos=repo_names, session_id=session_id, since=since, limit=limit, include_warnings=True
            )
            checkpoints = []
            for r in results:
                checkpoints.append(
                    {
                        "id": r.get("id", ""),
                        "commit_hash": r.get("git_commit_hash", ""),
                        "branch": r.get("git_branch", ""),
                        "created_at": r.get("created_at", ""),
                        "diff_summary": r.get("diff_summary", ""),
                        "repo_name": r.get("repo_name", ""),
                        "repo_path": r.get("repo_path", ""),
                    }
                )
            return json.dumps({"checkpoints": checkpoints, "count": len(checkpoints), "warnings": warnings})

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
        repos: list[str] | None = None,
    ) -> str:
        """Get session context with summary and recent turns.

        If session_id is omitted, uses the most recently active session.
        Returns session_id in response for use in subsequent calls.

        Args:
            session_id: Session ID (optional, auto-detects current session)
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_session_detail

            if not session_id:
                return json.dumps({"error": "session_id is required for cross-repo session context"})

            repo_names = None if repos == ["*"] else repos
            result, warnings = cross_repo_session_detail(session_id, repos=repo_names, include_warnings=True)
            if not result:
                return json.dumps({"error": f"Session not found: {session_id}", "warnings": warnings})

            turns = result.get("turns", [])
            return json.dumps(
                {
                    "session_id": result.get("id", ""),
                    "session_title": result.get("session_title", ""),
                    "session_summary": result.get("session_summary", ""),
                    "started_at": result.get("started_at", ""),
                    "ended_at": result.get("ended_at"),
                    "total_turns": result.get("total_turns", 0),
                    "repo_name": result.get("repo_name", ""),
                    "repo_path": result.get("repo_path", ""),
                    "recent_turns": [
                        {
                            "id": t.get("id", ""),
                            "turn_number": t.get("turn_number", 0),
                            "user_message": t.get("user_message", ""),
                            "assistant_summary": t.get("assistant_summary", ""),
                            "timestamp": t.get("timestamp", ""),
                        }
                        for t in turns
                    ],
                    "warnings": warnings,
                }
            )

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
        repos: list[str] | None = None,
    ) -> str:
        """Get human/agent attribution for a file.

        Args:
            file_path: Path to the file
            start_line: Start line number (optional)
            end_line: End line number (optional)
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_attribution

            repo_names = None if repos == ["*"] else repos
            results, warnings = cross_repo_attribution(
                file_path, start_line, end_line, repos=repo_names, include_warnings=True
            )
            attributions = []
            for r in results:
                attributions.append(
                    {
                        "start_line": r.get("start_line"),
                        "end_line": r.get("end_line"),
                        "type": r.get("attribution_type", ""),
                        "agent_name": r.get("agent_name"),
                        "session_id": r.get("session_id", ""),
                        "turn_id": r.get("turn_id", ""),
                        "confidence": r.get("confidence"),
                        "repo_name": r.get("repo_name", ""),
                        "repo_path": r.get("repo_path", ""),
                    }
                )
            return json.dumps({"file_path": file_path, "attributions": attributions, "warnings": warnings})

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
    async def ec_rewind(
        checkpoint_id: str,
        repos: list[str] | None = None,
    ) -> str:
        """Show state at a checkpoint.

        Args:
            checkpoint_id: The checkpoint ID to examine
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_rewind

            repo_names = None if repos == ["*"] else repos
            result, warnings = cross_repo_rewind(checkpoint_id, repos=repo_names, include_warnings=True)
            if not result:
                return json.dumps({"error": f"Checkpoint not found: {checkpoint_id}", "warnings": warnings})
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
        limit: int = 20,
        repos: list[str] | None = None,
    ) -> str:
        """Find related sessions and turns to current work.

        Args:
            query: Search query (optional)
            files: List of file paths to find related sessions (optional)
            limit: Maximum number of results (default 20)
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_related

            repo_names = None if repos == ["*"] else repos
            results, warnings = cross_repo_related(
                query=query, files=files, repos=repo_names, limit=limit, include_warnings=True
            )
            related = []
            for r in results:
                related.append(
                    {
                        "type": "turn",
                        "id": r.get("id", ""),
                        "session_id": r.get("session_id", ""),
                        "summary": r.get("assistant_summary") or r.get("user_message", ""),
                        "timestamp": r.get("timestamp", ""),
                        "repo_name": r.get("repo_name", ""),
                        "repo_path": r.get("repo_path", ""),
                    }
                )
            return json.dumps({"related": related, "count": len(related), "warnings": warnings})

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

            return json.dumps({"related": unique_results[:limit], "count": len(unique_results[:limit])})
        finally:
            conn.close()

    @mcp.tool()
    async def ec_turn_content(
        turn_id: str,
        repos: list[str] | None = None,
    ) -> str:
        """Get full content for a specific turn.

        Args:
            turn_id: The turn ID to retrieve content for
            repos: Repo filter — None=current repo, ["*"]=all repos, ["name"]=specific repos
        """
        import json

        if repos is not None:
            from ..core.cross_repo import cross_repo_turn_content

            repo_names = None if repos == ["*"] else repos
            result, warnings = cross_repo_turn_content(turn_id, repos=repo_names, include_warnings=True)
            if not result:
                return json.dumps({"error": f"Turn not found: {turn_id}", "warnings": warnings})
            return json.dumps(
                {
                    "turn_id": result.get("id", ""),
                    "session_id": result.get("session_id", ""),
                    "turn_number": result.get("turn_number", 0),
                    "user_message": result.get("user_message", ""),
                    "assistant_summary": result.get("assistant_summary", ""),
                    "timestamp": result.get("timestamp", ""),
                    "content": result.get("content"),
                    "content_path": result.get("content_path"),
                    "repo_name": result.get("repo_name", ""),
                    "repo_path": result.get("repo_path", ""),
                    "warnings": warnings,
                }
            )

        conn, repo_path = _get_repo_db()
        if not conn:
            return json.dumps({"error": "Not in an EntireContext-initialized repo"})

        try:
            from ..core.turn import get_turn

            turn = get_turn(conn, turn_id)
            if not turn:
                return json.dumps({"error": f"Turn not found: {turn_id}"})

            content_row = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_id,)).fetchone()

            content = None
            content_path = None
            if content_row:
                content_path = content_row["content_path"]
                from ..core.cross_repo import resolve_content_path

                full_path = resolve_content_path(str(repo_path), content_path)
                if full_path.exists():
                    content = full_path.read_text(encoding="utf-8")

            return json.dumps(
                {
                    "turn_id": turn["id"],
                    "session_id": turn["session_id"],
                    "turn_number": turn.get("turn_number", 0),
                    "user_message": turn.get("user_message", ""),
                    "assistant_summary": turn.get("assistant_summary", ""),
                    "timestamp": turn.get("timestamp", ""),
                    "content": content,
                    "content_path": content_path,
                }
            )
        finally:
            conn.close()


def run_server():
    """Run the MCP server (stdio transport)."""
    if mcp is None:
        print("MCP not available. Install with: pip install 'entirecontext[mcp]'")
        return
    mcp.run()
