"""Configuration management — TOML-based, global + per-repo merge."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_GLOBAL_CONFIG_PATH = Path.home() / ".entirecontext" / "config.toml"

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        "auto_capture": True,
        "checkpoint_on_commit": True,
        "checkpoint_on_session_end": False,
        "auto_cleanup_no_changes": False,
        "content_retention_days": 30,
        "intent_summary": False,
        "emit_aar": True,
        "codex_session_idle_minutes": 60,
        "surface_lessons_on_start": True,
        "exclusions": {
            "enabled": False,
            "content_patterns": [],
            "file_patterns": [],
            "tool_names": [],
            "redact_patterns": [],
        },
    },
    "search": {
        "default_mode": "regex",
        "semantic_model": "all-MiniLM-L6-v2",
    },
    "sync": {
        "auto_sync": False,
        "auto_sync_on_push": False,
        "auto_pull": False,
        "cooldown_seconds": 300,
        "pull_staleness_seconds": 600,
        "push_on_sync": True,
        "quiet": True,
    },
    "display": {
        "max_results": 20,
        "color": True,
    },
    "security": {
        "filter_secrets": True,
        "patterns": [
            r'(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*[\'"]?[\w-]+',
            r"(?i)bearer\s+[\w.-]+",
            r"ghp_[a-zA-Z0-9]{36}",
            r"sk-[a-zA-Z0-9]{48}",
            r"sk-proj-[a-zA-Z0-9_-]{20,}",
        ],
    },
    "filtering": {
        "query_redaction": {
            "enabled": False,
            "patterns": [],
            "replacement": "[FILTERED]",
        },
    },
    "index": {
        "auto_embed": False,
        "embed_model": "all-MiniLM-L6-v2",
    },
    "futures": {
        "auto_distill": False,
        "lessons_output": "LESSONS.md",
        "default_backend": "claude",
        "default_model": "",
        "assess_enrich": True,
        "assess_backfill_window_days": 7,
    },
    "decisions": {
        "auto_stale_check": False,
        "auto_extract": True,
        "show_related_on_start": False,
        "auto_promotion_contradicted_threshold": 2,
        "assessment_lookback_hours": 48,
        "surface_on_tool_use": False,
        "surface_on_tool_use_turn_interval": 1,
        "surface_on_tool_use_limit": 3,
        "surface_on_user_prompt": False,
        "surface_on_user_prompt_limit": 3,
        "extract_keywords": [
            "결정",
            "선택",
            "방식으로",
            "decided",
            "chose",
            "approach",
            "instead of",
        ],
        "extract_sources": ["session", "checkpoint", "assessment"],
        "infer_ignored_on_session_end": False,
        "infer_applied_on_session_end": True,
        "infer_outcome_type": True,
        "ignored_inference_min_turn_gap": 2,
        "candidate_min_confidence": 0.35,
        "noise_gate_min_turns_with_files": 3,
        "extract_max_attempts": 3,
        "candidate_dedup_similarity_threshold": 0.5,
        "candidate_redact_secrets": True,
        "capture_ranking_snapshots": False,
        "ranking_snapshot_retention_days": 90,
        "ranking": {
            "staleness_factors": {
                "fresh": 1.0,
                "stale": 0.85,
                "superseded": 0.5,
                "contradicted": 0.25,
            },
            "assessment_relation_weights": {
                "supports": 4.0,
                "informed_by": 4.0,
                "contradicts": 5.0,
                "supersedes": 3.0,
            },
            "file_exact_weight": 3.0,
            "git_commit_weight": 3.0,
            "directory_proximity_cap_levels": 3,
        },
        "quality": {
            "recency_half_life_days": 30.0,
            "min_volume": 2,
        },
        "extraction": {
            "outcome_feedback_enabled": True,
            "outcome_feedback_lookback_days": 60,
            "contradicted_penalty": 0.15,
        },
        "auto_embed": True,
        "injection": {
            "inject_on_user_prompt": True,
            "experiment_block": None,
            "top_k": 5,
            "max_tokens": 800,
            "min_confidence": 0.4,
            "inject_timeout_ms": 250,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(repo_path: str | Path | None = None) -> dict[str, Any]:
    """Load merged config: defaults <- global <- per-repo."""
    config = DEFAULT_CONFIG.copy()

    if _GLOBAL_CONFIG_PATH.exists():
        with open(_GLOBAL_CONFIG_PATH, "rb") as f:
            global_conf = tomllib.load(f)
        config = _deep_merge(config, global_conf)

    if repo_path:
        local_path = Path(repo_path) / ".entirecontext" / "config.toml"
        if local_path.exists():
            with open(local_path, "rb") as f:
                local_conf = tomllib.load(f)
            config = _deep_merge(config, local_conf)

    return config


def is_experiment_off(decisions_config: dict) -> bool:
    """Return True when experiment_block is 'off', suppressing all proactive surfacing."""
    return decisions_config.get("injection", {}).get("experiment_block") == "off"


def save_config(repo_path: str | Path | None, key: str, value: str) -> None:
    """Save a config value. Uses per-repo config if repo_path given, else global."""
    if repo_path:
        config_path = Path(repo_path) / ".entirecontext" / "config.toml"
    else:
        config_path = _GLOBAL_CONFIG_PATH

    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            existing = tomllib.load(f)

    parts = key.split(".")
    target = existing
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    parsed = _parse_value(value)
    target[parts[-1]] = parsed

    _write_toml(config_path, existing)


def get_config_value(config: dict, key: str) -> Any:
    """Get a nested config value by dotted key."""
    parts = key.split(".")
    current = config
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _parse_value(value: str) -> Any:
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _write_toml(path: Path, data: dict) -> None:
    """Write dict as TOML (simple serializer for flat/nested dicts)."""
    lines: list[str] = []
    _write_toml_section(lines, data, [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _needs_quoting(key: str) -> bool:
    return not key.isidentifier() or not all(c.isalnum() or c in "-_" for c in key)


def _quote_toml_key(key: str) -> str:
    if _needs_quoting(key):
        escaped = key.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return key


def _write_toml_section(lines: list[str], data: dict, prefix: list[str]) -> None:
    tables: list[tuple[str, dict]] = []
    for key, value in data.items():
        qk = _quote_toml_key(key)
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list):
            lines.append(f"{qk} = [")
            for item in value:
                lines.append(f"    {_toml_value(item)},")
            lines.append("]")
        else:
            lines.append(f"{qk} = {_toml_value(value)}")
    for key, value in tables:
        section = ".".join(_quote_toml_key(k) for k in prefix + [key])
        lines.append(f"\n[{section}]")
        _write_toml_section(lines, value, prefix + [key])


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        v = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{v}"'
    if isinstance(v, dict):
        pairs = ", ".join(f"{_quote_toml_key(k)} = {_toml_value(val)}" for k, val in v.items())
        return f"{{{pairs}}}"
    return str(v)
