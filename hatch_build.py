"""Hatchling hook that injects Git provenance into distribution artifacts."""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PROVENANCE_SOURCE = Path("src/entirecontext/_build_provenance.py")


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _read_existing_provenance(root: Path) -> tuple[str | None, bool]:
    path = root / _PROVENANCE_SOURCE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return None, False
    values: dict[str, object] = {}
    saw_future_import = False
    for index, node in enumerate(tree.body):
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                continue
        if isinstance(node, ast.ImportFrom):
            valid_future_import = (
                not saw_future_import
                and node.module == "__future__"
                and node.level == 0
                and len(node.names) == 1
                and node.names[0].name == "annotations"
                and node.names[0].asname is None
            )
            if valid_future_import:
                saw_future_import = True
                continue
            return None, False

        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name not in {"BUILD_SHA", "BUILD_DIRTY"} or value is None or name in values:
            return None, False
        try:
            values[name] = ast.literal_eval(value)
        except (ValueError, TypeError):
            return None, False

    sha = values.get("BUILD_SHA")
    dirty = values.get("BUILD_DIRTY")
    if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None or type(dirty) is not bool:
        return None, False
    return sha, dirty


def _resolve_provenance(root: Path) -> tuple[str | None, bool]:
    top_level = _run_git(root, "rev-parse", "--show-toplevel")
    is_repository_root = (
        top_level is not None
        and top_level.returncode == 0
        and Path(top_level.stdout.strip()).resolve() == root.resolve()
    )
    if not is_repository_root:
        return _read_existing_provenance(root)

    head = _run_git(root, "rev-parse", "HEAD")
    if head is None or head.returncode != 0:
        return None, False
    sha = head.stdout.strip()
    if _SHA_RE.fullmatch(sha) is None:
        return None, False
    status = _run_git(root, "status", "--porcelain", "--untracked-files=no")
    dirty = status is None or status.returncode != 0 or bool(status.stdout.strip())
    return sha, dirty


def _render_provenance_module(sha: str | None, dirty: bool) -> str:
    return (
        '"""Build provenance generated while assembling this distribution."""\n\n'
        "from __future__ import annotations\n\n"
        f"BUILD_SHA: str | None = {sha!r}\n"
        f"BUILD_DIRTY = {dirty!r}\n"
    )


class CustomBuildHook(BuildHookInterface):
    """Inject provenance without modifying the tracked source fallback."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name not in {"wheel", "sdist"}:
            return

        sha, dirty = _resolve_provenance(Path(self.root))
        temporary_directory = tempfile.TemporaryDirectory(prefix="entirecontext-build-provenance-")
        generated = Path(temporary_directory.name) / f"{self.target_name}.py"
        generated.write_text(_render_provenance_module(sha, dirty), encoding="utf-8")

        target = (
            "entirecontext/_build_provenance.py"
            if self.target_name == "wheel"
            else "src/entirecontext/_build_provenance.py"
        )
        build_data["force_include"][str(generated)] = target
        self._temporary_directory = temporary_directory

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        temporary_directory = getattr(self, "_temporary_directory", None)
        if temporary_directory is not None:
            temporary_directory.cleanup()
