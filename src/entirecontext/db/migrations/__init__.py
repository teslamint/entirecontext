"""Forward-only schema migrations."""

from __future__ import annotations

from importlib import import_module


def get_migrations() -> dict[int, list]:
    migrations: dict[int, list] = {}
    for version in range(2, 14):
        # version is a hardcoded bounded integer from range(), not user input
        module = import_module(
            f".v{version:03d}", __name__
        )  # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
        migrations[version] = list(module.MIGRATION_STEPS)
    return migrations
