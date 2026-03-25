"""CLI interface using Typer."""

from __future__ import annotations

import typer

app = typer.Typer(name="ec", help="EntireContext — searchable agent memory anchored to git")

from . import ast_cmds  # noqa: E402
from . import blame_cmds  # noqa: E402
from . import checkpoint_cmds  # noqa: E402
from . import context_cmds  # noqa: E402
from . import decisions_cmds  # noqa: E402
from . import dashboard_cmds  # noqa: E402
from . import event_cmds  # noqa: E402
from . import futures_cmds  # noqa: E402
from . import graph_cmds  # noqa: E402
from . import hook_cmds  # noqa: E402
from . import import_cmds  # noqa: E402
from . import index_cmds  # noqa: E402
from . import mcp_cmds  # noqa: E402
from . import project_cmds  # noqa: E402
from . import purge_cmds  # noqa: E402
from . import repo_cmds  # noqa: E402
from . import rewind_cmds  # noqa: E402
from . import search_cmds  # noqa: E402
from . import session_cmds  # noqa: E402
from . import sync_cmds  # noqa: E402

_MODULES = (
    project_cmds,
    search_cmds,
    session_cmds,
    hook_cmds,
    checkpoint_cmds,
    sync_cmds,
    rewind_cmds,
    repo_cmds,
    event_cmds,
    blame_cmds,
    index_cmds,
    mcp_cmds,
    import_cmds,
    futures_cmds,
    purge_cmds,
    graph_cmds,
    ast_cmds,
    dashboard_cmds,
    context_cmds,
    decisions_cmds,
)

for module in _MODULES:
    register = getattr(module, "register", None)
    if callable(register):
        register(app)
