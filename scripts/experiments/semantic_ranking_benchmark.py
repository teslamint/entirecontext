"""Read-only prompt-ranking benchmark over file-labeled turns."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from entirecontext.core.config import load_config
from entirecontext.core.content_filter import redact_content, redact_for_query
from entirecontext.core.decisions import rank_related_decisions
from entirecontext.core.embedding import _build_decision_embed_text, cosine_similarity
from entirecontext.core.security import filter_secrets


DEFAULT_MODEL = "all-MiniLM-L6-v2"


def open_database(repo: str | Path) -> sqlite3.Connection:
    path = Path(repo) / ".entirecontext" / "db" / "local.db"
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _default_embedder_factory(model: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model)


def _bytes(vector: Any) -> bytes:
    return vector if isinstance(vector, bytes) else vector.tobytes()


def _metrics(items: list[tuple[list[str], list[str], set[str]]]) -> dict[str, float]:
    if not items:
        return {"hit_at_k": 0.0, "mrr": 0.0}
    hits = 0
    reciprocal = 0.0
    for baseline, semantic, relevant in items:
        ranks = [i for i, did in enumerate(semantic, 1) if did in relevant]
        hits += bool(ranks)
        reciprocal += 1 / ranks[0] if ranks else 0.0
    return {"hit_at_k": hits / len(items), "mrr": reciprocal / len(items)}


def benchmark(
    repo: str | Path,
    *,
    k: int = 5,
    model: str = DEFAULT_MODEL,
    embedder_factory: Callable[[str], Any] = _default_embedder_factory,
) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be positive")
    repo = Path(repo)
    config = load_config(repo)
    semantic_config = config.get("decisions", {}).get("semantic", {})
    conn = open_database(repo)
    try:
        turns = conn.execute(
            "SELECT user_message, files_touched, timestamp FROM turns WHERE files_touched IS NOT NULL ORDER BY timestamp, id"
        ).fetchall()
        decisions = conn.execute(
            "SELECT id, title, rationale, rejected_alternatives, created_at FROM decisions"
        ).fetchall()
        stored = {
            row["source_id"]: row["vector"]
            for row in conn.execute(
                "SELECT source_id, vector FROM embeddings WHERE source_type = 'decision' AND model_name = ?", (model,)
            )
        }
        embedder = embedder_factory(model)
        vectors = {
            d["id"]: stored[d["id"]]
            if d["id"] in stored
            else _bytes(
                embedder.encode(_build_decision_embed_text(d["title"], d["rationale"], d["rejected_alternatives"]))
            )
            for d in decisions
        }
        groups: dict[str, list[tuple[list[str], list[str], set[str]]]] = {
            "all": [],
            "hangul": [],
            "no_file_mention": [],
            "hangul_no_file_mention": [],
        }
        created = {d["id"]: d["created_at"] for d in decisions}
        decision_files = [
            (row["decision_id"], row["file_path"])
            for row in conn.execute("SELECT DISTINCT decision_id, file_path FROM decision_files")
        ]
        dropped = 0
        for turn in turns:
            try:
                paths = json.loads(turn["files_touched"])
            except (TypeError, ValueError):
                continue
            if not isinstance(paths, list) or not paths:
                continue
            paths = [path for path in paths if isinstance(path, str)]
            if not paths:
                continue
            # Hooks record absolute paths, possibly from a linked worktree; decision links are repo-relative.
            # A link matches when it equals the touched path or is its suffix at a "/" boundary.
            relevant: set[str] = set()
            labeled_paths: set[str] = set()
            for did, rel in decision_files:
                if did not in created or created[did] > turn["timestamp"]:
                    continue
                for path in paths:
                    if path == rel or path.endswith("/" + rel):
                        relevant.add(did)
                        labeled_paths.add(path)
            if not relevant:
                dropped += 1
                continue
            prompt = redact_for_query(filter_secrets(redact_content(turn["user_message"] or "", config)), config)
            baseline = rank_related_decisions(
                conn, file_paths=[], diff_text=prompt, commit_shas=[], until=turn["timestamp"], limit=k
            )
            query_vector = _bytes(embedder.encode(prompt))
            scores = {}
            for d in decisions:
                if d["created_at"] <= turn["timestamp"]:
                    try:
                        scores[d["id"]] = cosine_similarity(query_vector, vectors[d["id"]])
                    except ValueError:
                        continue
            semantic = rank_related_decisions(
                conn,
                file_paths=[],
                diff_text=prompt,
                commit_shas=[],
                until=turn["timestamp"],
                limit=k,
                semantic_scores=scores,
                semantic_weight=float(semantic_config.get("weight", 3.0)),
                semantic_min_similarity=float(semantic_config.get("min_similarity", 0.3)),
            )
            item = ([d["id"] for d in baseline], [d["id"] for d in semantic], relevant)
            groups["all"].append(item)
            hangul = bool(re.search("[가-힣]", prompt))
            # Spec: exclude only prompts that name a labeled file; other touched files do not leak the label.
            no_mention = not any(Path(path).name.lower() in prompt.lower() for path in labeled_paths)
            if hangul:
                groups["hangul"].append(item)
            if no_mention:
                groups["no_file_mention"].append(item)
            if hangul and no_mention:
                groups["hangul_no_file_mention"].append(item)
        report = {
            "counts": {"items": len(groups["all"]), "dropped_no_relevant": dropped},
            "subsets": {
                name: {
                    "count": len(items),
                    "baseline": _metrics([(b, b, r) for b, _, r in items]),
                    "semantic": _metrics(items),
                }
                for name, items in groups.items()
            },
            "k": k,
            "model": model,
            "database_path_digest": hashlib.sha256(str(repo / ".entirecontext/db/local.db").encode()).hexdigest(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        conn.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON (redirect to save it)")
    args = parser.parse_args()
    report = benchmark(args.repo, k=args.k, model=args.model)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print("subset                 count  baseline hit  semantic hit  baseline MRR  semantic MRR")
    for name, data in report["subsets"].items():
        print(
            f"{name:22} {data['count']:5}  {data['baseline']['hit_at_k']:12.3f}  {data['semantic']['hit_at_k']:12.3f}  {data['baseline']['mrr']:12.3f}  {data['semantic']['mrr']:12.3f}"
        )


if __name__ == "__main__":
    main()
