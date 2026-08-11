"""Make `python -m entirecontext.cli` runnable.

The hook installer falls back to this form when the `ec` console script is not on PATH,
so the module must be executable or every generated hook fails at run time.
"""

from . import app

app()
