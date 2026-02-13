"""Parse Claude Code JSONL transcript files."""

from __future__ import annotations

import json
from pathlib import Path


def extract_last_response(transcript_path: str) -> str:
    """Extract assistant's last response summary from transcript JSONL."""
    path = Path(transcript_path)
    if not path.exists():
        return ""

    last_assistant = ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("role") == "assistant":
                content = entry.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    last_assistant = " ".join(text_parts)
                elif isinstance(content, str):
                    last_assistant = content
    except OSError:
        return ""

    if len(last_assistant) > 500:
        return last_assistant[:500] + "..."
    return last_assistant


def extract_transcript_content(transcript_path: str) -> str:
    """Extract full transcript content for storage."""
    path = Path(transcript_path)
    if not path.exists():
        return ""

    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
