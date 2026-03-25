"""Database layer for EntireContext."""

from .connection import get_db, get_global_db, get_memory_db
from .migration import apply_migrations, bootstrap_schema, check_and_migrate, get_current_version, init_schema
from .schema import SCHEMA_VERSION

__all__ = [
    "get_db",
    "get_global_db",
    "get_memory_db",
    "bootstrap_schema",
    "check_and_migrate",
    "get_current_version",
    "apply_migrations",
    "init_schema",
    "SCHEMA_VERSION",
]
