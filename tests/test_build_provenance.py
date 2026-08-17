"""Build-artifact provenance contract tests."""

from __future__ import annotations

import ast
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from hatch_build import _render_provenance_module, _resolve_provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_WHEEL_PATH = "entirecontext/_build_provenance.py"
PROVENANCE_SDIST_PATH = "src/entirecontext/_build_provenance.py"


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_git_repo(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "tracked.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "initial",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return _git_head(path)


def _read_constants(source: str) -> tuple[str | None, bool]:
    values: dict[str, str | bool | None] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            values[node.target.id] = ast.literal_eval(node.value)
    return values["BUILD_SHA"], values["BUILD_DIRTY"]  # type: ignore[return-value]


def _run_build(*args: str, cwd: Path) -> None:
    result = subprocess.run(
        ["uv", "build", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path, bool]:
    output_dir = tmp_path_factory.mktemp("build-provenance")
    direct_dir = output_dir / "direct"
    direct_dir.mkdir()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected_dirty = bool(status.stdout.strip())
    _run_build("--wheel", "--out-dir", str(direct_dir), cwd=REPO_ROOT)
    wheel = next(direct_dir.glob("*.whl"))

    sdist_dir = output_dir / "sdist"
    sdist_dir.mkdir()
    _run_build("--sdist", "--out-dir", str(sdist_dir), cwd=REPO_ROOT)
    sdist = next(sdist_dir.glob("*.tar.gz"))

    extracted_dir = output_dir / "extracted"
    extracted_dir.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        archive.extractall(extracted_dir, filter="data")
    source_root = next(path for path in extracted_dir.iterdir() if path.is_dir())

    rebuilt_dir = output_dir / "rebuilt"
    rebuilt_dir.mkdir()
    _run_build("--wheel", "--out-dir", str(rebuilt_dir), cwd=source_root)
    rebuilt_wheel = next(rebuilt_dir.glob("*.whl"))

    return wheel, sdist, rebuilt_wheel, expected_dirty


def test_built_wheel_contains_current_git_sha(built_artifacts):
    wheel, _, _, expected_dirty = built_artifacts
    with zipfile.ZipFile(wheel) as archive:
        assert archive.namelist().count(PROVENANCE_WHEEL_PATH) == 1
        build_sha, build_dirty = _read_constants(archive.read(PROVENANCE_WHEEL_PATH).decode())

    assert build_sha == _git_head(REPO_ROOT)
    assert build_dirty is expected_dirty


def test_built_wheel_preserves_runtime_package_and_entry_point(built_artifacts):
    wheel, _, _, _ = built_artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        entry_points_path = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = archive.read(entry_points_path).decode()

    assert "entirecontext/cli/project_cmds.py" in names
    assert "ec = entirecontext.cli:app" in entry_points


def test_sdist_to_wheel_preserves_git_sha(built_artifacts):
    _, sdist, rebuilt_wheel, _ = built_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        stamped_members = [name for name in archive.getnames() if name.endswith(PROVENANCE_SDIST_PATH)]
        assert len(stamped_members) == 1
        sdist_values = _read_constants(archive.extractfile(stamped_members[0]).read().decode())
    with zipfile.ZipFile(rebuilt_wheel) as archive:
        assert archive.namelist().count(PROVENANCE_WHEEL_PATH) == 1
        rebuilt_values = _read_constants(archive.read(PROVENANCE_WHEEL_PATH).decode())

    assert sdist_values == rebuilt_values
    assert rebuilt_values[0] == _git_head(REPO_ROOT)


def test_sdist_to_wheel_ignores_enclosing_repository(built_artifacts, tmp_path):
    _, sdist, _, _ = built_artifacts
    outer_repo = tmp_path / "outer"
    outer_repo.mkdir()
    subprocess.run(["git", "init"], cwd=outer_repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "outer",
        ],
        cwd=outer_repo,
        check=True,
        capture_output=True,
    )

    extracted_dir = outer_repo / "source"
    extracted_dir.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        stamped_member = next(name for name in archive.getnames() if name.endswith(PROVENANCE_SDIST_PATH))
        sdist_values = _read_constants(archive.extractfile(stamped_member).read().decode())
        archive.extractall(extracted_dir, filter="data")

    source_root = next(path for path in extracted_dir.iterdir() if path.is_dir())
    rebuilt_dir = tmp_path / "rebuilt"
    rebuilt_dir.mkdir()
    _run_build("--wheel", "--out-dir", str(rebuilt_dir), cwd=source_root)
    rebuilt_wheel = next(rebuilt_dir.glob("*.whl"))
    with zipfile.ZipFile(rebuilt_wheel) as archive:
        rebuilt_values = _read_constants(archive.read(PROVENANCE_WHEEL_PATH).decode())

    assert rebuilt_values == sdist_values
    assert rebuilt_values[0] != _git_head(outer_repo)


def test_sdist_build_inside_source_tree_contains_one_stamp(built_artifacts, tmp_path):
    _, sdist, _, _ = built_artifacts
    extracted_dir = tmp_path / "source"
    extracted_dir.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        original_member = next(name for name in archive.getnames() if name.endswith(PROVENANCE_SDIST_PATH))
        original_values = _read_constants(archive.extractfile(original_member).read().decode())
        archive.extractall(extracted_dir, filter="data")

    source_root = next(path for path in extracted_dir.iterdir() if path.is_dir())
    rebuilt_dir = source_root / "dist"
    rebuilt_dir.mkdir()
    _run_build("--sdist", "--out-dir", str(rebuilt_dir), cwd=source_root)
    rebuilt_sdist = next(rebuilt_dir.glob("*.tar.gz"))
    with tarfile.open(rebuilt_sdist, "r:gz") as archive:
        rebuilt_members = [name for name in archive.getnames() if name.endswith(PROVENANCE_SDIST_PATH)]
        assert len(rebuilt_members) == 1
        rebuilt_values = _read_constants(archive.extractfile(rebuilt_members[0]).read().decode())

    assert rebuilt_values == original_values


def test_resolve_provenance_reuses_valid_sdist_stamp(tmp_path):
    provenance_path = tmp_path / PROVENANCE_SDIST_PATH
    provenance_path.parent.mkdir(parents=True)
    provenance_path.write_text(_render_provenance_module("a" * 40, True), encoding="utf-8")

    assert _resolve_provenance(tmp_path) == ("a" * 40, True)


def test_resolve_provenance_rejects_invalid_sdist_stamp(tmp_path):
    provenance_path = tmp_path / PROVENANCE_SDIST_PATH
    provenance_path.parent.mkdir(parents=True)
    provenance_path.write_text('BUILD_SHA = "short"\nBUILD_DIRTY = False\n', encoding="utf-8")

    assert _resolve_provenance(tmp_path) == (None, False)


@pytest.mark.parametrize(
    "source",
    [
        _render_provenance_module("a" * 40, False) + "\nif True:\n    BUILD_DIRTY = True\n",
        _render_provenance_module("a" * 40, False) + f"\nBUILD_SHA = {'b' * 40!r}\n",
    ],
)
def test_resolve_provenance_rejects_ambiguous_sdist_stamp(tmp_path, source):
    provenance_path = tmp_path / PROVENANCE_SDIST_PATH
    provenance_path.parent.mkdir(parents=True)
    provenance_path.write_text(source, encoding="utf-8")

    assert _resolve_provenance(tmp_path) == (None, False)


def test_resolve_provenance_does_not_reuse_stamp_for_unborn_repository(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    provenance_path = tmp_path / PROVENANCE_SDIST_PATH
    provenance_path.parent.mkdir(parents=True)
    provenance_path.write_text(_render_provenance_module("a" * 40, False), encoding="utf-8")

    assert _resolve_provenance(tmp_path) == (None, False)


def test_resolve_provenance_tracks_only_tracked_file_changes(tmp_path):
    repo = tmp_path / "repo"
    head = _init_git_repo(repo)
    assert _resolve_provenance(repo) == (head, False)

    (repo / "untracked.txt").write_text("ignored\n", encoding="utf-8")
    assert _resolve_provenance(repo) == (head, False)

    (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    assert _resolve_provenance(repo) == (head, True)


def test_resolve_provenance_accepts_linked_worktree_root(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "provenance-test", str(worktree)],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    assert _resolve_provenance(worktree) == (_git_head(worktree), False)
