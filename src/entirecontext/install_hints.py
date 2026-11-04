"""Install guidance shared by import-light failure paths.

Kept outside ``entirecontext.mcp`` because ``ec mcp serve`` must print this
hint when importing that package fails.
"""

MCP_INSTALL_HINT = (
    "Install the extra: uv tool install --force 'entirecontext[mcp]', "
    "or from a source checkout: uv tool install --force '.[mcp]'"
)
