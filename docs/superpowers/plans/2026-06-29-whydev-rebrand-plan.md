# WhyDev Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename EntireContext to WhyDev (package `whydev`, CLI `wy`, MCP prefix `wy_`) and ship as v1.0.0.

**Architecture:** Mechanical rename in layers — (1) atomic package rename verified by full test suite, (2) runtime path constants, (3) MCP tool prefix, (4) migration command (only new feature — TDD here), (5) docs/CI/version, (6) external publishing with approval gates. No schema changes in v1.0.

**Tech Stack:** Python 3.12+, uv, SQLite, Typer, sed/find for bulk rename, pytest for verification

## Global Constraints

- Full test suite must pass after each task (1810+ tests)
- No blind `sed` substitution — substring collisions (`ec_` inside `exec_`, `spec_`, `codec_`, etc.) must be avoided
- MCP tool rename uses explicit function name list, not regex
- `wy migrate` tested with fixtures, never run on real user data during development
- PyPI publish and GitHub repo rename are irreversible — they happen last, after all verification, with explicit user approval
- Plan uses `find`/`grep -rl` discovery commands (not hardcoded file lists) because file count will change between now and v1.0 execution

---

### Task 1: Atomic Package Rename

**Files:**
- Rename: `src/entirecontext/` → `src/whydev/` (entire directory tree)
- Modify: `pyproject.toml` (package name, scripts, URLs, description)
- Modify: `src/whydev/__init__.py` (module docstring, version)
- Modify: All `*.py` files under `src/whydev/` (internal imports)
- Modify: All `*.py` files under `tests/` (test imports)

**Interfaces:**
- Consumes: nothing
- Produces: package `whydev` importable, CLI entry `wy`, all existing tests green

This task is atomic: partial rename leaves the suite uncollectable. Everything must change together.

- [ ] **Step 1: Rename the source directory**

```bash
mv src/entirecontext src/whydev
```

- [ ] **Step 2: Update pyproject.toml**

Change `name`, `description`, `scripts`, and `urls`:

```toml
[project]
name = "whydev"
version = "1.0.0"
description = "Decision memory for agent-assisted development — remember why, not just what"

[project.scripts]
wy = "whydev.cli:app"

[project.urls]
Homepage = "https://github.com/teslamint/whydev"
Repository = "https://github.com/teslamint/whydev"
```

- [ ] **Step 3: Update module docstring and version in `__init__.py`**

```python
"""WhyDev — Decision memory for agent-assisted development."""

__version__ = "1.0.0"
```

- [ ] **Step 4: Rewrite all internal imports within `src/whydev/`**

```bash
# Find all Python files with 'entirecontext' references under src/whydev/
grep -rl 'entirecontext' src/whydev/ --include="*.py" | while read f; do
  sed -i '' 's/from entirecontext/from whydev/g; s/import entirecontext/import whydev/g; s/entirecontext\./whydev./g' "$f"
done
```

Verify no remainders:
```bash
grep -rn 'entirecontext' src/whydev/ --include="*.py"
# Expected: 0 matches (or only in comments/docstrings describing the rename)
```

- [ ] **Step 5: Rewrite all test imports**

```bash
grep -rl 'entirecontext' tests/ --include="*.py" | while read f; do
  sed -i '' 's/from entirecontext/from whydev/g; s/import entirecontext/import whydev/g; s/entirecontext\./whydev./g' "$f"
done
```

Verify no remainders:
```bash
grep -rn 'entirecontext' tests/ --include="*.py"
# Expected: 0 matches (or only in comments/strings about migration)
```

- [ ] **Step 6: Reinstall the package in dev mode**

```bash
uv sync
```

- [ ] **Step 7: Run the full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass. If any fail, fix import issues before proceeding.

- [ ] **Step 8: Verify CLI entry point**

```bash
uv run wy --help
```

Expected: Typer help output with all subcommands.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat!: rename package entirecontext → whydev

BREAKING CHANGE: package name, CLI command (ec → wy), and all
import paths changed. Part of the WhyDev rebrand for v1.0.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Runtime Path Constants Rename

**Files:**
- Modify: All source files referencing `.entirecontext` as a path string (discovered via `grep -rl '\.entirecontext' src/whydev/`)
- Modify: `.gitignore`
- Test: Existing tests (path-sensitive tests should now reference `.whydev`)

