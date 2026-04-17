"""Candidate decision extraction pipeline.

Pulls candidate decisions out of sessions, checkpoints, and assessments;
scores them with a structural heuristic; dedups against existing decisions
and pending candidates; persists into decision_candidates.

Production hook/worker path uses run_extraction() directly. The CLI shim
at cli.decisions_cmds._extract_from_session_impl uses a separate loop so
test monkeypatches on that module's _get_llm_response stay effective.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from entirecontext.core.decisions import _normalize_path


class DecisionExtractionError(Exception):
    """Expected failure mode in the extraction pipeline.

    Raised for backend unavailable, rate limit, JSON parse failure, missing
    config. Callers downgrade to a telemetry warning and exit cleanly so the
    SessionEnd hook never crashes. Unexpected exceptions bypass this class
    and are recorded as error-level telemetry.
    """


_CODE_STOPWORDS_TITLE: frozenset[str] = frozenset(
    {
        "and",
        "or",
        "the",
        "for",
        "from",
        "with",
        "this",
        "that",
        "not",
        "use",
        "using",
        "new",
        "old",
        "via",
        "via",
    }
)


_VALID_SOURCE_TYPES = frozenset({"session", "checkpoint", "assessment"})

_BASE_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "assessment": 0.55,
    "checkpoint": 0.40,
    "session": 0.30,
}

_DEFAULT_EXTRACT_KEYWORDS: list[str] = [
    "결정",
    "선택",
    "방식으로",
    "decided",
    "chose",
    "approach",
    "instead of",
]

_MAX_CANDIDATES_PER_BUNDLE = 5
_MAX_PROMPT_CHARS = 8000


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SignalBundle:
    source_type: str
    source_id: str
    session_id: str
    checkpoint_id: str | None
    assessment_id: str | None
    text_blocks: list[str]
    files: list[str]


@dataclass
class CandidateDraft:
    title: str
    rationale: str | None
    scope: str | None
    rejected_alternatives: list[Any]
    supporting_evidence: list[Any]
    source_type: str
    source_id: str
    session_id: str
    checkpoint_id: str | None
    assessment_id: str | None
    files: list[str]


@dataclass
class DedupResult:
    dedup_key: str
    score_vs_decisions: float = 0.0
    score_vs_candidates: float = 0.0
    similar_decision_id: str | None = None
    similar_candidate_id: str | None = None


@dataclass
class PersistResult:
    candidate_id: str | None
    inserted: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_decisions_config(repo_path: str) -> dict:
    try:
        from .config import load_config

        cfg = load_config(repo_path)
        if isinstance(cfg, dict):
            return cfg.get("decisions", {}) or {}
    except Exception:
        pass
    return {}


def _load_security_patterns(repo_path: str) -> list[str] | None:
    try:
        from .config import load_config

        cfg = load_config(repo_path)
        sec = cfg.get("security", {}) if isinstance(cfg, dict) else {}
        patterns = sec.get("patterns")
        if isinstance(patterns, list):
            return patterns
    except Exception:
        pass
    return None


def _extract_keywords(config: dict) -> list[str]:
    raw = config.get("extract_keywords")
    if isinstance(raw, list) and raw:
        return [str(k) for k in raw]
    return list(_DEFAULT_EXTRACT_KEYWORDS)


def _extract_sources(config: dict) -> list[str]:
    raw = config.get("extract_sources")
    if isinstance(raw, list) and raw:
        return [str(s) for s in raw if s in _VALID_SOURCE_TYPES]
    return ["session", "checkpoint", "assessment"]


def _dedup_similarity_threshold(config: dict) -> float:
    raw = config.get("candidate_dedup_similarity_threshold", 0.5)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


def _should_redact_secrets(config: dict) -> bool:
    raw = config.get("candidate_redact_secrets", True)
    return bool(raw)


# ---------------------------------------------------------------------------
# Normalization & tokenization
# ---------------------------------------------------------------------------


def normalize_title_for_dedup(title: str) -> str:
    if not title:
        return ""
    lowered = title.lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    collapsed = re.sub(r"\s+", " ", stripped).strip()
    return collapsed


def compute_dedup_key(title: str) -> str:
    normalized = normalize_title_for_dedup(title)
    if not normalized:
        return hashlib.sha256(b"").hexdigest()[:12]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _tokenize_title_for_fts(title: str, max_tokens: int = 10) -> str | None:
    if not title:
        return None
    tokens: dict[str, int] = {}
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[a-z]+", title)
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", title)
    for t in {tok.lower() for tok in parts + words}:
        if len(t) < 3:
            continue
        if t in _CODE_STOPWORDS_TITLE:
            continue
        if re.fullmatch(r"[0-9a-f]+", t):
            continue
        tokens[t] = tokens.get(t, 0) + 1
    if not tokens:
        return None
    sorted_tokens = sorted(tokens, key=tokens.__getitem__, reverse=True)[:max_tokens]
    safe = []
    for tok in sorted_tokens:
        if tok.upper() in ("AND", "OR", "NOT", "NEAR"):
            safe.append(f'"{tok}"')
        else:
            safe.append(tok)
    return " OR ".join(safe)


# ---------------------------------------------------------------------------
# Session extraction marker (with v12 shim)
# ---------------------------------------------------------------------------


def is_session_extracted(conn, session_id: str) -> bool:
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["metadata"]:
        return False
    try:
        meta = json.loads(row["metadata"])
    except (ValueError, TypeError):
        return False
    if not isinstance(meta, dict):
        return False
    # v13 marker is authoritative; v12 marker shim means old sessions are
    # treated as already-extracted so we never re-run extraction on rows
    # written by the pre-candidates pipeline.
    if meta.get("candidates_extracted") is True:
        return True
    if meta.get("decisions_extracted") is True:
        return True
    return False


def mark_session_extracted(conn, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET metadata = json_set(COALESCE(metadata, '{}'), "
        "'$.candidates_extracted', json('true')) WHERE id = ?",
        (session_id,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Turn window derivation (used by checkpoint + assessment sources)
# ---------------------------------------------------------------------------


def _previous_checkpoint_created_at(conn, session_id: str, current_created_at: str) -> str | None:
    # datetime() wrapping normalizes both the ISO-8601 format that Python
    # writes via create_turn/_now_iso() and the space-separated form that
    # sqlite emits for the checkpoints.created_at DEFAULT datetime('now').
    # Without this, lexicographic comparison between 'T' (0x54) and ' '
    # (0x20) makes same-second turn/checkpoint rows compare incorrectly.
    row = conn.execute(
        "SELECT created_at FROM checkpoints "
        "WHERE session_id = ? AND datetime(created_at) < datetime(?) "
        "ORDER BY datetime(created_at) DESC, rowid DESC LIMIT 1",
        (session_id, current_created_at),
    ).fetchone()
    if row is None:
        return None
    return row["created_at"]


def _turn_window_rows(conn, session_id: str, checkpoint_created_at: str, prev_created_at: str | None) -> list[Any]:
    # Both turns.timestamp (ISO-8601 with T separator) and
    # checkpoints.created_at (sqlite space-separated) must be canonicalized
    # via datetime() so the range predicate works across the format
    # boundary. See _previous_checkpoint_created_at for context.
    if prev_created_at is None:
        return list(
            conn.execute(
                "SELECT assistant_summary, files_touched FROM turns "
                "WHERE session_id = ? AND datetime(timestamp) <= datetime(?) "
                "ORDER BY turn_number ASC",
                (session_id, checkpoint_created_at),
            ).fetchall()
        )
    return list(
        conn.execute(
            "SELECT assistant_summary, files_touched FROM turns "
            "WHERE session_id = ? AND datetime(timestamp) <= datetime(?) "
            "  AND datetime(timestamp) > datetime(?) "
            "ORDER BY turn_number ASC",
            (session_id, checkpoint_created_at, prev_created_at),
        ).fetchall()
    )


def _files_union_from_rows(rows: list[Any]) -> list[str]:
    all_files: set[str] = set()
    for r in rows:
        raw = r["files_touched"] if "files_touched" in r.keys() else None
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            for path in parsed:
                if isinstance(path, str) and path:
                    all_files.add(path)
    return sorted(all_files)


def _summaries_from_rows(rows: list[Any]) -> list[str]:
    out: list[str] = []
    for r in rows:
        summary = r["assistant_summary"] if "assistant_summary" in r.keys() else None
        if summary:
            out.append(str(summary))
    return out


# ---------------------------------------------------------------------------
# Signal collection
# ---------------------------------------------------------------------------


def _collect_session_bundle(conn, session_id: str, config: dict) -> SignalBundle | None:
    keywords = _extract_keywords(config)
    if not keywords:
        return None
    rows = conn.execute(
        "SELECT assistant_summary, files_touched FROM turns "
        "WHERE session_id = ? AND assistant_summary IS NOT NULL "
        "ORDER BY turn_number ASC",
        (session_id,),
    ).fetchall()
    if not rows:
        return None

    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    matching_rows = [r for r in rows if pattern.search(r["assistant_summary"] or "")]
    if not matching_rows:
        return None

    summaries = [r["assistant_summary"] for r in matching_rows if r["assistant_summary"]]

    matching_file_sets: list[set[str]] = []
    for r in matching_rows:
        if not r["files_touched"]:
            continue
        try:
            parsed = json.loads(r["files_touched"])
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            matching_file_sets.append({p for p in parsed if isinstance(p, str) and p})

    files: list[str] = []
    if matching_file_sets:
        intersection = set.intersection(*matching_file_sets) if len(matching_file_sets) > 1 else matching_file_sets[0]
        files = sorted(intersection)

    return SignalBundle(
        source_type="session",
        source_id=session_id,
        session_id=session_id,
        checkpoint_id=None,
        assessment_id=None,
        text_blocks=summaries,
        files=files,
    )


def _collect_checkpoint_bundles(conn, session_id: str) -> list[SignalBundle]:
    checkpoints = conn.execute(
        "SELECT id, created_at, diff_summary FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
        (session_id,),
    ).fetchall()
    bundles: list[SignalBundle] = []
    for cp in checkpoints:
        diff_summary = cp["diff_summary"]
        if not diff_summary or not str(diff_summary).strip():
            continue
        prev_created_at = _previous_checkpoint_created_at(conn, session_id, cp["created_at"])
        rows = _turn_window_rows(conn, session_id, cp["created_at"], prev_created_at)
        files = _files_union_from_rows(rows)
        if len(files) < 2:
            continue
        window_summaries = _summaries_from_rows(rows)
        text_blocks = [str(diff_summary)] + window_summaries
        bundles.append(
            SignalBundle(
                source_type="checkpoint",
                source_id=cp["id"],
                session_id=session_id,
                checkpoint_id=cp["id"],
                assessment_id=None,
                text_blocks=text_blocks,
                files=files,
            )
        )
    return bundles


def _collect_assessment_bundles(conn, session_id: str) -> list[SignalBundle]:
    rows = conn.execute(
        "SELECT a.id AS assessment_id, a.checkpoint_id, a.verdict, a.impact_summary, "
        "a.roadmap_alignment, a.tidy_suggestion, a.diff_summary, c.created_at AS cp_created_at "
        "FROM assessments a JOIN checkpoints c ON a.checkpoint_id = c.id "
        "WHERE c.session_id = ? AND a.verdict IN ('expand', 'narrow') "
        "ORDER BY a.created_at ASC",
        (session_id,),
    ).fetchall()
    bundles: list[SignalBundle] = []
    for r in rows:
        text_blocks: list[str] = []
        for field_name in ("impact_summary", "roadmap_alignment", "tidy_suggestion", "diff_summary"):
            value = r[field_name]
            if value:
                text_blocks.append(f"{field_name}: {value}")
        if not text_blocks:
            continue

        prev_created_at = _previous_checkpoint_created_at(conn, session_id, r["cp_created_at"])
        window_rows = _turn_window_rows(conn, session_id, r["cp_created_at"], prev_created_at)
        files = _files_union_from_rows(window_rows)

        bundles.append(
            SignalBundle(
                source_type="assessment",
                source_id=r["assessment_id"],
                session_id=session_id,
                checkpoint_id=r["checkpoint_id"],
                assessment_id=r["assessment_id"],
                text_blocks=text_blocks,
                files=files,
            )
        )
    return bundles


def collect_signals(conn, session_id: str, repo_path: str) -> list[SignalBundle]:
    config = _load_decisions_config(repo_path)
    sources = _extract_sources(config)
    bundles: list[SignalBundle] = []

    if "session" in sources:
        session_bundle = _collect_session_bundle(conn, session_id, config)
        if session_bundle is not None:
            bundles.append(session_bundle)

    if "checkpoint" in sources:
        bundles.extend(_collect_checkpoint_bundles(conn, session_id))

    if "assessment" in sources:
        bundles.extend(_collect_assessment_bundles(conn, session_id))

    return bundles


# ---------------------------------------------------------------------------
# Prompt assembly + redaction + LLM call
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_BY_SOURCE: dict[str, str] = {
    "session": (
        "You are reviewing a coding session for architectural or technical decisions. "
        'Return a JSON array: [{"title": str, "rationale": str, "scope": str, '
        '"rejected_alternatives": [str]}] '
        "Only include actual decisions (choosing one approach over another), "
        "not tasks, plans, or status updates. Return [] if no decisions were made."
    ),
    "checkpoint": (
        "You are reviewing a checkpoint's code change summary and the surrounding "
        "turn summaries. Extract architectural or technical decisions that the "
        "change embodies (e.g. choosing one library over another, switching a "
        "data model, picking an error handling strategy). "
        'Return a JSON array: [{"title": str, "rationale": str, "scope": str, '
        '"rejected_alternatives": [str]}]. '
        "Return [] if the change is a routine refactor, bug fix, or cleanup."
    ),
    "assessment": (
        "You are reviewing an assessment of a code change (verdict, impact summary, "
        "roadmap alignment, tidy suggestion). Extract decisions this assessment "
        "records — typically an expansion or narrowing of project scope with a "
        "specific rationale. "
        'Return a JSON array: [{"title": str, "rationale": str, "scope": str, '
        '"rejected_alternatives": [str]}]. '
        "Return [] if the assessment is a neutral observation."
    ),
}


def assemble_prompt(bundle: SignalBundle) -> str:
    combined = "\n\n".join(block for block in bundle.text_blocks if block)
    if len(combined) > _MAX_PROMPT_CHARS:
        combined = combined[:_MAX_PROMPT_CHARS]
    return combined


def get_system_prompt(source_type: str) -> str:
    return _SYSTEM_PROMPT_BY_SOURCE.get(source_type, _SYSTEM_PROMPT_BY_SOURCE["session"])


def apply_redaction(text: str, repo_path: str) -> str:
    if not text:
        return text
    config = _load_decisions_config(repo_path)
    if not _should_redact_secrets(config):
        return text
    try:
        from .security import filter_secrets

        patterns = _load_security_patterns(repo_path)
        return filter_secrets(text, patterns)
    except Exception:
        return text


def call_extraction_llm(user_text: str, repo_path: str, source_type: str = "session") -> str:
    try:
        from .config import load_config
        from .llm import get_backend
    except Exception as exc:
        raise DecisionExtractionError(f"llm backend unavailable: {exc}") from exc

    try:
        cfg = load_config(repo_path)
        futures_cfg = cfg.get("futures", {}) if isinstance(cfg, dict) else {}
        backend_name = futures_cfg.get("default_backend", "openai")
        model = futures_cfg.get("default_model", None)
        backend = get_backend(backend_name, model=model)
    except Exception as exc:
        raise DecisionExtractionError(f"llm backend init failed: {exc}") from exc

    system = get_system_prompt(source_type)
    try:
        return backend.complete(system, user_text)
    except Exception as exc:
        raise DecisionExtractionError(f"llm call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_llm_response(raw: str, bundle: SignalBundle) -> list[CandidateDraft]:
    if raw is None:
        raise DecisionExtractionError("llm returned None")
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DecisionExtractionError(f"llm output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        return []

    drafts: list[CandidateDraft] = []
    for item in parsed[:_MAX_CANDIDATES_PER_BUNDLE]:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        rationale = item.get("rationale")
        scope = item.get("scope")
        rejected = item.get("rejected_alternatives") or []
        if not isinstance(rejected, list):
            rejected = []
        drafts.append(
            CandidateDraft(
                title=title.strip(),
                rationale=rationale if isinstance(rationale, str) else None,
                scope=scope if isinstance(scope, str) else None,
                rejected_alternatives=rejected,
                supporting_evidence=[{"type": bundle.source_type, "id": bundle.source_id}],
                source_type=bundle.source_type,
                source_id=bundle.source_id,
                session_id=bundle.session_id,
                checkpoint_id=bundle.checkpoint_id,
                assessment_id=bundle.assessment_id,
                files=list(bundle.files),
            )
        )
    return drafts


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def _normalize_fts_scores(rows: list[Any]) -> dict[str, float]:
    """Normalize FTS5 bm25 ranks into [0.0, 1.0] using min-max rescaling.

    Matches the convention in core.decisions._fts_rank_decisions_from_diff
    (lines 1014-1018), which collapses a single-row result set to the
    *mid* value (2.0 out of [0.5, 4.0]) rather than the max. We do the
    same with our [0.0, 1.0] range — single-row → 0.5 — so that a
    single weak FTS hit does not propagate as the full dedup penalty
    weight and zero out legitimate candidates that happen to share one
    stopword-adjacent token with a prior decision. True duplicates are
    still caught by the exact dedup_key gate via the unique index.
    """
    if not rows:
        return {}
    raw_scores = {r["rowid"]: -float(r["rank"]) for r in rows}
    if not raw_scores:
        return {}
    mx = max(raw_scores.values())
    mn = min(raw_scores.values())
    result: dict[str, float] = {}
    if mx == mn:
        for rowid in raw_scores:
            result[str(rowid)] = 0.5
    else:
        span = mx - mn
        for rowid, raw in raw_scores.items():
            result[str(rowid)] = (raw - mn) / span
    return result


def dedup(conn, draft: CandidateDraft) -> DedupResult:
    dedup_key = compute_dedup_key(draft.title)
    result = DedupResult(dedup_key=dedup_key)

    fts_query = _tokenize_title_for_fts(draft.title)
    if not fts_query:
        return result

    # vs. decisions
    try:
        decisions_rows = conn.execute(
            "SELECT rowid, rank FROM fts_decisions WHERE fts_decisions MATCH ? ORDER BY rank LIMIT 10",
            (fts_query,),
        ).fetchall()
    except Exception:
        decisions_rows = []
    if decisions_rows:
        normalized = _normalize_fts_scores(decisions_rows)
        if normalized:
            top_rowid, top_score = max(normalized.items(), key=lambda kv: kv[1])
            result.score_vs_decisions = top_score
            try:
                id_row = conn.execute("SELECT id FROM decisions WHERE rowid = ?", (int(top_rowid),)).fetchone()
                if id_row:
                    result.similar_decision_id = id_row["id"]
            except Exception:
                pass

    # vs. pending candidates
    try:
        cand_rows = conn.execute(
            "SELECT fdc.rowid AS rowid, fdc.rank AS rank FROM fts_decision_candidates fdc "
            "JOIN decision_candidates dc ON dc.rowid = fdc.rowid "
            "WHERE fts_decision_candidates MATCH ? AND dc.review_status = 'pending' "
            "ORDER BY fdc.rank LIMIT 10",
            (fts_query,),
        ).fetchall()
    except Exception:
        cand_rows = []
    if cand_rows:
        normalized = _normalize_fts_scores(cand_rows)
        if normalized:
            top_rowid, top_score = max(normalized.items(), key=lambda kv: kv[1])
            result.score_vs_candidates = top_score
            try:
                id_row = conn.execute(
                    "SELECT id FROM decision_candidates WHERE rowid = ?", (int(top_rowid),)
                ).fetchone()
                if id_row:
                    result.similar_candidate_id = id_row["id"]
            except Exception:
                pass

    return result


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def score_confidence(draft: CandidateDraft, dedup_result: DedupResult) -> tuple[float, dict[str, Any]]:
    base = _BASE_CONFIDENCE_WEIGHTS.get(draft.source_type, 0.30)

    has_rationale = bool(draft.rationale and len(draft.rationale.strip()) >= 30)
    has_alts = bool(draft.rejected_alternatives and len(draft.rejected_alternatives) >= 1)
    file_scope_bonus = 0.0
    if draft.files and 1 <= len(draft.files) <= 5:
        file_scope_bonus = 0.10

    components_bonus = 0.0
    if has_rationale:
        components_bonus += 0.15
    if has_alts:
        components_bonus += 0.15
    components_bonus += file_scope_bonus

    initial = base + components_bonus
    penalty_vs_decisions = 0.25 * dedup_result.score_vs_decisions
    penalty_vs_candidates = 0.15 * dedup_result.score_vs_candidates
    penalty = penalty_vs_decisions + penalty_vs_candidates

    final = max(0.0, min(1.0, initial - penalty))

    breakdown: dict[str, Any] = {
        "base": {"source_type": draft.source_type, "weight": base},
        "components": {
            "has_rationale": has_rationale,
            "has_alts": has_alts,
            "file_scope_bonus": file_scope_bonus,
        },
        "initial": round(initial, 4),
        "penalties": {
            "vs_decisions": round(penalty_vs_decisions, 4),
            "vs_candidates": round(penalty_vs_candidates, 4),
        },
        "final": round(final, 4),
    }
    if dedup_result.similar_decision_id:
        breakdown["similar_decision_id"] = dedup_result.similar_decision_id
    if dedup_result.similar_candidate_id:
        breakdown["similar_candidate_id"] = dedup_result.similar_candidate_id

    return final, breakdown


# ---------------------------------------------------------------------------
# Outcome → extraction feedback (F2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionWeights:
    """Extraction feedback parameters loaded from ``[decisions.extraction]``.

    The ratio gate (0.5) is intentionally hardcoded: it is the midpoint where
    'more contradicted than not' becomes a signal, and exposing it as config
    invites bikeshedding without unlocking meaningful behavior. Magnitude of
    the penalty and the lookback horizon are the knobs worth tuning.
    """

    outcome_feedback_enabled: bool = True
    outcome_feedback_lookback_days: int = 60
    contradicted_penalty: float = 0.15


_DEFAULT_EXTRACTION_WEIGHTS = ExtractionWeights()

_OUTCOME_FEEDBACK_RATIO_THRESHOLD = 0.5


def _coerce_extraction_bool(section: dict, key: str, default: bool) -> bool:
    raw = section.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "yes", "1", "on"):
            return True
        if lowered in ("false", "no", "0", "off"):
            return False
    raise ValueError(f"decisions.extraction.{key} must be a boolean, got {raw!r}")


def _coerce_extraction_int(section: dict, key: str, default: int) -> int:
    raw = section.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"decisions.extraction.{key} must be an integer, got {raw!r}") from exc


def _coerce_extraction_float(section: dict, key: str, default: float) -> float:
    raw = section.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"decisions.extraction.{key} must be a number, got {raw!r}") from exc


def _coerce_extraction_nonneg_float(section: dict, key: str, default: float) -> float:
    """Variant of :func:`_coerce_extraction_float` that rejects negatives.

    ``contradicted_penalty`` must be >= 0 because ``apply_outcome_feedback_to_confidence``
    subtracts it directly: a negative value would convert the penalty into a
    boost when contradicted outcomes dominate, inverting the 'penalty-only'
    contract of this feature.
    """
    value = _coerce_extraction_float(section, key, default)
    if value < 0.0:
        raise ValueError(f"decisions.extraction.{key} must be >= 0, got {value!r}")
    return value


def _load_extraction_weights(config: dict | None) -> ExtractionWeights:
    """Build :class:`ExtractionWeights` from ``[decisions.extraction]``.

    Always returns a fresh instance so callers cannot mutate the module-level
    ``_DEFAULT_EXTRACTION_WEIGHTS`` singleton.
    """
    if not config:
        return ExtractionWeights()
    section = (config.get("decisions") or {}).get("extraction") or {}
    if not section:
        return ExtractionWeights()
    return ExtractionWeights(
        outcome_feedback_enabled=_coerce_extraction_bool(
            section, "outcome_feedback_enabled", _DEFAULT_EXTRACTION_WEIGHTS.outcome_feedback_enabled
        ),
        outcome_feedback_lookback_days=_coerce_extraction_int(
            section,
            "outcome_feedback_lookback_days",
            _DEFAULT_EXTRACTION_WEIGHTS.outcome_feedback_lookback_days,
        ),
        contradicted_penalty=_coerce_extraction_nonneg_float(
            section, "contradicted_penalty", _DEFAULT_EXTRACTION_WEIGHTS.contradicted_penalty
        ),
    )


def get_file_outcome_stats(
    conn,
    file_paths: list[str],
    lookback_days: int,
) -> dict[str, int]:
    """Aggregate outcome counts across decisions that touch the given files.

    Uses SQL-side path normalization matching ``_gather_candidates_by_files``
    so stored entries like ``"./src/foo.py"`` or ``"src\\foo.py"`` match
    normalized inputs. Paths are deduplicated at the decision level (same
    decision linked to multiple files in ``file_paths`` counts once per
    outcome).

    Returns ``{"accepted": N, "ignored": N, "contradicted": N, "total": N}``
    (zeros when nothing matches). ``lookback_days <= 0`` short-circuits to
    zeros so callers can disable the feedback path via config without a
    separate branch.
    """
    zero: dict[str, int] = {"accepted": 0, "ignored": 0, "contradicted": 0, "total": 0}
    if not file_paths or lookback_days <= 0:
        return zero

    normalized = [_normalize_path(p) for p in file_paths]
    placeholders = ",".join("?" for _ in normalized)
    rows = conn.execute(
        "SELECT o.outcome_type, COUNT(DISTINCT o.id) AS n"
        " FROM decision_outcomes o"
        " JOIN ("
        "   SELECT DISTINCT decision_id FROM decision_files"
        f"   WHERE REPLACE(CASE WHEN file_path LIKE './%' THEN SUBSTR(file_path, 3)"  # noqa: S608
        f"                 ELSE file_path END, '\\', '/') IN ({placeholders})"
        " ) df ON df.decision_id = o.decision_id"
        " WHERE datetime(o.created_at) >= datetime('now', ?)"
        " GROUP BY o.outcome_type",
        [*normalized, f"-{int(lookback_days)} days"],
    ).fetchall()

    stats = dict(zero)
    for row in rows:
        ot = row["outcome_type"]
        n = int(row["n"] or 0)
        if ot in ("accepted", "ignored", "contradicted"):
            stats[ot] = n
            stats["total"] += n
    return stats


def apply_outcome_feedback_to_confidence(
    confidence: float,
    breakdown: dict[str, Any],
    stats: dict[str, int],
    *,
    penalty: float = 0.15,
) -> tuple[float, dict[str, Any]]:
    """Apply a confidence penalty when contradicted outcomes dominate history.

    Penalty logic: if aggregated ``contradicted / total`` strictly exceeds
    :data:`_OUTCOME_FEEDBACK_RATIO_THRESHOLD` (0.5) across the draft's files,
    subtract ``penalty`` from ``confidence`` and clamp to ``[0.0, 1.0]``.
    Otherwise return the input unchanged.

    The returned breakdown always includes an ``outcome_feedback`` section
    (even when no penalty applied) so telemetry and UI can render a
    consistent shape without branching on presence.
    """
    total = int(stats.get("total", 0))
    contradicted = int(stats.get("contradicted", 0))
    accepted = int(stats.get("accepted", 0))
    ignored = int(stats.get("ignored", 0))

    ratio = (contradicted / total) if total > 0 else 0.0
    applied = ratio > _OUTCOME_FEEDBACK_RATIO_THRESHOLD
    penalty_amount = penalty if applied else 0.0
    final = max(0.0, min(1.0, confidence - penalty_amount))

    feedback = {
        "applied": applied,
        "contradicted": contradicted,
        "accepted": accepted,
        "ignored": ignored,
        "total": total,
        "ratio": round(ratio, 4),
        "ratio_threshold": _OUTCOME_FEEDBACK_RATIO_THRESHOLD,
        "penalty": round(penalty_amount, 4),
    }
    new_breakdown = dict(breakdown)
    new_breakdown["outcome_feedback"] = feedback
    if applied:
        # Keep the original score next to the adjusted final so downstream
        # review can see what was deducted without re-running the calc.
        new_breakdown["final_before_outcome_feedback"] = round(confidence, 4)
        new_breakdown["final"] = round(final, 4)
    return final, new_breakdown


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_candidate(
    conn,
    draft: CandidateDraft,
    confidence: float,
    breakdown: dict[str, Any],
    dedup_result: DedupResult,
) -> PersistResult:
    candidate_id = str(uuid4())
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO decision_candidates (
                id, title, rationale, scope, rejected_alternatives, supporting_evidence,
                source_type, source_id, session_id, checkpoint_id, assessment_id,
                files, confidence, confidence_breakdown, review_status, dedup_key,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                candidate_id,
                draft.title,
                draft.rationale,
                draft.scope,
                json.dumps(list(draft.rejected_alternatives)),
                json.dumps(list(draft.supporting_evidence)),
                draft.source_type,
                draft.source_id,
                draft.session_id,
                draft.checkpoint_id,
                draft.assessment_id,
                json.dumps(list(draft.files)),
                confidence,
                json.dumps(breakdown),
                dedup_result.dedup_key,
                now,
                now,
            ),
        )
        conn.commit()
        return PersistResult(candidate_id=candidate_id, inserted=True)
    except Exception as exc:
        # Unique-index violation on (source_type, source_id, dedup_key) is
        # expected idempotency — same source producing same normalized title.
        conn.rollback()
        msg = str(exc).lower()
        if "unique" in msg or "constraint" in msg:
            return PersistResult(candidate_id=None, inserted=False, reason="duplicate")
        return PersistResult(candidate_id=None, inserted=False, reason=f"error: {exc}")


# ---------------------------------------------------------------------------
# Orchestration (production hook/worker path)
# ---------------------------------------------------------------------------


@dataclass
class ExtractionOutcome:
    bundles_collected: int = 0
    drafts_parsed: int = 0
    candidates_inserted: int = 0
    duplicates_skipped: int = 0
    low_confidence_skipped: int = 0
    parsed_ok: bool = False
    marked: bool = False
    warnings: list[str] = field(default_factory=list)


def run_extraction(
    conn,
    session_id: str,
    repo_path: str,
    *,
    min_confidence: float = 0.35,
    extraction_weights: ExtractionWeights | None = None,
) -> ExtractionOutcome:
    outcome = ExtractionOutcome()
    if is_session_extracted(conn, session_id):
        return outcome

    bundles = collect_signals(conn, session_id, repo_path)
    outcome.bundles_collected = len(bundles)
    if not bundles:
        return outcome

    if extraction_weights is None:
        from entirecontext.core.config import load_config

        # Guard against malformed TOML: the extraction pipeline degrades
        # gracefully on expected failures (LLM unavailable, parse errors),
        # so a config read that crashes here must not abort the whole run.
        # Fall back to defaults + a warning so the session still gets its
        # candidates and the operator still sees the misconfiguration.
        try:
            extraction_weights = _load_extraction_weights(load_config(repo_path))
        except Exception as exc:
            outcome.warnings.append(f"extraction_weights_load:{exc}")
            extraction_weights = ExtractionWeights()

    for bundle in bundles:
        prompt_text = assemble_prompt(bundle)
        if not prompt_text.strip():
            continue
        redacted = apply_redaction(prompt_text, repo_path)
        try:
            raw = call_extraction_llm(redacted, repo_path, source_type=bundle.source_type)
        except DecisionExtractionError as exc:
            outcome.warnings.append(f"llm_call:{bundle.source_type}:{exc}")
            continue
        try:
            drafts = parse_llm_response(raw, bundle)
        except DecisionExtractionError as exc:
            outcome.warnings.append(f"parse:{bundle.source_type}:{exc}")
            continue
        outcome.parsed_ok = True
        outcome.drafts_parsed += len(drafts)
        for draft in drafts:
            dedup_result = dedup(conn, draft)
            score, breakdown = score_confidence(draft, dedup_result)
            if extraction_weights.outcome_feedback_enabled and draft.files:
                stats = get_file_outcome_stats(
                    conn,
                    list(draft.files),
                    extraction_weights.outcome_feedback_lookback_days,
                )
                score, breakdown = apply_outcome_feedback_to_confidence(
                    score,
                    breakdown,
                    stats,
                    penalty=extraction_weights.contradicted_penalty,
                )
            if score < min_confidence:
                outcome.low_confidence_skipped += 1
                continue
            persist_result = persist_candidate(conn, draft, score, breakdown, dedup_result)
            if persist_result.inserted:
                outcome.candidates_inserted += 1
            elif persist_result.reason == "duplicate":
                outcome.duplicates_skipped += 1

    if outcome.parsed_ok:
        mark_session_extracted(conn, session_id)
        outcome.marked = True

    return outcome
