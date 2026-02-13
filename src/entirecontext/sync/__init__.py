"""Sync module for shadow branch management."""

from .shadow_branch import init_shadow_branch, shadow_branch_exists, SHADOW_BRANCH

__all__ = ["init_shadow_branch", "shadow_branch_exists", "SHADOW_BRANCH"]
