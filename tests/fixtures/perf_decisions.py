"""Synthetic decision corpus for PDI performance measurement (PR-D).

Seeds an in-memory SQLite DB with N decisions covering a realistic
distribution of scopes, file associations, and staleness statuses.
Call `seed_perf_db(conn, n)` after bootstrapping the schema.
"""

from __future__ import annotations

import random
import sqlite3
from uuid import uuid4

_FILE_POOL = [
    "src/entirecontext/core/decisions.py",
    "src/entirecontext/core/decision_extraction.py",
    "src/entirecontext/core/decision_prompt_surfacing.py",
    "src/entirecontext/hooks/handler.py",
    "src/entirecontext/hooks/turn_capture.py",
    "src/entirecontext/hooks/session_lifecycle.py",
    "src/entirecontext/cli/session_cmds.py",
    "src/entirecontext/cli/decision_cmds.py",
    "src/entirecontext/db/migration.py",
    "src/entirecontext/db/connection.py",
    "src/entirecontext/core/config.py",
    "src/entirecontext/core/context.py",
    "src/entirecontext/core/search.py",
    "src/entirecontext/core/telemetry.py",
    "src/entirecontext/core/export.py",
    "tests/test_decisions.py",
    "tests/test_handler.py",
    "tests/test_decision_extraction.py",
    "pyproject.toml",
    "CHANGELOG.md",
]

_TITLES_KO = [
    "결정 추출 신뢰도 임계값 설정",
    "SessionEnd 훅 타임아웃 정책",
    "accepted_boost 대칭 경로 도입",
    "FTS5 전문 검색 인덱스 설계",
    "PDI 동기 경로 기본값 결정",
    "outcome 피드백 lookback 기간",
    "SQLite WAL 모드 적용 이유",
    "turn content JSONL 하이브리드 저장",
    "MCP 서버 재시작 정책",
    "랭킹 가중치 기본값 캘리브레이션",
]
_TITLES_EN = [
    "Ranker weight calibration for file-signal dominance",
    "Decision scope taxonomy — three tiers",
    "Supersede chain collapse policy",
    "Rejected-alternative normalization format",
    "Context budget optimizer token heuristic",
    "FTS5 rank signal weight vs file-match signal",
    "Hook protocol: stdin JSON, stdout JSON",
    "Schema version policy — migration-only forward",
    "Confidence score clamp at [0, 1]",
    "Staleness factor multiplicative vs additive",
]
_SCOPES = ["core", "hooks", "cli", "db", "config", "testing", "docs", "mcp", "sync"]
_STATUSES = ["fresh"] * 7 + ["stale"] * 2 + ["superseded"] * 1


def seed_perf_db(conn: sqlite3.Connection, n: int, *, rng_seed: int = 0) -> list[str]:
    """Insert n synthetic decisions; return list of inserted IDs."""
    rng = random.Random(rng_seed)
    titles = _TITLES_KO + _TITLES_EN
    ids: list[str] = []

    for i in range(n):
        did = str(uuid4())
        title = f"{rng.choice(titles)} #{i}"
        rationale = f"Rationale for decision {i}. " * rng.randint(2, 6)
        scope = rng.choice(_SCOPES)
        status = rng.choice(_STATUSES)
        ts = f"2026-0{rng.randint(1, 5)}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:00:00Z"
        conn.execute(
            """INSERT INTO decisions (
                id, title, rationale, scope, staleness_status,
                rejected_alternatives, supporting_evidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (did, title, rationale, scope, status, "[]", "[]", ts, ts),
        )
        # Link 0–3 files per decision
        for fp in rng.sample(_FILE_POOL, rng.randint(0, 3)):
            conn.execute(
                "INSERT INTO decision_files (decision_id, file_path, added_at) VALUES (?, ?, ?)",
                (did, fp, ts),
            )
        ids.append(did)

    conn.commit()
    return ids
