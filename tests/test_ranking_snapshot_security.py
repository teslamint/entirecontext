"""Seeded-secret regression: planted tokens must never reach ranking_snapshots."""

from entirecontext.core.decisions import (
    create_decision,
    link_decision_to_file,
    rank_related_decisions,
)


def test_seeded_secret_never_stored(ec_db):
    """A planted API key in diff_text must be redacted before snapshot storage."""
    conn = ec_db

    decision = create_decision(conn, title="secret test", rationale="test", scope="module")
    link_decision_to_file(conn, decision["id"], "src/config.py")

    planted_secrets = [
        "sk-proj-ABCDEF1234567890abcdef",
        "ghp_1234567890abcdefABCDEF1234567890abcd",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature",
    ]
    diff_with_secrets = "\n".join(
        f"+API_KEY = '{s}'" for s in planted_secrets
    )

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/config.py"],
        diff_text=diff_with_secrets,
        _return_stats=True,
        _capture_snapshots=True,
    )

    assert "snapshot_id" in stats

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()

    stored_text = row["input_diff_text"] or ""
    for secret in planted_secrets:
        assert secret not in stored_text, f"Secret leaked into snapshot: {secret[:20]}..."

    assert "[REDACTED]" in stored_text
