"""Code AST-based semantic search — Python symbol indexing and querying.

Parses Python source files using the standard-library ``ast`` module to
extract function, class, and method definitions.  Extracted symbols are
stored in the ``ast_symbols`` table and indexed with an FTS5 virtual table
(``fts_ast_symbols``) for full-text search across names and docstrings.

No external dependencies — pure standard library (ast, json, uuid).

Typical usage::

    # Index a file (e.g. from a turn post-processor)
    index_file_ast(conn, "src/auth.py", source_code, turn_id=turn["id"])

    # Search symbols
    results = search_ast_symbols(conn, "authenticate user")
    for r in results:
        print(r["qualified_name"], r["file_path"], r["start_line"])
"""

from __future__ import annotations

import ast
import json
from uuid import uuid4


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    """Return a list of decorator name strings for *node*.

    Dotted names (e.g. ``@functools.lru_cache``) are stored with their full
    qualified path so that ``@module.cache`` and ``@other.cache`` remain
    distinguishable.
    """

    def _name_from_expr(expr: ast.expr) -> str:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            parent = _name_from_expr(expr.value)
            return f"{parent}.{expr.attr}" if parent else expr.attr
        return ""

    names: list[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            name = _name_from_expr(dec.func)
        else:
            name = _name_from_expr(dec)
        if name:
            names.append(name)
    return names


def _get_docstring(node: ast.AST) -> str | None:
    """Return the first-line docstring for *node*, or None."""
    doc = ast.get_docstring(node, clean=True)
    return doc or None


def extract_ast_symbols(source_code: str, file_path: str) -> list[dict]:
    """Parse *source_code* and extract all function, class, and method definitions.

    Args:
        source_code: Python source as a string.
        file_path: Path label stored on each returned symbol (not accessed on disk).

    Returns:
        A list of dicts, one per symbol, with keys:

        ``name``           Symbol name (e.g. ``"authenticate"``).
        ``qualified_name`` Dot-qualified path (e.g. ``"AuthClass.authenticate"``).
        ``symbol_type``    One of ``"function"``, ``"class"``, ``"method"``.
        ``file_path``      The *file_path* argument as provided.
        ``start_line``     First line number (1-based).
        ``end_line``       Last line number (1-based).
        ``docstring``      Docstring text or ``None``.
        ``decorators``     List of decorator name strings.
        ``parent_name``    Enclosing class name for methods; ``None`` otherwise.

    Returns an empty list if *source_code* is empty or contains a syntax error.
    """
    if not source_code or not source_code.strip():
        return []

    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError:
        return []

    symbols: list[dict] = []

    def _visit_class(class_node: ast.ClassDef, parent_qualname: str | None = None) -> None:
        qualname = f"{parent_qualname}.{class_node.name}" if parent_qualname else class_node.name
        symbols.append(
            {
                "name": class_node.name,
                "qualified_name": qualname,
                "symbol_type": "class",
                "file_path": file_path,
                "start_line": class_node.lineno,
                "end_line": class_node.end_lineno or class_node.lineno,
                "docstring": _get_docstring(class_node),
                "decorators": _decorator_names(class_node),
                "parent_name": parent_qualname,
            }
        )
        # Extract methods and recurse into nested classes
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    {
                        "name": item.name,
                        "qualified_name": f"{qualname}.{item.name}",
                        "symbol_type": "method",
                        "file_path": file_path,
                        "start_line": item.lineno,
                        "end_line": item.end_lineno or item.lineno,
                        "docstring": _get_docstring(item),
                        "decorators": _decorator_names(item),
                        "parent_name": qualname,
                    }
                )
            elif isinstance(item, ast.ClassDef):
                _visit_class(item, parent_qualname=qualname)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                {
                    "name": node.name,
                    "qualified_name": node.name,
                    "symbol_type": "function",
                    "file_path": file_path,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "docstring": _get_docstring(node),
                    "decorators": _decorator_names(node),
                    "parent_name": None,
                }
            )
        elif isinstance(node, ast.ClassDef):
            _visit_class(node)

    return symbols


