"""Backwards-compatibility shim — functions moved to search.py and embedding.py.

TODO(cleanup): remove this shim after migrating all callers to import from core.search and
core.embedding directly. See teslamint/entirecontext#27 for context. Callers to update:
  - cli/import_cmds.py
  - cli/index_cmds.py
"""

from __future__ import annotations

from .embedding import generate_embeddings
from .search import rebuild_fts_indexes

__all__ = ["rebuild_fts_indexes", "generate_embeddings"]
