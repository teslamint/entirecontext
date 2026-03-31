"""Migration to schema v11 (FTS5 for decisions + superseded_by_id column)."""


def _add_superseded_by_id(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
    if "superseded_by_id" not in cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN superseded_by_id TEXT REFERENCES decisions(id) ON DELETE SET NULL")


MIGRATION_STEPS = [
    _add_superseded_by_id,
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_decisions USING fts5(
        title,
        rationale,
        content='decisions',
        content_rowid='rowid'
    )""",
    """CREATE TRIGGER IF NOT EXISTS fts_decisions_ai AFTER INSERT ON decisions BEGIN
      INSERT INTO fts_decisions(rowid, title, rationale)
      VALUES (new.rowid, new.title, new.rationale);
    END""",
    """CREATE TRIGGER IF NOT EXISTS fts_decisions_ad AFTER DELETE ON decisions BEGIN
      INSERT INTO fts_decisions(fts_decisions, rowid, title, rationale)
      VALUES ('delete', old.rowid, old.title, old.rationale);
    END""",
    """CREATE TRIGGER IF NOT EXISTS fts_decisions_au AFTER UPDATE ON decisions BEGIN
      INSERT INTO fts_decisions(fts_decisions, rowid, title, rationale)
      VALUES ('delete', old.rowid, old.title, old.rationale);
      INSERT INTO fts_decisions(rowid, title, rationale)
      VALUES (new.rowid, new.title, new.rationale);
    END""",
    lambda conn: conn.execute(
        "INSERT INTO fts_decisions(rowid, title, rationale) SELECT rowid, title, rationale FROM decisions"
    ),
]
