"""Focused unit tests for DEFAULT_CONFIG values."""

from __future__ import annotations


def test_capture_ranking_snapshots_default_false():
    from entirecontext.core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["decisions"]["capture_ranking_snapshots"] is False


def test_ranking_snapshot_retention_days_default():
    from entirecontext.core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["decisions"]["ranking_snapshot_retention_days"] == 90
