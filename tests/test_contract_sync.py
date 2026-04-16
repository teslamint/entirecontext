"""Contract-sync tests — prevent code/doc drift on public surface area.

v0.2.0 retrospective finding #2 ('contract drift tax') identified doc/code
mismatches as a dominant source of review churn. This file guards four
surfaces:

  1. ``mcp/server.py`` ``__all__`` <-> ``register_tools()`` actual registrations
  2. ``__all__`` (ec_* subset) <-> README ``### Available Tools`` section
     (bidirectional: catches both missing rows and stale rows)
  3. ``hooks/decision_hooks`` fallback filename constants <-> README
  4. ``db/schema.SCHEMA_VERSION`` <-> ``CHANGELOG.md`` (paragraph-scoped)

REPLACES ``tests/test_mcp_registration.py``, whose hardcoded expected set
silently drifted — its registration loop omitted ``tools.decision_candidates``
AND its expected set omitted the 4 candidate tools, passing via symmetric
drift. The parity test below is strictly stronger.

IMPLICIT CONTRACT NOTE: the parity test assumes tools register via the
``mcp.tool()(fn)`` pattern with ``registered_name == fn.__name__``. The
``_FakeMCP.tool()`` honors an optional ``name=`` kwarg override (matching
real ``FastMCP.tool()``'s signature) but does NOT capture ``mcp.add_tool()``
calls. If a future registration uses either of those escape hatches, update
the fake and/or the AST extractor at that time.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
SERVER_PY = REPO_ROOT / "src" / "entirecontext" / "mcp" / "server.py"


class _FakeMCP:
    """Minimal FastMCP stand-in that captures tool-registration names.

    Honors the ``name=`` kwarg override like real ``FastMCP.tool()`` does,
    so a future ``mcp.tool(name="ec_alias")(fn)`` registration would be
    captured under the alias, not ``fn.__name__``.
    """

    def __init__(self) -> None:
        self.registered: list[str] = []

    def tool(self, *args, **kwargs):
        def decorator(fn):
            name = kwargs.get("name") or fn.__name__
            self.registered.append(name)
            return fn

        return decorator


def _extract_server_module_names() -> list[str]:
    """Return the module names in ``server.py``'s ``for module in (...)`` loop.

    Source-of-truth extraction: rather than hardcoding the tuple in this
    test (which would silently drift if ``server.py`` changes), parse the
    real file and walk for the ``For`` node whose body contains a
    ``register_tools`` call.

    If ``server.py`` is refactored so the module iterable is no longer an
    inline tuple literal (e.g., extracted into ``MODULES = (...)`` and the
    loop becomes ``for mod in MODULES:``), this extractor raises
    ``AssertionError`` with an explicit fix-forward message. Fail-loud is
    correct — the tradeoff is that this test needs updating at the same
    time as any such refactor, which is exactly the drift we're guarding
    against.
    """
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.iter, ast.Tuple):
            continue
        body_calls_register_tools = any(
            isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and stmt.func.attr == "register_tools"
            for stmt in ast.walk(node)
        )
        if not body_calls_register_tools:
            continue
        return [elt.id for elt in node.iter.elts if isinstance(elt, ast.Name)]
    raise AssertionError(
        "Could not locate a `for module in (...): module.register_tools(...)` loop "
        "in src/entirecontext/mcp/server.py. If the registration path was refactored, "
        "update _extract_server_module_names() and the docstring contract note."
    )


def _collect_registered_tools() -> set[str]:
    """Drive each tool module's ``register_tools()`` against a ``_FakeMCP``.

    The module tuple is pulled from ``server.py`` via AST, NOT hardcoded
    here, so the test follows the real registration path.
    """
    fake = _FakeMCP()
    for name in _extract_server_module_names():
        mod = importlib.import_module(f"entirecontext.mcp.tools.{name}")
        mod.register_tools(fake)
    return set(fake.registered)


def _ec_tools_in_all() -> set[str]:
    from entirecontext.mcp import server

    return {name for name in server.__all__ if name.startswith("ec_")}


def test_mcp_export_matches_registration() -> None:
    """``server.__all__`` (ec_* subset) must equal what ``register_tools()`` registers."""
    exported = _ec_tools_in_all()
    registered = _collect_registered_tools()
    missing_from_all = registered - exported
    missing_from_registration = exported - registered
    messages: list[str] = []
    if missing_from_all:
        messages.append(f"Tools registered but NOT in __all__: {sorted(missing_from_all)}")
    if missing_from_registration:
        messages.append(f"Tools in __all__ but NOT registered by any module: {sorted(missing_from_registration)}")
    assert not messages, "MCP __all__ <-> register_tools drift:\n  " + "\n  ".join(messages)


_AVAILABLE_TOOLS_PATTERN = re.compile(r"### Available Tools\n(.*?)(?=\n## |\n### |\Z)", re.DOTALL)
_EC_TOOL_BACKTICKED = re.compile(r"`(ec_\w+)`")


def test_mcp_tools_enumerated_in_readme() -> None:
    """Bidirectional: every ``__all__`` ec_* tool is in README, and every
    ec_* mentioned in the README section is in ``__all__`` (catches stale
    rows, not just missing ones)."""
    exported = _ec_tools_in_all()
    readme_text = README.read_text(encoding="utf-8")
    match = _AVAILABLE_TOOLS_PATTERN.search(readme_text)
    assert match, "README is missing the `### Available Tools` section"
    section = match.group(1)
    mentioned = set(_EC_TOOL_BACKTICKED.findall(section))
    missing_from_readme = exported - mentioned
    stale_in_readme = mentioned - exported
    messages: list[str] = []
    if missing_from_readme:
        messages.append(
            f"Tools in __all__ but missing from README `### Available Tools`: {sorted(missing_from_readme)}"
        )
    if stale_in_readme:
        messages.append(
            f"Tools in README `### Available Tools` but not in __all__ (stale docs): {sorted(stale_in_readme)}"
        )
    assert not messages, "\n".join(messages)


def test_fallback_filenames_match_readme() -> None:
    """Decision-hook fallback filename constants must be documented in README.

    Guards the PR #56 regression class where a constant was renamed in code
    but the README kept the old name.
    """
    from entirecontext.hooks.decision_hooks import (
        _POST_TOOL_FALLBACK_BASE,
        _SESSION_START_FALLBACK_NAME,
    )

    readme_text = README.read_text(encoding="utf-8")
    missing = [name for name in (_SESSION_START_FALLBACK_NAME, _POST_TOOL_FALLBACK_BASE) if name not in readme_text]
    assert not missing, f"Hook fallback filename constants missing from README: {missing}"


def test_schema_version_in_changelog() -> None:
    """CHANGELOG must mention the current ``SCHEMA_VERSION`` (``vNN``) inside
    a paragraph that also mentions 'schema' — guards against raw substring
    false-positives (``--v13-flag``, ``1v13``) while staying forgiving about
    exact phrasing."""
    from entirecontext.db.schema import SCHEMA_VERSION

    text = CHANGELOG.read_text(encoding="utf-8")
    version_tag = f"v{SCHEMA_VERSION}"
    paragraphs = re.split(r"\n\s*\n", text)
    tag_pattern = re.compile(rf"\b{re.escape(version_tag)}\b")
    schema_pattern = re.compile(r"\bschema\b", re.IGNORECASE)
    matching = [p for p in paragraphs if tag_pattern.search(p) and schema_pattern.search(p)]
    assert matching, (
        f"CHANGELOG has no paragraph containing both 'schema' and {version_tag!r} "
        f"as a whole word. Add a CHANGELOG entry describing the schema bump to v{SCHEMA_VERSION}."
    )
