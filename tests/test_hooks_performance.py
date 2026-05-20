"""PR-D: PDI performance baseline measurement.

Measures rank_related_decisions p50/p95 across 100/500/1000 decision corpora.
Gate: p95 < 250ms at 1000 decisions → default inject_on_user_prompt = true.

Results are written to docs/perf/v0-7-0-pdi-baseline.md when the env var
RECORD_PERF=1 is set (CI skips writing; local measurement run produces the doc).

Usage:
    RECORD_PERF=1 uv run pytest tests/test_hooks_performance.py -s -v
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from statistics import median, quantiles

import pytest

from tests.fixtures.perf_decisions import seed_perf_db

REPO_ROOT = Path(__file__).parent.parent
PERF_DOC = REPO_ROOT / "docs" / "perf" / "v0-7-0-pdi-baseline.md"

_SAMPLE_DIFF = """\
diff --git a/src/entirecontext/hooks/handler.py b/src/entirecontext/hooks/handler.py
index abc1234..def5678 100644
--- a/src/entirecontext/hooks/handler.py
+++ b/src/entirecontext/hooks/handler.py
@@ -90,6 +90,28 @@ def _handle_user_prompt(data: dict) -> int:
+    # PDI sync path: rank decisions and inject as additionalContext
+    from .turn_capture import on_user_prompt
+    on_user_prompt(data)
+    return 0
diff --git a/src/entirecontext/core/decisions.py b/src/entirecontext/core/decisions.py
index 1234567..abcdef0 100644
--- a/src/entirecontext/core/decisions.py
+++ b/src/entirecontext/core/decisions.py
@@ -1308,6 +1308,8 @@ def rank_related_decisions(
+    # New: extract rank_decisions_for_prompt for PDI sync path
+    pass
"""

_SAMPLE_FILES = [
    "src/entirecontext/hooks/handler.py",
    "src/entirecontext/core/decisions.py",
    "src/entirecontext/core/decision_prompt_surfacing.py",
    "src/entirecontext/hooks/turn_capture.py",
    "src/entirecontext/cli/session_cmds.py",
    "src/entirecontext/db/migration.py",
    "src/entirecontext/core/config.py",
    "src/entirecontext/core/context.py",
    "tests/test_handler.py",
    "tests/test_decisions.py",
]

_SAMPLE_COMMITS = [f"abc{i:04x}def{i:04x}0000000000000000" for i in range(10)]

_REPETITIONS = 20
_SIZES = [100, 500, 1000]


def _make_perf_db(n: int):
    from entirecontext.db.connection import get_memory_db
    from entirecontext.db.migration import bootstrap_schema

    conn = get_memory_db()
    bootstrap_schema(conn)
    seed_perf_db(conn, n)
    return conn


def _measure(conn) -> list[float]:
    from entirecontext.core.decisions import rank_related_decisions

    timings: list[float] = []
    for _ in range(_REPETITIONS):
        t0 = time.perf_counter()
        rank_related_decisions(
            conn,
            file_paths=_SAMPLE_FILES,
            diff_text=_SAMPLE_DIFF,
            commit_shas=_SAMPLE_COMMITS,
            assessment_ids=[],
            limit=10,
            include_contradicted=False,
        )
        timings.append((time.perf_counter() - t0) * 1000)
    return timings


class TestPDIPerformanceBaseline:
    """Quantitative gate: rank_related_decisions must stay under 250ms p95 at 1000 decisions."""

    @pytest.fixture(scope="class")
    def results(self):
        data: dict[int, dict] = {}
        for n in _SIZES:
            conn = _make_perf_db(n)
            timings = _measure(conn)
            conn.close()
            timings_sorted = sorted(timings)
            p50 = median(timings_sorted)
            p95 = quantiles(timings_sorted, n=20)[18]  # 95th percentile
            data[n] = {"p50": p50, "p95": p95, "timings": timings_sorted}
        return data

    def test_p95_under_250ms_at_100(self, results):
        p95 = results[100]["p95"]
        assert p95 < 250, f"p95@100={p95:.1f}ms ≥ 250ms"

    def test_p95_under_250ms_at_500(self, results):
        p95 = results[500]["p95"]
        assert p95 < 250, f"p95@500={p95:.1f}ms ≥ 250ms"

    def test_p95_under_250ms_at_1000(self, results):
        p95 = results[1000]["p95"]
        assert p95 < 250, f"p95@1000={p95:.1f}ms ≥ 250ms — default inject_on_user_prompt should be false"

    def test_record_results(self, results):
        """Write markdown results doc when RECORD_PERF=1."""
        if not os.getenv("RECORD_PERF"):
            pytest.skip("Set RECORD_PERF=1 to record results to docs/perf/")

        lines = [
            "# PDI Performance Baseline — v0.7.0",
            "",
            f"Measured with {_REPETITIONS} repetitions per corpus size.",
            "Input: 10 file paths + simulated diff (2 hunks) + 10 commit SHAs.",
            "",
            "## Results",
            "",
            "| Corpus size | p50 (ms) | p95 (ms) | Gate (< 250ms) |",
            "|---|---|---|---|",
        ]
        default_on = True
        for n in _SIZES:
            p50 = results[n]["p50"]
            p95 = results[n]["p95"]
            gate = "PASS ✓" if p95 < 250 else "FAIL ✗"
            if n == 1000 and p95 >= 250:
                default_on = False
            lines.append(f"| {n:,} | {p50:.1f} | {p95:.1f} | {gate} |")

        lines += [
            "",
            "## Decision",
            "",
            f"**`inject_on_user_prompt` default: `{'true' if default_on else 'false'}`**",
            "",
            (
                "p95 < 250ms at 1000 decisions → sync PDI path is fast enough for default-ON."
                if default_on
                else "p95 ≥ 250ms at 1000 decisions → default-OFF; operator opt-in via config."
            ),
            "",
            "## Raw Timings (ms)",
            "",
        ]
        for n in _SIZES:
            ts = results[n]["timings"]
            lines.append(f"### {n:,} decisions")
            lines.append(", ".join(f"{t:.1f}" for t in ts))
            lines.append("")

        PERF_DOC.parent.mkdir(parents=True, exist_ok=True)
        PERF_DOC.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nWrote perf baseline to {PERF_DOC}")
