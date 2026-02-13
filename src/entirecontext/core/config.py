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
    },
    "search": {
        "default_mode": "regex",
        "semantic_model": "all-MiniLM-L6-v2",
    },
    "sync": {
        "auto_sync": False,
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
        ],
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


def _write_toml_section(lines: list[str], data: dict, prefix: list[str]) -> None:
    for key, value in data.items():
        if isinstance(value, dict):
            section = ".".join(prefix + [key])
            lines.append(f"\n[{section}]")
            _write_toml_section(lines, value, prefix + [key])
        elif isinstance(value, list):
            lines.append(f"{key} = [")
            for item in value:
                lines.append(f"    {_toml_value(item)},")
            lines.append("]")
        else:
            lines.append(f"{key} = {_toml_value(value)}")


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)
