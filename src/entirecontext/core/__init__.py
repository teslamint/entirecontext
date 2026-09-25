"""Core business logic for EntireContext."""

from .project import init_project, get_project, get_status, find_git_root, find_project_root, get_repo_roots
from .repo_roots import RepoRoots, resolve_repo_roots
from .session import create_session, get_session, list_sessions, get_current_session
from .turn import create_turn, get_turn, list_turns, content_hash
from .search import regex_search, fts_search
from .cross_repo import list_repos, cross_repo_search, cross_repo_sessions
from .config import load_config, save_config, get_config_value
from .security import filter_secrets

__all__ = [
    "init_project",
    "get_project",
    "get_status",
    "find_git_root",
    "find_project_root",
    "get_repo_roots",
    "resolve_repo_roots",
    "RepoRoots",
    "create_session",
    "get_session",
    "list_sessions",
    "get_current_session",
    "create_turn",
    "get_turn",
    "list_turns",
    "content_hash",
    "regex_search",
    "fts_search",
    "list_repos",
    "cross_repo_search",
    "cross_repo_sessions",
    "load_config",
    "save_config",
    "get_config_value",
    "filter_secrets",
]
