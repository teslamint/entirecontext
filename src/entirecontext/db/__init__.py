"""Database layer for EntireContext."""

from .connection import get_db, get_global_db, get_memory_db
from .migration import check_and_migrate, get_current_version
from .schema import SCHEMA_VERSION

__all__ = [
    "get_db",
    "get_global_db",
    "get_memory_db",
    "check_and_migrate",
    "get_current_version",
    "SCHEMA_VERSION",
]
