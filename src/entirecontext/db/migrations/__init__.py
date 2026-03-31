"""Forward-only schema migrations."""

from __future__ import annotations

from importlib import import_module


def get_migrations() -> dict[int, list]:
    migrations: dict[int, list] = {}
    for version in range(2, 12):
        module = import_module(f".v{version:03d}", __name__)
        migrations[version] = list(module.MIGRATION_STEPS)
    return migrations
