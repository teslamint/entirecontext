"""Ratchet test: ban new internal ``conn.commit()`` calls in ``core/``.

The retrospective (v0.2.0) found that helpers across ``src/entirecontext/core``
silently take transaction ownership from their callers by calling
``conn.commit()`` internally. The fix pattern is to own a ``BEGIN IMMEDIATE``
boundary via ``entirecontext.core.context.transaction`` and let nesting defer
commit to the outer owner. This test locks down progress on that cleanup.

**Allowlist semantics.** The test records the set of ``core/*.py`` modules that
currently contain at least one ``conn.commit()`` call. New PRs may not add
``conn.commit()`` to any module outside that set. As each allowlisted module is
cleaned up (its last ``conn.commit()`` replaced by a ``with transaction(conn):``
owner), it must be *removed* from the allowlist so the ratchet tightens.

**Known granularity limitation.** The allowlist is *file-level*, not
function-level. A second ``conn.commit()`` added inside an already-allowlisted
file will NOT fail this test. A stronger form would key on ``(file, function)``
pairs or require a ``# transaction_owner`` marker at each legitimate commit
site, but file-level is the minimum viable ratchet. Tighten later.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Files that CURRENTLY contain at least one ``conn.commit()`` in
# ``src/entirecontext/core/``. This set is a ratchet: it may SHRINK over time,
# never grow. When a PR lands that removes the last ``conn.commit()`` from one
# of these modules, drop it from the set in the same PR.
ALLOWLIST = frozenset(
    {
        "agent_graph.py",
        "attribution.py",
        "checkpoint.py",
        "consolidation.py",
        "decision_candidates.py",
        "decision_extraction.py",
        "decisions.py",
        "event.py",
        "futures.py",
        "project.py",
        "purge.py",
        "session.py",
        "telemetry.py",
        "turn.py",
    }
)

CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "entirecontext" / "core"


def _commit_call_locations(path: Path) -> list[int]:
    """Return line numbers of ``<receiver>.commit()`` zero-arg calls in ``path``.

    Matches any attribute call whose attr is ``commit`` and carries no arguments.
    That catches the common bindings (``conn.commit()``, ``ec_conn.commit()``,
    ``self.conn.commit()``) without requiring every helper to use the same
    parameter name. The price is that it also matches non-sqlite commit calls
    (e.g., a hypothetical ``transaction.commit()``), which is acceptable: this
    check runs only on ``core/*.py``, where the relevant receivers are all
    sqlite connections.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "commit" and not node.args and not node.keywords:
            hits.append(node.lineno)
    return hits


def test_no_new_conn_commit_in_core():
    violations: list[str] = []
    cleaned: list[str] = []

    # ``context.py`` is THE transaction owner module — the helper's implementation
    # calls ``conn.commit()`` by design. Skip it so the ratchet doesn't flag the fix.
    exempt = {"__init__.py", "context.py"}

    for py in sorted(CORE_DIR.glob("*.py")):
        if py.name in exempt:
            continue
        hits = _commit_call_locations(py)
        if hits and py.name not in ALLOWLIST:
            for line in hits:
                violations.append(f"{py.name}:{line} — new `conn.commit()` not allowed in core/")
        elif not hits and py.name in ALLOWLIST:
            cleaned.append(py.name)

    messages: list[str] = []
    if violations:
        messages.append(
            "New `conn.commit()` calls found in core/ modules outside the ratchet allowlist. "
            "Use `with transaction(conn):` from `entirecontext.core.context` to own the boundary:\n  "
            + "\n  ".join(violations)
        )
    if cleaned:
        messages.append(
            "The following files no longer contain `conn.commit()` and must be REMOVED from "
            "ALLOWLIST in this file (ratchet tightening):\n  " + "\n  ".join(cleaned)
        )

    assert not messages, "\n\n".join(messages)
