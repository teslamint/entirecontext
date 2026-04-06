"""Backwards-compatibility shim — functions moved to search.py and embedding.py.

TODO(cleanup): remove this shim after migrating callers to import from core.search and
core.embedding directly.
Tracked callers: search_cmds.py, mcp/tools/search.py, cross_repo.py, import_cmds.py, index_cmds.py
"""

from __future__ import annotations

from .embedding import generate_embeddings
from .search import rebuild_fts_indexes

__all__ = ["rebuild_fts_indexes", "generate_embeddings"]
