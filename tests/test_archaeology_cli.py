"""CLI tests for ec archaeologize."""

import subprocess


def test_help_output():
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--since" in result.stdout
    assert "--until" in result.stdout
    assert "--limit" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--pr-bodies" in result.stdout
    assert "--batch-size" in result.stdout


def test_dry_run_on_fixture(git_repo):
    for i in range(3):
        (git_repo / f"file{i}.py").write_text(f"x = {i}")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: add file{i}"],
            cwd=git_repo,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                "PATH": subprocess.check_output(
                    ["bash", "-c", "echo $PATH"]
                ).decode().strip(),
            },
        )
    result = subprocess.run(
        ["uv", "run", "ec", "archaeologize", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=git_repo,
    )
    assert result.returncode == 0
    assert "commits" in result.stdout.lower() or "commits" in result.stderr.lower()
