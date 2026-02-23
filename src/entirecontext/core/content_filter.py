"""Content filtering — capture-time exclusion and redaction."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

FILTERED = "[FILTERED]"


def _get_exclusions(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("capture", {}).get("exclusions", {})


def _get_query_redaction(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("filtering", {}).get("query_redaction", {})


def should_skip_turn(user_message: str, config: dict[str, Any]) -> bool:
    """Check if a turn should be skipped based on content patterns."""
    exc = _get_exclusions(config)
    if not exc.get("enabled", False):
        return False
    for pattern in exc.get("content_patterns", []):
        try:
            if re.search(pattern, user_message):
                return True
        except re.error:
            continue
    return False


def should_skip_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check if a file should be excluded from tracking."""
    exc = _get_exclusions(config)
    if not exc.get("enabled", False):
        return False
    for pattern in exc.get("file_patterns", []):
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False


def should_skip_tool(tool_name: str, config: dict[str, Any]) -> bool:
    """Check if a tool should be excluded from tracking."""
    exc = _get_exclusions(config)
    if not exc.get("enabled", False):
        return False
    return tool_name in exc.get("tool_names", [])


def redact_content(text: str, config: dict[str, Any]) -> str:
    """Redact sensitive patterns from text before storage."""
    exc = _get_exclusions(config)
    if not exc.get("enabled", False):
        return text
    for pattern in exc.get("redact_patterns", []):
        try:
            text = re.sub(pattern, FILTERED, text)
        except re.error:
            continue
    return text


def redact_for_query(text: str, config: dict[str, Any]) -> str:
    """Redact sensitive patterns from text at query time."""
    qr = _get_query_redaction(config)
    if not qr.get("enabled", False):
        return text
    replacement = qr.get("replacement", FILTERED)
    for pattern in qr.get("patterns", []):
        try:
            text = re.sub(pattern, replacement, text)
        except re.error:
            continue
    return text
