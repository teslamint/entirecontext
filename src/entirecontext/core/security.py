"""Security — secret filtering before export/sync."""

from __future__ import annotations

import re

DEFAULT_PATTERNS = [
    r'(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*[\'"]?[\w-]+',
    r"(?i)bearer\s+[\w.-]+",
    r"ghp_[a-zA-Z0-9]{36}",
    r"sk-[a-zA-Z0-9]{48}",
]

REDACTED = "[REDACTED]"


def filter_secrets(text: str, patterns: list[str] | None = None) -> str:
    """Replace secret patterns with [REDACTED]."""
    if patterns is None:
        patterns = DEFAULT_PATTERNS
    for pattern in patterns:
        try:
            text = re.sub(pattern, REDACTED, text)
        except re.error:
            continue
    return text


def scan_for_secrets(text: str, patterns: list[str] | None = None) -> list[dict]:
    """Scan text for secrets, return list of findings."""
    if patterns is None:
        patterns = DEFAULT_PATTERNS
    findings = []
    for pattern in patterns:
        try:
            for match in re.finditer(pattern, text):
                findings.append(
                    {
                        "pattern": pattern,
                        "match": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )
        except re.error:
            continue
    return findings