**Interfaces:**
- Consumes: Task 1 (package is now `whydev`)
- Produces: All runtime paths use `.whydev/` and `~/.whydev/`; DB file renamed from `ec.db` to `wy.db`

This task changes string constants that control where data is stored at runtime.

- [ ] **Step 1: Discover all files with `.entirecontext` path references**

```bash
grep -rn '\.entirecontext' src/whydev/ --include="*.py"
```

Review output — each reference is a path constant (directory name, config path, DB path, state file path). No import-path confusion here since Task 1 already handled that.

- [ ] **Step 2: Replace path constants in source**

```bash
grep -rl '\.entirecontext' src/whydev/ --include="*.py" | while read f; do
  sed -i '' 's/\.entirecontext/\.whydev/g' "$f"
done
```

- [ ] **Step 3: Rename global DB filename `ec.db` → `wy.db`**

```bash
grep -rn 'ec\.db' src/whydev/ --include="*.py"
# Replace all occurrences
grep -rl 'ec\.db' src/whydev/ --include="*.py" | while read f; do
  sed -i '' "s/ec\.db/wy.db/g" "$f"
done
```

- [ ] **Step 4: Update test fixtures and test references**

```bash
grep -rl '\.entirecontext' tests/ --include="*.py" | while read f; do
  sed -i '' 's/\.entirecontext/\.whydev/g' "$f"
done
grep -rl 'ec\.db' tests/ --include="*.py" | while read f; do
  sed -i '' "s/ec\.db/wy.db/g" "$f"
done
```

- [ ] **Step 5: Update `.gitignore`**

Replace `.entirecontext/` with `.whydev/`:
```
.whydev/
```

- [ ] **Step 6: Verify no remainders**

```bash
grep -rn '\.entirecontext' src/whydev/ tests/ --include="*.py"
grep -rn 'ec\.db' src/whydev/ tests/ --include="*.py"
# Expected: 0 matches each (or only in migration code / comments about the rename)
```

- [ ] **Step 7: Run the full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat!: rename runtime paths .entirecontext → .whydev

BREAKING CHANGE: data directory, config, and global DB paths changed.
Use 'wy migrate' (added in a later commit) to move existing data.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: MCP Tool Prefix Rename

**Files:**
- Modify: `src/whydev/mcp/tools/*.py` (function names)
- Modify: `src/whydev/mcp/server.py` (server name, tool registration)
- Modify: All test files referencing `ec_*` MCP tool names
- Modify: Any source files calling MCP tools by name string

**Interfaces:**
- Consumes: Tasks 1-2 (package and paths are already `whydev`)
- Produces: All MCP tool functions named `wy_*`, server advertises as `whydev`

MCP tool names are Python function names decorated with `@mcp.tool()`. The rename is safe because MCP derives tool names from function names — no separate registry to update.

**Important:** Do NOT use blind `sed 's/ec_/wy_/g'` — this would corrupt `exec_`, `spec_`, `codec_`, `check_`, etc. Use the explicit 28-function list below.

- [ ] **Step 1: Build the explicit rename list**

```bash
# Extract all ec_* function names from MCP tools
grep -rn 'async def ec_' src/whydev/mcp/tools/ --include="*.py" | sed 's/.*async def \(ec_[a-z_]*\).*/\1/' | sort -u
```

Expected list (28 functions):
```
ec_activate
ec_assess
ec_assess_create
ec_assess_trends
ec_ast_search
ec_attribution
ec_checkpoint_list
ec_context_apply
ec_dashboard
ec_decision_candidate_confirm
ec_decision_candidate_get
ec_decision_candidate_list
ec_decision_candidate_reject
ec_decision_context
ec_decision_create
ec_decision_get
ec_decision_list
ec_decision_outcome
ec_decision_related
ec_decision_search
ec_decision_stale
ec_feedback
ec_graph
ec_lessons
ec_related
ec_rewind
ec_search
ec_session_context
ec_turn_content
```

- [ ] **Step 2: Rename MCP functions in source**

For each function in the list, rename `ec_` → `wy_` in the MCP tool files:

