"""Migration to schema v6."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS ast_symbols (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL,
        symbol_type TEXT NOT NULL,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        docstring TEXT,
        decorators TEXT,
        parent_name TEXT,
        turn_id TEXT,
        git_commit_hash TEXT,
        indexed_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ast_file ON ast_symbols(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_ast_name ON ast_symbols(name)",
    "CREATE INDEX IF NOT EXISTS idx_ast_type ON ast_symbols(symbol_type)",
    "CREATE INDEX IF NOT EXISTS idx_ast_turn ON ast_symbols(turn_id)",
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_ast_symbols USING fts5(
        name,
        qualified_name,
        docstring,
        file_path,
        content='ast_symbols',
        content_rowid='rowid'
    )""",
    """CREATE TRIGGER IF NOT EXISTS fts_ast_symbols_ai AFTER INSERT ON ast_symbols BEGIN
      INSERT INTO fts_ast_symbols(rowid, name, qualified_name, docstring, file_path)
      VALUES (new.rowid, new.name, new.qualified_name, new.docstring, new.file_path);
    END""",
    """CREATE TRIGGER IF NOT EXISTS fts_ast_symbols_ad AFTER DELETE ON ast_symbols BEGIN
      INSERT INTO fts_ast_symbols(fts_ast_symbols, rowid, name, qualified_name, docstring, file_path)
      VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docstring, old.file_path);
    END""",
    """CREATE TRIGGER IF NOT EXISTS fts_ast_symbols_au AFTER UPDATE ON ast_symbols BEGIN
      INSERT INTO fts_ast_symbols(fts_ast_symbols, rowid, name, qualified_name, docstring, file_path)
      VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docstring, old.file_path);
      INSERT INTO fts_ast_symbols(rowid, name, qualified_name, docstring, file_path)
      VALUES (new.rowid, new.name, new.qualified_name, new.docstring, new.file_path);
    END""",
]
