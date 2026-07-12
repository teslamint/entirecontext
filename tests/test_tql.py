"""Unit tests for core/tql.py — temporal ref resolution and filter injection."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from entirecontext.core.tql import TQLContext, TQLError, apply_temporal_filters, resolve_temporal_ref


class TestResolveTemporalRef:
    def test_resolve_iso_date(self):
        ts, is_date = resolve_temporal_ref("2026-04-01")
        assert ts == "2026-04-01 00:00:00"
        assert is_date is True

    def test_resolve_iso_datetime_with_tz(self):
        ts, is_date = resolve_temporal_ref("2026-04-01T15:30:00+09:00")
        assert ts == "2026-04-01 06:30:00"
        assert is_date is False

    def test_resolve_iso_datetime_utc(self):
        ts, is_date = resolve_temporal_ref("2026-04-01T12:00:00+00:00")
        assert ts == "2026-04-01 12:00:00"
        assert is_date is False

    def test_resolve_iso_datetime_naive(self):
        ts, is_date = resolve_temporal_ref("2026-04-01T12:00:00")
        assert ts == "2026-04-01 12:00:00"
        assert is_date is False

    def test_resolve_git_ref(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="2026-03-15T10:30:00+00:00\n", stderr=""
        )
        with patch("subprocess.run", return_value=fake_result):
            ts, is_date = resolve_temporal_ref("v0.8.0", repo_path="/tmp/repo")
        assert ts == "2026-03-15 10:30:00"
        assert is_date is False

    def test_resolve_git_ref_with_offset(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="2026-05-20T18:00:00+09:00\n", stderr=""
        )
        with patch("subprocess.run", return_value=fake_result):
            ts, is_date = resolve_temporal_ref("main", repo_path="/tmp/repo")
        assert ts == "2026-05-20 09:00:00"
        assert is_date is False

    def test_resolve_invalid_ref_no_repo(self):
        with pytest.raises(TQLError, match="Cannot resolve"):
            resolve_temporal_ref("not-a-ref-or-date")

    def test_resolve_invalid_ref_with_repo(self, tmp_path):
        with pytest.raises(TQLError, match="Cannot resolve"):
            resolve_temporal_ref("nonexistent-branch", repo_path=str(tmp_path))

    def test_resolve_git_ref_no_repo_path(self):
        with pytest.raises(TQLError):
            resolve_temporal_ref("v1.0.0")


class TestTQLContext:
    def test_validated_success(self):
        ctx = TQLContext.validated(since="2026-01-01 00:00:00", until="2026-12-31 00:00:00")
        assert ctx.since == "2026-01-01 00:00:00"
        assert ctx.until == "2026-12-31 00:00:00"

    def test_validated_empty_range(self):
        with pytest.raises(TQLError, match="Empty time range"):
            TQLContext.validated(since="2026-05-01 00:00:00", until="2026-04-01 00:00:00")

    def test_validated_since_only(self):
        ctx = TQLContext.validated(since="2026-01-01 00:00:00")
        assert ctx.since == "2026-01-01 00:00:00"
        assert ctx.until is None

    def test_validated_until_only(self):
        ctx = TQLContext.validated(until="2026-12-31 00:00:00")
        assert ctx.since is None
        assert ctx.until == "2026-12-31 00:00:00"


class TestApplyTemporalFilters:
    def test_since_only(self):
        conditions: list[str] = []
        params: list = []
        tql = TQLContext(since="2026-01-01 00:00:00")
        apply_temporal_filters(conditions, params, tql, "t.timestamp")
        assert len(conditions) == 1
        assert "datetime(t.timestamp) >= datetime(?)" in conditions[0]
        assert params == ["2026-01-01 00:00:00"]

    def test_until_exclusive(self):
        conditions: list[str] = []
        params: list = []
        tql = TQLContext(until="2026-04-01 00:00:00", until_exclusive=True)
        apply_temporal_filters(conditions, params, tql, "d.created_at")
        assert len(conditions) == 1
        assert "datetime(d.created_at) < datetime(?)" in conditions[0]
        assert "<=" not in conditions[0]
        assert params == ["2026-04-01 00:00:00"]

    def test_until_inclusive(self):
        conditions: list[str] = []
        params: list = []
        tql = TQLContext(until="2026-04-01 15:30:00", until_exclusive=False)
        apply_temporal_filters(conditions, params, tql, "d.created_at")
        assert len(conditions) == 1
        assert "datetime(d.created_at) <= datetime(?)" in conditions[0]
        assert params == ["2026-04-01 15:30:00"]

    def test_both_bounds(self):
        conditions: list[str] = []
        params: list = []
        tql = TQLContext(since="2026-01-01 00:00:00", until="2026-06-01 00:00:00")
        apply_temporal_filters(conditions, params, tql, "t.timestamp")
        assert len(conditions) == 2
        assert "datetime(t.timestamp) >= datetime(?)" in conditions[0]
        assert "datetime(t.timestamp) <= datetime(?)" in conditions[1]
        assert params == ["2026-01-01 00:00:00", "2026-06-01 00:00:00"]

    def test_none_tql(self):
        conditions: list[str] = []
        params: list = []
        apply_temporal_filters(conditions, params, None, "t.timestamp")
        assert conditions == []
        assert params == []