```bash
for func in ec_activate ec_assess ec_assess_create ec_assess_trends ec_ast_search ec_attribution ec_checkpoint_list ec_context_apply ec_dashboard ec_decision_candidate_confirm ec_decision_candidate_get ec_decision_candidate_list ec_decision_candidate_reject ec_decision_context ec_decision_create ec_decision_get ec_decision_list ec_decision_outcome ec_decision_related ec_decision_search ec_decision_stale ec_feedback ec_graph ec_lessons ec_related ec_rewind ec_search ec_session_context ec_turn_content; do
  new_func=$(echo "$func" | sed 's/^ec_/wy_/')
  # Replace in MCP tool source files
  grep -rl "$func" src/whydev/mcp/ --include="*.py" | while read f; do
    sed -i '' "s/\b${func}\b/${new_func}/g" "$f"
  done
done
```

- [ ] **Step 3: Update MCP server name**

In `src/whydev/mcp/server.py`, change the server name from `"entirecontext"` to `"whydev"`.

- [ ] **Step 4: Update test references**

```bash
for func in ec_activate ec_assess ec_assess_create ec_assess_trends ec_ast_search ec_attribution ec_checkpoint_list ec_context_apply ec_dashboard ec_decision_candidate_confirm ec_decision_candidate_get ec_decision_candidate_list ec_decision_candidate_reject ec_decision_context ec_decision_create ec_decision_get ec_decision_list ec_decision_outcome ec_decision_related ec_decision_search ec_decision_stale ec_feedback ec_graph ec_lessons ec_related ec_rewind ec_search ec_session_context ec_turn_content; do
  new_func=$(echo "$func" | sed 's/^ec_/wy_/')
  grep -rl "$func" tests/ --include="*.py" | while read f; do
    sed -i '' "s/${func}/${new_func}/g" "$f"
  done
done
```

- [ ] **Step 5: Update any source files referencing MCP tool names as strings**

```bash
# Check for string references to ec_ tool names in non-MCP source
grep -rn "'ec_\|\"ec_" src/whydev/ --include="*.py" | grep -v '/mcp/'
# Fix any found references
```

- [ ] **Step 6: Verify no ec_ function names remain**

```bash
grep -rn '\bec_' src/whydev/mcp/ --include="*.py"
# Expected: 0 matches

grep -rn 'ec_' tests/ --include="*.py" | grep -v 'exec_\|spec_\|codec_\|check_\|ovec_\|ovec_'
# Expected: 0 matches (only non-MCP substrings should remain)
```

- [ ] **Step 7: Verify no unintended wy_ collisions**

```bash
grep -rn 'wy_' src/whydev/ --include="*.py" | grep -v 'mcp/tools\|mcp/server\|async def wy_'
# Review any matches — should only be MCP-related
```

- [ ] **Step 8: Run the full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat!: rename MCP tools ec_* → wy_*

BREAKING CHANGE: all MCP tool names changed from ec_ prefix to wy_.
MCP clients must update their tool references.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Migration Command (`wy migrate`)

**Files:**
- Create: `src/whydev/cli/migrate_cmds.py`
- Modify: `src/whydev/cli/__init__.py` (register migrate subcommand)
- Create: `tests/test_migrate.py`

