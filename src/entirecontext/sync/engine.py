"""Reusable sync engine compatibility layer."""

from __future__ import annotations

from . import coordinator as _coordinator
from . import export_flow as _export_flow
from . import git_transport as _git_transport
from . import shadow_branch as _shadow_branch
from .git_transport import REMOTE_SHADOW_REF
from .shadow_branch import SHADOW_BRANCH

# Backward-compatible patch points for tests and older integrations.
shadow_branch_exists = _shadow_branch.shadow_branch_exists
init_shadow_branch = _shadow_branch.init_shadow_branch
subprocess = _git_transport.subprocess
export_sessions = _export_flow.export_sessions
export_checkpoints = _export_flow.export_checkpoints
update_manifest = _export_flow.update_manifest


def _bind_compat_symbols() -> dict[str, object]:
    originals = {
        "shadow_branch_exists": _coordinator.shadow_branch_exists,
        "init_shadow_branch": _coordinator.init_shadow_branch,
        "subprocess": _git_transport.subprocess,
        "export_sessions": _export_flow.export_sessions,
        "export_checkpoints": _export_flow.export_checkpoints,
        "update_manifest": _export_flow.update_manifest,
    }
    _coordinator.shadow_branch_exists = shadow_branch_exists
    _coordinator.init_shadow_branch = init_shadow_branch
    _git_transport.subprocess = subprocess
    _export_flow.export_sessions = export_sessions
    _export_flow.export_checkpoints = export_checkpoints
    _export_flow.update_manifest = update_manifest
    return originals


def _restore_compat_symbols(originals: dict[str, object]) -> None:
    _coordinator.shadow_branch_exists = originals["shadow_branch_exists"]
    _coordinator.init_shadow_branch = originals["init_shadow_branch"]
    _git_transport.subprocess = originals["subprocess"]
    _export_flow.export_sessions = originals["export_sessions"]
    _export_flow.export_checkpoints = originals["export_checkpoints"]
    _export_flow.update_manifest = originals["update_manifest"]


def perform_sync(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    originals = _bind_compat_symbols()
    try:
        return _coordinator.perform_sync(conn, repo_path, config, quiet=quiet)
    finally:
        _restore_compat_symbols(originals)


def perform_pull(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    originals = _bind_compat_symbols()
    try:
        return _coordinator.perform_pull(conn, repo_path, config, quiet=quiet)
    finally:
        _restore_compat_symbols(originals)


__all__ = [
    "REMOTE_SHADOW_REF",
    "SHADOW_BRANCH",
    "shadow_branch_exists",
    "init_shadow_branch",
    "subprocess",
    "export_sessions",
    "export_checkpoints",
    "update_manifest",
    "perform_sync",
    "perform_pull",
]
