"""CLI interface using Typer."""

import typer

app = typer.Typer(name="ec", help="EntireContext — searchable agent memory anchored to git")

# Import subcommand modules to register them
from . import project_cmds  # noqa: F401, E402
from . import search_cmds  # noqa: F401, E402
from . import session_cmds  # noqa: F401, E402
from . import hook_cmds  # noqa: F401, E402
from . import checkpoint_cmds  # noqa: F401, E402
from . import sync_cmds  # noqa: F401, E402
from . import rewind_cmds  # noqa: F401, E402
from . import repo_cmds  # noqa: F401, E402
