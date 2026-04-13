"""Migration to schema v12 (decision auto-promotion reset baseline)."""


def _add_auto_promotion_reset_at(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
    if "auto_promotion_reset_at" not in cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN auto_promotion_reset_at TEXT")


MIGRATION_STEPS = [
    _add_auto_promotion_reset_at,
]
