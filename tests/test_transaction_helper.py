"""Regression pins for ``entirecontext.core.context.transaction``.

These tests lock down the helper's behavior under Python 3.12's
``LEGACY_TRANSACTION_CONTROL`` mode — the same mode ``_configure_connection``
leaves on every real ``RepoContext.conn``. If a future runtime migration to
``autocommit=True`` lands without updating the helper, these cases will fail
and surface the semantic change before silent atomicity regressions ship.
"""

from __future__ import annotations

import pytest

from entirecontext.core.context import transaction
from entirecontext.db.connection import get_memory_db


@pytest.fixture()
def conn():
    c = get_memory_db()
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    c.commit()
    yield c
    c.close()


def test_happy_path_commits_on_normal_exit(conn):
    with transaction(conn):
        conn.execute("INSERT INTO t (v) VALUES (?)", ("alpha",))
    assert conn.in_transaction is False
    rows = conn.execute("SELECT v FROM t ORDER BY id").fetchall()
    assert [r["v"] for r in rows] == ["alpha"]


def test_nested_defers_to_outer_owner(conn):
    conn.execute("INSERT INTO t (v) VALUES (?)", ("outer",))
    assert conn.in_transaction is True

    with transaction(conn):
        conn.execute("INSERT INTO t (v) VALUES (?)", ("inner",))

    # Nested path must not commit — outer still owns the boundary.
    assert conn.in_transaction is True
    conn.commit()

    rows = conn.execute("SELECT v FROM t ORDER BY id").fetchall()
    assert [r["v"] for r in rows] == ["outer", "inner"]


def test_exception_rolls_back_owned_boundary(conn):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with transaction(conn):
            conn.execute("INSERT INTO t (v) VALUES (?)", ("rolled-back",))
            raise Boom()

    assert conn.in_transaction is False
    rows = conn.execute("SELECT v FROM t").fetchall()
    assert rows == []
