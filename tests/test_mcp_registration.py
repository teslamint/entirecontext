"""Tests for MCP tool registration."""

from __future__ import annotations

from entirecontext.mcp.tools import checkpoint, decisions, futures, misc, search, session


class _FakeMCP:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def tool(self):
        def decorator(fn):
            self.registered.append(fn.__name__)
            return fn

        return decorator


def test_register_tools_exports_expected_public_tool_names():
    mcp = _FakeMCP()

    for module in (search, checkpoint, session, futures, misc, decisions):
        module.register_tools(mcp)

    assert set(mcp.registered) == {
        "ec_activate",
        "ec_ast_search",
        "ec_assess",
        "ec_assess_create",
        "ec_assess_trends",
        "ec_attribution",
        "ec_checkpoint_list",
        "ec_context_apply",
        "ec_dashboard",
        "ec_decision_create",
        "ec_decision_get",
        "ec_decision_list",
        "ec_decision_outcome",
        "ec_decision_related",
        "ec_decision_stale",
        "ec_feedback",
        "ec_graph",
        "ec_lessons",
        "ec_related",
        "ec_rewind",
        "ec_search",
        "ec_session_context",
        "ec_turn_content",
    }