def index_file_ast(
    conn,
    file_path: str,
    source_code: str,
    *,
    turn_id: str | None = None,
    git_commit_hash: str | None = None,
) -> list[dict]:
    """Parse *source_code* and store its symbols in the ``ast_symbols`` table.

    Existing records for *file_path* are deleted before inserting new ones
    so that re-indexing is idempotent (replaces, never duplicates).

    Args:
        conn: SQLite connection.
        file_path: Canonical file path used as the grouping key.
        source_code: Python source string to parse.
        turn_id: Optional FK to ``turns.id`` linking the indexing event.
        git_commit_hash: Optional git commit hash at index time.

    Returns:
        The list of symbol dicts that were inserted (may be empty).
    """
    # Remove all existing symbols for this file (idempotent re-index)
    conn.execute("DELETE FROM ast_symbols WHERE file_path = ?", (file_path,))

    symbols = extract_ast_symbols(source_code, file_path)
    for sym in symbols:
        conn.execute(
            """INSERT INTO ast_symbols
               (id, file_path, symbol_type, name, qualified_name,
                start_line, end_line, docstring, decorators, parent_name,
                turn_id, git_commit_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                file_path,
                sym["symbol_type"],
                sym["name"],
                sym["qualified_name"],
                sym["start_line"],
                sym["end_line"],
                sym["docstring"],
                json.dumps(sym["decorators"]) if sym["decorators"] else None,
                sym["parent_name"],
                turn_id,
                git_commit_hash,
            ),
        )
    conn.commit()  # commit the DELETE + INSERT batch atomically
    return symbols


def get_ast_symbols_for_file(
    conn,
    file_path: str,
    *,
    symbol_type: str | None = None,
) -> list[dict]:
    """Return all indexed symbols for *file_path*.

    Args:
        conn: SQLite connection.
        file_path: Exact file path to look up.
        symbol_type: Optional filter: ``"function"``, ``"class"``, or ``"method"``.

    Returns:
        List of symbol dicts sorted by ``start_line``.
    """
    if symbol_type:
        rows = conn.execute(
            "SELECT * FROM ast_symbols WHERE file_path = ? AND symbol_type = ? ORDER BY start_line",
            (file_path, symbol_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ast_symbols WHERE file_path = ? ORDER BY start_line",
            (file_path,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_ast_symbols(
    conn,
    query: str,
    *,
    symbol_type: str | None = None,
    file_filter: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search over indexed AST symbols.

    Searches ``name``, ``qualified_name``, ``docstring``, and ``file_path``
    using the ``fts_ast_symbols`` FTS5 virtual table.

    Args:
        conn: SQLite connection.
        query: Search query string (FTS5 syntax supported).
        symbol_type: Optional filter: ``"function"``, ``"class"``, or ``"method"``.
        file_filter: Optional exact file path filter.
        limit: Maximum number of results (default 20).

    Returns:
        List of matching symbol dicts, ordered by FTS5 relevance.
    """
    if not query or not query.strip():
        return []

    # Escape FTS5 special chars in query for safety; wrap in quotes for phrase search
    safe_query = query.replace('"', '""')

    params: list = [f'"{safe_query}"']
    where_clauses: list[str] = []

    if symbol_type:
        where_clauses.append("s.symbol_type = ?")
        params.append(symbol_type)
    if file_filter:
        where_clauses.append("s.file_path = ?")
        params.append(file_filter)

    # Additional filters are AND-conditions after the FTS MATCH clause
    extra_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    import sqlite3

    try:
        rows = conn.execute(
            f"""SELECT s.*
                FROM ast_symbols s
                JOIN fts_ast_symbols fts ON fts.rowid = s.rowid
                WHERE fts_ast_symbols MATCH ?
                {extra_sql}
                ORDER BY rank
                LIMIT ?""",
            params + [limit],
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS table not yet initialised or query syntax error
        return []

    return [dict(r) for r in rows]
