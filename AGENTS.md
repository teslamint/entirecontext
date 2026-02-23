# Repository Guidelines

## Project Structure & Module Organization
- Source code lives in `src/entirecontext/`, organized by layer:
  - `cli/` (Typer commands), `core/` (business logic), `db/` (schema/migrations), `hooks/` (Claude hook handlers), `sync/` (shadow-branch export/import), `mcp/` (MCP server).
- Tests are in `tests/`, with both unit and end-to-end coverage (for example `tests/test_core.py`, `tests/test_e2e_search.py`).
- Documentation and research notes are in `docs/` and `docs/research/`.
- Build artifacts are output to `dist/`.

## Build, Test, and Development Commands
- `uv sync` : Install runtime dependencies.
- `uv sync --extra dev` : Install developer tools (`pytest`, `pytest-cov`, `ruff`).
- `uv run ec --help` : Verify CLI entrypoint and available commands.
- `uv run pytest` : Run full test suite.
- `uv run pytest --cov=entirecontext` : Run tests with coverage.
- `uv run ruff format .` : Format code (line length 120).
- `uv run ruff check . --fix` : Lint and auto-fix issues.
- `uv build` : Build distributable packages.

## Coding Style & Naming Conventions
- Python 3.12+ only (`requires-python >=3.12`).
- Use Ruff for formatting/linting; keep line length at 120.
- Follow existing naming patterns: snake_case for modules/functions, PascalCase for classes, descriptive command modules like `search_cmds.py`.
- Keep CLI concerns in `cli/` and domain logic in `core/`; avoid cross-layer shortcuts.

## Testing Guidelines
- Framework: `pytest` with shared fixtures in `tests/conftest.py`.
- Name tests as `test_*.py` and functions as `test_<behavior>`.
- Add/adjust tests for every behavior change, including edge and regression paths.
- Prefer real business logic execution; mock only external integrations when necessary.

## Commit & Pull Request Guidelines
- Commit style in history follows Conventional Commit-like prefixes: `feat(...)`, `fix(...)`, `refactor(...)`, `docs(...)`.
- Keep each commit focused on one change area and include scope when useful (example: `feat(search): add hybrid reranking`).
- PRs should include: purpose, key changes, test evidence (commands + results), and linked issue/task.
- Include CLI output snippets or screenshots when user-facing command behavior changes.

## Security & Configuration Tips
- Never commit secrets; use environment variables (for example `OPENAI_API_KEY`, `GITHUB_TOKEN`).
- Repo/local settings live under `.entirecontext/`; validate setup with `ec doctor` after config changes.
