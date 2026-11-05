"""Private per-session prompt and semantic-score files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .async_worker import file_lock
from .content_filter import redact_content, redact_for_query
from .security import filter_secrets
from ..hooks.turn_capture import _sanitize_id_for_path


def _state(repo_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / "state"


def _paths(repo_path: str, session_id: str) -> tuple[Path, Path, Path]:
    sid = _sanitize_id_for_path(session_id)
    state = _state(repo_path)
    return (
        state / f"semantic-prompt-{sid}.txt",
        state / f"semantic-scores-{sid}.json",
        state / f"semantic-{sid}.lock",
    )


def semantic_top_n(semantic_config: dict[str, Any]) -> int:
    """Return the configured top_n, or 20 when it is missing or invalid (a non-positive slice drops the best scores)."""
    try:
        value = int(semantic_config.get("top_n", 20))
    except (TypeError, ValueError):
        return 20
    return value if value > 0 else 20


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)


def write_pending_prompt(repo_path: str, session_id: str, prompt: str, config: dict[str, Any]) -> Path:
    pending, scores, lock = _paths(repo_path, session_id)
    safe = redact_for_query(filter_secrets(redact_content(prompt, config)), config)
    with file_lock(lock):
        _atomic_write(pending, safe)
        scores.unlink(missing_ok=True)
    return pending


def take_pending_prompts(repo_path: str) -> list[tuple[str, Path]]:
    claimed = []
    for pending in _state(repo_path).glob("semantic-prompt-*.txt"):
        sid = pending.name.removeprefix("semantic-prompt-").removesuffix(".txt")
        path = pending.with_name(f"semantic-prompt-{sid}.{os.getpid()}.{uuid4().hex}.processing")
        try:
            os.replace(pending, path)
        except FileNotFoundError:
            continue
        claimed.append((sid, path))
    return claimed


def write_scores(repo_path: str, session_id: str, scores: dict[str, float], *, model: str, top_n: int) -> None:
    _, path, _ = _paths(repo_path, session_id)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_n]
    payload = {"model": model, "computed_at": datetime.now(timezone.utc).isoformat(), "scores": dict(ranked)}
    _atomic_write(path, json.dumps(payload))


def invalidate_scores(repo_path: str, session_id: str) -> None:
    _, scores, lock = _paths(repo_path, session_id)
    with file_lock(lock):
        scores.unlink(missing_ok=True)


def publish_scores_if_current(
    repo_path: str, session_id: str, scores: dict[str, float], *, model: str, top_n: int
) -> bool:
    pending, _, lock = _paths(repo_path, session_id)
    with file_lock(lock):
        if pending.exists():
            return False
        write_scores(repo_path, session_id, scores, model=model, top_n=top_n)
        return True


def read_fresh_scores(
    repo_path: str, session_id: str, *, model: str, max_age_seconds: int, now: datetime | None = None
) -> dict[str, float] | None:
    _, path, _ = _paths(repo_path, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(payload["computed_at"])
        age = (now or datetime.now(timezone.utc)) - timestamp
        if payload["model"] != model or age.total_seconds() > max_age_seconds or age.total_seconds() < 0:
            return None
        scores = payload["scores"]
        if not isinstance(scores, dict) or not all(
            isinstance(k, str) and isinstance(v, (int, float)) for k, v in scores.items()
        ):
            return None
        return scores
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None
