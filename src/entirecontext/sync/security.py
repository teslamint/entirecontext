"""Security filtering for sync/export — redact secrets before pushing."""

from __future__ import annotations

from ..core.security import filter_secrets, DEFAULT_PATTERNS


def filter_export_data(text: str, patterns: list[str] | None = None, enabled: bool = True) -> str:
    """Filter secrets from export data.

    Args:
        text: Text to filter
        patterns: Regex patterns (uses defaults if None)
        enabled: Whether filtering is enabled (--no-filter disables)
    """
    if not enabled:
        return text
    return filter_secrets(text, patterns)


def get_security_config(config: dict) -> tuple[bool, list[str]]:
    """Extract security settings from config."""
    security = config.get("security", {})
    enabled = security.get("filter_secrets", True)
    patterns = security.get("patterns", DEFAULT_PATTERNS)
    return enabled, patterns
