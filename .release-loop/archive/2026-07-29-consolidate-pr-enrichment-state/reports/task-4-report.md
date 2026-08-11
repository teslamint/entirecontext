# Task 4 Report

## Status

Implementation complete; review pending.

## Changes

- Added deterministic fake-`Popen` coverage faithful to text-mode line iteration, where one line ends before the next record separator and the following line begins with it.
- Proved clean completion does not terminate the subprocess or emit warnings.
- Proved closing a live generator terminates and waits for its subprocess.
- Added a sentinel iterator proving `batch_size=1` starts extraction before requesting the next commit.
- Added a real Typer integration test for `decision candidates list --source archaeology`.
- Added the schema v17 migration traceability entry under CHANGELOG `Unreleased`.
- Accepted ADR 0004 after all project verification gates passed.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_contract_sync.py::test_schema_version_in_changelog -q` — 1 passed.
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_archaeology_streaming.py tests/test_archaeology_cli.py -q` — 15 passed.
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` — 2012 passed, 1 skipped, 1 warning.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` — passed.
- `UV_CACHE_DIR=/tmp/uv-cache uv run mypy src` — passed with no issues in 117 source files.

## Decision and lesson reuse

- No relevant stored decision was found for the Task 4 regression-proof scope.
- Reviewed generated project lessons; connection cleanup and shared-policy regression guidance reinforced the cleanup and CLI integration coverage.
- No prior assessment required feedback for this regression-only task.

## Concerns

- The full suite retains one pre-existing pytest deprecation warning for an instance-method class-scoped fixture in `tests/test_hooks_performance.py`.
- General Git C-style path escapes remain intentionally out of scope.
