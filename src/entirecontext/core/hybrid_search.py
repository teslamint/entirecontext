"""Backwards-compatibility shim — hybrid search now lives in search.py.

TODO(cleanup): remove this shim after migrating callers to import from core.search directly.
Tracked callers: search_cmds.py, mcp/tools/search.py, cross_repo.py, import_cmds.py, index_cmds.py
"""

from __future__ import annotations

from .search import hybrid_search, rrf_fuse

__all__ = ["hybrid_search", "rrf_fuse"]
