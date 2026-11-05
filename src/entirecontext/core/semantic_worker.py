"""Exclusive background worker for prompt semantic scores."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from .async_worker import file_lock, is_worker_running
from .config import load_config
from .embedding import cosine_similarity
from .semantic_scores import invalidate_scores, publish_scores_if_current, semantic_top_n, take_pending_prompts


def _default_embedder(model: str) -> Callable[[str], bytes]:
    encoder = importlib.import_module("sentence_transformers").SentenceTransformer(model)
    return lambda prompt: encoder.encode(prompt).tobytes()


def run_semantic_worker(
    repo_path: str, *, embedder_factory: Callable[[str], Callable[[str], Any]] | None = None
) -> None:
    from ..db import get_db
    from ..hooks.session_lifecycle import _record_hook_warning

    config = load_config(repo_path).get("decisions", {}).get("semantic", {})
    model = str(config.get("model", "all-MiniLM-L6-v2"))
    top_n = semantic_top_n(config)
    try:
        embedder = (embedder_factory or _default_embedder)(model)
    except Exception as exc:
        # Missing package, missing model files, or a torch error: discard prompts instead of crashing,
        # so no prompt text stays on disk. Record only the exception type, never its message.
        _record_hook_warning(repo_path, "semantic_worker", RuntimeError(type(exc).__name__))
        embedder = None

    root = Path(repo_path) / ".entirecontext"
    _discard_orphaned_claims(root / "state")
    while True:
        claimed = take_pending_prompts(repo_path)
        vectors = []
        if embedder is not None and claimed:
            try:
                conn = get_db(repo_path)
                try:
                    vectors = conn.execute(
                        "SELECT source_id, vector FROM embeddings WHERE source_type = 'decision' AND model_name = ?",
                        (model,),
                    ).fetchall()
                finally:
                    conn.close()
            except Exception:
                vectors = []
        for sid, path in claimed:
            try:
                if embedder is None or not vectors:
                    invalidate_scores(repo_path, sid)
                    continue
                query = embedder(path.read_text(encoding="utf-8"))
                if not isinstance(query, bytes):
                    query = query.tobytes()
                scores = {}
                for row in vectors:
                    if len(row["vector"]) != len(query):
                        continue
                    scores[row["source_id"]] = cosine_similarity(query, row["vector"])
                if scores:
                    publish_scores_if_current(repo_path, sid, scores, model=model, top_n=top_n)
                else:
                    invalidate_scores(repo_path, sid)
            except Exception:
                invalidate_scores(repo_path, sid)
            finally:
                path.unlink(missing_ok=True)
        with file_lock(root / "worker-semantic.lock"):
            if not list((root / "state").glob("semantic-prompt-*.txt")):
                (root / "worker-semantic.pid").unlink(missing_ok=True)
                return


def _discard_orphaned_claims(state: Path) -> None:
    """Delete prompts claimed by a worker that died before it deleted them."""
    for path in state.glob("semantic-prompt-*.processing"):
        try:
            pid = int(path.name.split(".")[-3])
        except (IndexError, ValueError):
            continue
        if not is_worker_running(pid):
            path.unlink(missing_ok=True)
