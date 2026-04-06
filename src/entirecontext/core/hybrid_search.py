"""Backwards-compatibility shim — hybrid search now lives in search.py.

TODO(cleanup): remove this shim after migrating all callers to import from core.search directly.
See teslamint/entirecontext#27 for context. Callers to update:
  - cli/search_cmds.py
  - mcp/tools/search.py
  - core/cross_repo.py
"""

from __future__ import annotations

from .search import hybrid_search, rrf_fuse

__all__ = ["hybrid_search", "rrf_fuse"]