**Interfaces:**
- Consumes: Tasks 1-3 (all rename is complete; migrate operates on user's old data)
- Produces: `wy migrate` CLI command that moves `.entirecontext/` → `.whydev/`, renames `ec.db` → `wy.db`, handles global + per-repo data, prints external config guidance

This is the only new feature — proper TDD applies here.

- [ ] **Step 1: Investigate DB stored paths**

Before writing tests, verify what paths are stored in the database:

```bash
# Check content_path format in turn_content
uv run python3 -c "
import sqlite3, pathlib
db = pathlib.Path.home() / '.whydev/db/wy.db'
if not db.exists():
    db = pathlib.Path.home() / '.entirecontext/db/ec.db'
if db.exists():
    conn = sqlite3.connect(str(db))
    rows = conn.execute('SELECT content_path FROM turn_content LIMIT 5').fetchall()
    for r in rows: print(r)
    conn.close()
else:
    print('No global DB found')
"
```

Document whether `content_path` uses absolute or relative paths. This determines whether DB rows need updating during migration.

Also check:
```bash
# Check projects table for repo_path format
uv run python3 -c "
import sqlite3, pathlib
db = pathlib.Path.home() / '.entirecontext/db/ec.db'
if db.exists():
    conn = sqlite3.connect(str(db))
    rows = conn.execute('SELECT repo_path FROM projects LIMIT 10').fetchall()
    for r in rows: print(r)
    conn.close()
"
```

- [ ] **Step 2: Write failing test — basic per-repo migration**

```python
# tests/test_migrate.py
"""Tests for wy migrate command."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from whydev.cli.migrate_cmds import migrate_repo


def test_migrate_repo_moves_directory(tmp_path):
    """Per-repo .entirecontext/ → .whydev/ directory move."""
    repo = tmp_path / "repo"
    repo.mkdir()
    old_dir = repo / ".entirecontext"
    old_dir.mkdir()
    (old_dir / "config.toml").write_text("[capture]\nenabled = true\n")

    result = migrate_repo(str(repo))

    new_dir = repo / ".whydev"
    assert new_dir.exists()
    assert not old_dir.exists()
    assert (new_dir / "config.toml").read_text() == "[capture]\nenabled = true\n"
    assert result["status"] == "migrated"


def test_migrate_repo_skips_already_migrated(tmp_path):
    """Idempotent: .whydev/ exists, .entirecontext/ does not."""
    repo = tmp_path / "repo"
    repo.mkdir()
    new_dir = repo / ".whydev"
    new_dir.mkdir()

    result = migrate_repo(str(repo))
    assert result["status"] == "already_migrated"


def test_migrate_repo_skips_fresh(tmp_path):
    """Fresh repo with neither directory."""
    repo = tmp_path / "repo"
    repo.mkdir()

    result = migrate_repo(str(repo))
    assert result["status"] == "no_data"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_migrate.py -v
```

Expected: FAIL — `migrate_cmds` module does not exist.

- [ ] **Step 4: Write failing test — global migration**

```python
# Append to tests/test_migrate.py

from whydev.cli.migrate_cmds import migrate_global


def test_migrate_global_moves_directory(tmp_path, monkeypatch):
    """Global ~/.entirecontext/ → ~/.whydev/ move."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    old_global = fake_home / ".entirecontext"
    old_global.mkdir()
    (old_global / "config.toml").write_text("[display]\ntheme = dark\n")
    db_dir = old_global / "db"
    db_dir.mkdir()
    (db_dir / "ec.db").write_text("fake-db")

    result = migrate_global()

    new_global = fake_home / ".whydev"
    assert new_global.exists()
    assert not old_global.exists()
    assert (new_global / "config.toml").read_text() == "[display]\ntheme = dark\n"
    assert (new_global / "db" / "wy.db").exists()
    assert not (new_global / "db" / "ec.db").exists()
    assert result["status"] == "migrated"
    assert result["db_renamed"]


def test_migrate_global_skips_when_no_old_dir(tmp_path, monkeypatch):
    """No ~/.entirecontext/ → skip."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    result = migrate_global()
    assert result["status"] == "no_data"
```

- [ ] **Step 5: Write failing test — external config guidance**

```python
# Append to tests/test_migrate.py

from whydev.cli.migrate_cmds import get_external_config_guidance


def test_external_config_guidance_includes_mcp():
    """Guidance includes MCP re-registration instructions."""
    guidance = get_external_config_guidance()
    assert any("MCP" in line or "mcp" in line for line in guidance)
    assert any("wy" in line for line in guidance)
```

- [ ] **Step 6: Implement migrate_cmds.py**

```python
# src/whydev/cli/migrate_cmds.py
"""Migration from EntireContext to WhyDev."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(help="Migrate from EntireContext to WhyDev.")


def migrate_repo(repo_path: str) -> dict[str, Any]:
    repo = Path(repo_path)
    old_dir = repo / ".entirecontext"
    new_dir = repo / ".whydev"

    if new_dir.exists() and not old_dir.exists():
        return {"status": "already_migrated"}
    if not old_dir.exists():
        return {"status": "no_data"}

    if new_dir.exists():
        shutil.rmtree(new_dir)
    shutil.move(str(old_dir), str(new_dir))

    old_db = new_dir / "db" / "ec.db"
    new_db = new_dir / "db" / "wy.db"
    db_renamed = False
    if old_db.exists() and not new_db.exists():
        old_db.rename(new_db)
        db_renamed = True

    return {"status": "migrated", "db_renamed": db_renamed}


def migrate_global() -> dict[str, Any]:
    home = Path.home()
    old_global = home / ".entirecontext"
    new_global = home / ".whydev"

    if not old_global.exists():
        return {"status": "no_data"}

    if new_global.exists():
        shutil.rmtree(new_global)
    shutil.move(str(old_global), str(new_global))

    old_db = new_global / "db" / "ec.db"
    new_db = new_global / "db" / "wy.db"
    db_renamed = False
    if old_db.exists() and not new_db.exists():
        old_db.rename(new_db)
        db_renamed = True

    return {"status": "migrated", "db_renamed": db_renamed}


def get_external_config_guidance() -> list[str]:
    return [
        "External configuration updates needed:",
        "",
        "1. MCP server registration:",
        "   Update your Claude Code MCP config to use 'whydev' instead of 'entirecontext'.",
        "   Tool names changed: ec_* → wy_* (e.g., ec_search → wy_search).",
        "",
        "2. Codex notify hook (if using ec hook codex-notify):",
        "   Update ~/.codex/config.toml notify command from 'ec' to 'wy'.",
        "",
        "3. CLAUDE.md / AGENTS.md references:",
        "   Update any references from 'ec' commands to 'wy' commands.",
        "   Update any EntireContext MCP tool references (ec_* → wy_*).",
        "",
        "4. Git hooks (if using ec hook install):",
        "   Re-run: wy hook install",
    ]


@app.command("migrate")
def migrate_command(
    repo: str = typer.Argument(".", help="Repository path to migrate"),
    global_too: bool = typer.Option(True, "--global/--no-global", help="Also migrate global config"),
) -> None:
    """Migrate EntireContext data to WhyDev."""
    import rich

    console = rich.get_console()

    if global_too:
        result = migrate_global()
        if result["status"] == "migrated":
            console.print("[green]Global config migrated: ~/.entirecontext/ → ~/.whydev/[/green]")
            if result.get("db_renamed"):
                console.print("[green]  Global DB renamed: ec.db → wy.db[/green]")
        elif result["status"] == "already_migrated":
            console.print("[dim]Global: already migrated[/dim]")
        else:
            console.print("[dim]Global: no EntireContext data found[/dim]")

    result = migrate_repo(repo)
    if result["status"] == "migrated":
        console.print(f"[green]Repo migrated: {repo}[/green]")
    elif result["status"] == "already_migrated":
        console.print(f"[dim]Repo {repo}: already migrated[/dim]")
    else:
        console.print(f"[dim]Repo {repo}: no EntireContext data found[/dim]")

    console.print()
    for line in get_external_config_guidance():
        console.print(line)
```

- [ ] **Step 7: Register migrate subcommand**

In `src/whydev/cli/__init__.py`, add the migrate app:

```python
from whydev.cli.migrate_cmds import app as migrate_app

app.add_typer(migrate_app, name="migrate")
```

Or if the CLI uses direct command registration, add the migrate command accordingly (match existing pattern).

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_migrate.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 9: Run the full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 10: Commit**

```bash
git add src/whydev/cli/migrate_cmds.py tests/test_migrate.py src/whydev/cli/__init__.py
git commit -m "feat: add wy migrate command for EntireContext → WhyDev data migration

Moves .entirecontext/ → .whydev/, renames ec.db → wy.db,
handles both per-repo and global directories.
Prints guidance for external config updates (MCP, hooks, CLAUDE.md).

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Documentation, CI, and Version

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `CLAUDE.local.md`
- Modify: `AGENTS.md` (if exists)
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/tidy-pilot.yml`
- Modify: `CHANGELOG.md` (if exists)
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: Tasks 1-4 (all code changes complete)
- Produces: All documentation and CI reflects WhyDev identity

- [ ] **Step 1: Update README.md**

Replace all `entirecontext` references with `whydev`, `ec` CLI references with `wy`, `ec_*` MCP tool references with `wy_*`. Update project title, description, installation instructions, examples.

```bash
sed -i '' 's/entirecontext/whydev/g; s/EntireContext/WhyDev/g' README.md
```

Manually review and fix:
- Title and badges
- Installation: `pip install whydev`
- CLI examples: `wy` instead of `ec`
- MCP tool examples: `wy_*` instead of `ec_*`
- Description: "Decision memory for agent-assisted development"

- [ ] **Step 2: Update CLAUDE.md**

```bash
sed -i '' 's/entirecontext/whydev/g; s/EntireContext/WhyDev/g; s/`ec /`wy /g; s/`ec`/`wy`/g' CLAUDE.md
```

Manually review for ec_* → wy_* MCP tool references.

- [ ] **Step 3: Update CLAUDE.local.md**

Replace `ec` command references with `wy`:

```bash
sed -i '' 's/`ec /`wy /g; s/`ec`/`wy`/g' CLAUDE.local.md
```

- [ ] **Step 4: Update CI workflows**

Check and update any `entirecontext` references in CI files:

```bash
grep -rn 'entirecontext\|" ec "' .github/workflows/ --include="*.yml"
# Update all references found
```

- [ ] **Step 5: Update ROADMAP.md**

Replace identity references. Keep historical version notes as-is (they describe past releases):

```bash
# Update forward-looking references only
# Keep historical references in shipped version sections unchanged
```

Manually review: update "EntireContext" project name references, `ec` CLI references in non-historical sections.

- [ ] **Step 6: Verify no stale references in key files**

```bash
grep -n 'entirecontext\|" ec "\|`ec ' README.md CLAUDE.md CLAUDE.local.md .github/workflows/*.yml
# Expected: 0 matches (or only in historical/migration context)
```

- [ ] **Step 7: Run the full test suite one final time**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 8: Build the package**

```bash
uv build
```

Expected: `dist/whydev-1.0.0.tar.gz` and `dist/whydev-1.0.0-py3-none-any.whl` created.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "docs: update all documentation for WhyDev rebrand

README, CLAUDE.md, CLAUDE.local.md, CI workflows, and ROADMAP
updated to reflect the WhyDev identity. Historical version notes
preserved.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Dev Environment Re-bootstrap + External Publishing

**Files:**
- No source changes — this task is verification and external actions

**Interfaces:**
- Consumes: Tasks 1-5 (all changes committed and tested)
- Produces: Working dev environment, published package, renamed repo

This task contains irreversible external actions. Each major step requires explicit user confirmation.

- [ ] **Step 1: Reinstall the tool locally**

```bash
uv tool install --reinstall '.[mcp]'
```

Verify:
```bash
wy --help
wy --version
# Expected: WhyDev 1.0.0
```

- [ ] **Step 2: Run `wy migrate` on this repo**

```bash
wy migrate .
```

Expected: Migrates `.entirecontext/` → `.whydev/` in this repo + global directory.

- [ ] **Step 3: Re-register MCP server**

Update Claude Code MCP configuration to point to `whydev` instead of `entirecontext`. The exact location depends on the Claude Code MCP config format.

Verify MCP tools are available:
```bash
# Test MCP server starts
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' | uv run wy mcp serve 2>/dev/null | head -1
```

- [ ] **Step 4: Re-install Claude Code hooks**

```bash
wy hook install
```

Verify hooks work by checking `.claude/settings.json` or equivalent.

- [ ] **Step 5: Verify end-to-end dogfooding**

Start a new Claude Code session in this repo and verify:
- SessionStart hook fires (check stdout for decision context)
- `wy_search` MCP tool is available and returns results
- `wy_decision_create` MCP tool works

- [ ] **Step 6: USER APPROVAL — Publish to PyPI**

**This is irreversible.** Wait for explicit user approval.

```bash
# Only after user confirms:
uv publish
```

Verify:
```bash
pip install whydev --dry-run
```

- [ ] **Step 7: USER APPROVAL — Rename GitHub repo**

**This creates a redirect from the old URL.** Wait for explicit user approval.

```bash
# Only after user confirms:
gh repo rename whydev
```

- [ ] **Step 8: Tag the release**

```bash
git tag v1.0.0
git push origin main --tags
```

- [ ] **Step 9: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "chore(release): v1.0.0 — WhyDev rebrand complete

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Dropped from Plan

- **`decided_by` field**: Deferred to v1.1 per spec. Not included in this plan.
- **Retroactive Archaeology**: Post-v1.0 feature. Separate plan needed.
- **Decision Packs**: Post-v1.0 feature. Separate plan needed.
