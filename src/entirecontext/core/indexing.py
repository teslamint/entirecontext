"""Backwards-compatibility shim — functions moved to search.py and embedding.py."""

from __future__ import annotations

from .embedding import generate_embeddings
from .search import rebuild_fts_indexes

__all__ = ["rebuild_fts_indexes", "generate_embeddings"]
