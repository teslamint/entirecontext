"""Sync module for shadow branch management."""

from .auto_sync import run_pull, run_sync, should_pull, should_sync, trigger_background_sync
from .engine import perform_pull, perform_sync
from .shadow_branch import init_shadow_branch, shadow_branch_exists, SHADOW_BRANCH

__all__ = [
    "init_shadow_branch",
    "shadow_branch_exists",
    "SHADOW_BRANCH",
    "perform_sync",
    "perform_pull",
    "trigger_background_sync",
    "run_sync",
    "run_pull",
    "should_sync",
    "should_pull",
]
