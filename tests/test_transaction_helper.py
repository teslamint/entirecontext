"""Regression pins for ``entirecontext.core.context.transaction``.

These tests lock down the helper's behavior under autocommit mode — the
mode ``_configure_connection`` enables on every real ``RepoContext.conn``.
Under autocommit, each DML self-commits unless an explicit ``BEGIN`` is
open. The helper owns ``BEGIN IMMEDIATE`` on outer entry, defers to an
outer owner via a per-connection depth counter on nested entry, and
issues ``COMMIT``/``ROLLBACK`` only when the depth returns to 0.

Assertions are behavioral (post-conditions on table state and on the
depth counter). The depth counter is technically an implementation
detail; tests probe it sparingly to surface helper-internal regressions.
"""

from __future__ import annotations

import pytest

from entirecontext.core.context import transaction
from entirecontext.db.connection import get_memory_db


@pytest.fixture()
def conn():
    c = get_memory_db()
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    yield c
    c.close()


def test_happy_path_commits_on_normal_exit(conn):
    with transaction(conn):
        conn.execute("INSERT INTO t (v) VALUES (?)", ("alpha",))
    rows = conn.execute("SELECT v FROM t ORDER BY id").fetchall()
    assert [r["v"] for r in rows] == ["alpha"]
    assert getattr(conn, "_ec_tx_depth", 0) == 0


def test_nested_defers_to_outer_owner(conn):
    with transaction(conn):
        conn.execute("INSERT INTO t (v) VALUES (?)", ("outer",))
        with transaction(conn):
            conn.execute("INSERT INTO t (v) VALUES (?)", ("inner",))
            assert getattr(conn, "_ec_tx_depth", 0) == 2
        assert getattr(conn, "_ec_tx_depth", 0) == 1
    rows = conn.execute("SELECT v FROM t ORDER BY id").fetchall()
    assert [r["v"] for r in rows] == ["outer", "inner"]
    assert getattr(conn, "_ec_tx_depth", 0) == 0


def test_exception_rolls_back_owned_boundary(conn):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with transaction(conn):
            conn.execute("INSERT INTO t (v) VALUES (?)", ("rolled-back",))
            raise Boom()

    rows = conn.execute("SELECT v FROM t").fetchall()
    assert rows == []
    assert getattr(conn, "_ec_tx_depth", 0) == 0
