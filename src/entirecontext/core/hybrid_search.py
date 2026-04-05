"""Backwards-compatibility shim — hybrid search now lives in search.py."""

from __future__ import annotations

from .search import hybrid_search, rrf_fuse

__all__ = ["hybrid_search", "rrf_fuse"]
