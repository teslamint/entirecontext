# Decision Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three decision-related hooks (SessionStart surfacing, SessionEnd stale detection, SessionEnd LLM extraction) to automate the decision lifecycle.

**Architecture:** New `hooks/decision_hooks.py` module with three functions. SessionStart and stale check run inline. LLM extraction runs as a background worker via named PID file. All hooks are config-gated and exception-safe.

**Tech Stack:** Python 3.12, SQLite, Typer CLI, subprocess (git), LLM backend (openai/anthropic via `core/llm.py`)

**Spec:** `docs/superpowers/specs/2026-04-04-decision-hooks-design.md`

---

### Task 1: Add `decisions` config section

**Files:**
- Modify: `src/entirecontext/core/config.py:11-69` (DEFAULT_CONFIG dict)
- Test: `tests/test_decision_hooks.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_decision_hooks.py`:

```python
"""Tests for decision hooks."""

from __future__ import annotations

from entirecontext.core.config import DEFAULT_CONFIG


class TestDecisionConfig:
    def test_decisions_section_exists(self):
        assert "decisions" in DEFAULT_CONFIG

    def test_decisions_defaults_all_off(self):
        decisions = DEFAULT_CONFIG["decisions"]
        assert decisions["auto_stale_check"] is False
        assert decisions["auto_extract"] is False
        assert decisions["show_related_on_start"] is False

    def test_extract_keywords_present(self):
        keywords = DEFAULT_CONFIG["decisions"]["extract_keywords"]
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert "decided" in keywords
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_hooks.py::TestDecisionConfig -v`
Expected: FAIL with `KeyError: 'decisions'`

- [ ] **Step 3: Add decisions section to DEFAULT_CONFIG**

In `src/entirecontext/core/config.py`, add after the `"futures"` section (around line 68):

```python
    "decisions": {
        "auto_stale_check": False,
        "auto_extract": False,
        "show_related_on_start": False,
        "extract_keywords": [
            "결정", "선택", "방식으로",
            "decided", "chose", "approach", "instead of",
        ],
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_hooks.py::TestDecisionConfig -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_decision_hooks.py
git commit -m "feat(config): add decisions section to DEFAULT_CONFIG"
```

---

### Task 2: Add `pid_name` parameter to `async_worker`

**Files:**
- Modify: `src/entirecontext/core/async_worker.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decision_hooks.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock
from entirecontext.core.async_worker import launch_worker, worker_status, _pid_file


class TestNamedWorker:
    def test_pid_file_default_name(self, tmp_path):
        result = _pid_file(str(tmp_path))
        assert result == tmp_path / ".entirecontext" / "worker.pid"

    def test_pid_file_custom_name(self, tmp_path):
        result = _pid_file(str(tmp_path), pid_name="worker-decision")
        assert result == tmp_path / ".entirecontext" / "worker-decision.pid"

    def test_launch_worker_custom_pid(self, tmp_path):
        ec_dir = tmp_path / ".entirecontext"
        ec_dir.mkdir()
        with patch("entirecontext.core.async_worker.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            pid = launch_worker(str(tmp_path), ["echo", "test"], pid_name="worker-decision")
            assert pid == 12345
            pid_path = ec_dir / "worker-decision.pid"
            assert pid_path.exists()
            assert pid_path.read_text().strip() == "12345"
            # Default pid file should NOT exist
            assert not (ec_dir / "worker.pid").exists()

    def test_worker_status_custom_pid(self, tmp_path):
        ec_dir = tmp_path / ".entirecontext"
        ec_dir.mkdir()
        # No pid file → not running
        status = worker_status(str(tmp_path), pid_name="worker-decision")
        assert status["running"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_hooks.py::TestNamedWorker -v`
Expected: FAIL with `TypeError: _pid_file() got an unexpected keyword argument 'pid_name'`

- [ ] **Step 3: Add `pid_name` parameter to async_worker functions**

Modify `src/entirecontext/core/async_worker.py`:

Change `_pid_file`:
```python
def _pid_file(repo_path: str, pid_name: str = "worker") -> Path:
    """Return the path to the worker PID file."""
    return Path(repo_path) / ".entirecontext" / f"{pid_name}.pid"
```

Change `get_worker_pid`:
```python
def get_worker_pid(repo_path: str, pid_name: str = "worker") -> int | None:
    pid_path = _pid_file(repo_path, pid_name)
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None
```

Change `launch_worker`:
```python
def launch_worker(repo_path: str, cmd: list[str], pid_name: str = "worker") -> int:
    pid_path = _pid_file(repo_path, pid_name)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_path.write_text(f"{proc.pid}\n")
    return proc.pid
```

Change `stop_worker`:
```python
def stop_worker(repo_path: str, pid_name: str = "worker") -> str:
    pid = get_worker_pid(repo_path, pid_name)
    if pid is None:
        return "none"
    outcome = "killed"
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        outcome = "stale"
    pid_path = _pid_file(repo_path, pid_name)
    try:
        pid_path.unlink()
    except OSError:
        pass
    return outcome
```

Change `worker_status`:
```python
def worker_status(repo_path: str, pid_name: str = "worker") -> dict:
    pid = get_worker_pid(repo_path, pid_name)
    if pid is None:
        return {"running": False, "pid": None}
    if is_worker_running(pid):
        return {"running": True, "pid": pid}
    return {"running": False, "pid": pid, "stale": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_hooks.py::TestNamedWorker -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run existing async_worker tests to check backwards compatibility**

Run: `uv run pytest tests/ -k "worker" -v`
Expected: All existing tests still pass (default `pid_name="worker"` is backwards-compatible)

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/async_worker.py tests/test_decision_hooks.py
git commit -m "feat(async_worker): add pid_name parameter for named worker slots"
```

---

### Task 3: Implement `maybe_check_stale_decisions` (SessionEnd stale check)

**Files:**
- Create: `src/entirecontext/hooks/decision_hooks.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_decision_hooks.py`:

```python
from unittest.mock import patch
from entirecontext.core.decisions import create_decision, link_decision_to_file, get_decision


class TestMaybeCheckStaleDecisions:
    def test_disabled_by_config(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": False},
        )
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        # Should not raise, should not touch DB
        maybe_check_stale_decisions(str(ec_repo))

    def test_no_decisions_early_return(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))
        # No error, no decisions to check

    def test_stale_detection_updates_status(self, ec_repo, ec_db, monkeypatch):
        import subprocess

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )
        # Create a decision and link a file
        d = create_decision(ec_db, title="Test decision")
        test_file = ec_repo / "src" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        # Make a git commit that changes the linked file
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "change app"],
            check=True, capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))

        updated = get_decision(ec_db, d["id"])
        assert updated["staleness_status"] == "stale"

    def test_exception_does_not_propagate(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr("entirecontext.core.decisions.list_decisions", _boom)
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        # Must not raise
        maybe_check_stale_decisions(str(ec_repo))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_hooks.py::TestMaybeCheckStaleDecisions -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'entirecontext.hooks.decision_hooks'`

- [ ] **Step 3: Create `decision_hooks.py` with `maybe_check_stale_decisions`**

Create `src/entirecontext/hooks/decision_hooks.py`:

```python
"""Decision-related hook functions — stale detection, extraction, context surfacing."""

from __future__ import annotations

from typing import Any

from .session_lifecycle import _find_git_root, _record_hook_warning


def _load_decisions_config(repo_path: str) -> dict:
    from ..core.config import load_config

    config = load_config(repo_path)
    return config.get("decisions", {})


def maybe_check_stale_decisions(repo_path: str) -> None:
    """Auto-detect stale decisions on SessionEnd. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_stale_check", False):
            return

        from ..core.decisions import check_staleness, list_decisions, update_decision_staleness
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            decisions = list_decisions(conn, staleness_status="fresh", limit=50)
            for d in decisions:
                result = check_staleness(conn, d["id"], repo_path)
                if result["stale"]:
                    update_decision_staleness(conn, d["id"], "stale")
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_stale_check", exc)


```

Note: Tests monkeypatch `_load_decisions_config` directly since it wraps the config import internally. No re-exports needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_hooks.py::TestMaybeCheckStaleDecisions -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/hooks/decision_hooks.py tests/test_decision_hooks.py
git commit -m "feat(hooks): add maybe_check_stale_decisions for SessionEnd"
```

---

### Task 4: Implement `on_session_start_decisions` (SessionStart surfacing)

**Files:**
- Modify: `src/entirecontext/hooks/decision_hooks.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_decision_hooks.py`:

```python
import subprocess as _subprocess


class TestOnSessionStartDecisions:
    def test_disabled_by_config(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": False},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None

    def test_no_related_decisions_returns_none(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None

    def test_related_decisions_shown(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        # Create decision linked to a file
        d = create_decision(ec_db, title="Arch decision")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        # Make git history with that file
        test_file = ec_repo / "src" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add app"],
            check=True, capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Arch decision" in result
        assert "Related Decisions" in result

    def test_stale_decisions_shown(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        create_decision(ec_db, title="Stale one", staleness_status="stale")

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Stale Decisions" in result
        assert "Stale one" in result

    def test_max_5_decisions(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        for i in range(8):
            create_decision(ec_db, title=f"Stale {i}", staleness_status="stale")

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        # Count decision entries (lines starting with "- [")
        entries = [line for line in result.split("\n") if line.strip().startswith("- [")]
        assert len(entries) <= 5

    def test_git_failure_returns_none(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        # Monkeypatch subprocess to fail AND no stale decisions
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.subprocess.run",
            lambda *a, **kw: MagicMock(returncode=1, stdout=""),
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_hooks.py::TestOnSessionStartDecisions -v`
Expected: FAIL with `ImportError: cannot import name 'on_session_start_decisions'`

- [ ] **Step 3: Implement `on_session_start_decisions`**

Add to `src/entirecontext/hooks/decision_hooks.py`:

```python
import re
import subprocess


def _get_recently_changed_files(repo_path: str) -> list[str]:
    """Get files changed in recent commits. Falls back to git log if git diff fails.

    Records a warning via _record_hook_warning if both git diff and git log fail.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~5..HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-5"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return list({f for f in result.stdout.strip().split("\n") if f})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _record_hook_warning(repo_path, "get_recently_changed_files", RuntimeError("both git diff and git log failed"))
    return []


def _format_decision_entry(d: dict, stale: bool = False) -> str:
    """Format a single decision as Markdown list item."""
    id_prefix = d["id"][:8]
    title = d.get("title", "")
    status = "STALE" if stale else d.get("staleness_status", "fresh")
    rationale = d.get("rationale", "") or ""
    rationale_short = rationale[:120] + "..." if len(rationale) > 120 else rationale
    files = ", ".join(d.get("files", [])[:3])
    parts = [f"- [{id_prefix}] {title}"]
    parts.append(f"  Status: {status}")
    if files:
        parts.append(f"  Files: {files}")
    if rationale_short:
        parts.append(f"  Rationale: {rationale_short}")
    return "\n".join(parts)


def on_session_start_decisions(data: dict[str, Any]) -> str | None:
    """Surface related and stale decisions at session start. Never raises."""
    try:
        cwd = data.get("cwd", ".")
        repo_path = _find_git_root(cwd)
        if not repo_path:
            return None

        config = _load_decisions_config(repo_path)
        if not config.get("show_related_on_start", False):
            return None

        from ..core.decisions import get_decision, list_decisions
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            sections = []
            seen_ids: set[str] = set()

            # 1. Recently changed files → linked decisions (using DB-level file_path filter)
            changed_files = _get_recently_changed_files(repo_path)
            file_related = []
            if changed_files:
                for f in changed_files:
                    for d in list_decisions(conn, file_path=f, limit=10):
                        if d["id"] not in seen_ids:
                            full = get_decision(conn, d["id"]) or d
                            file_related.append(full)
                            seen_ids.add(d["id"])
                        if len(seen_ids) >= 5:
                            break
                    if len(seen_ids) >= 5:
                        break

                if file_related:
                    entries = [_format_decision_entry(d) for d in file_related[:5]]
                    sections.append(
                        "## Related Decisions\n\n"
                        "The following decisions are linked to recently changed files:\n\n"
                        + "\n\n".join(entries)
                    )

            # 2. Stale decisions
            stale = list_decisions(conn, staleness_status="stale", limit=10)
            stale_new = [d for d in stale if d["id"] not in seen_ids]
            remaining = 5 - len(seen_ids)
            if stale_new and remaining > 0:
                stale_entries = []
                for d in stale_new[:remaining]:
                    full = get_decision(conn, d["id"]) or d
                    stale_entries.append(_format_decision_entry(full, stale=True))
                    seen_ids.add(d["id"])
                sections.append(
                    "## Stale Decisions (action needed)\n\n"
                    + "\n\n".join(stale_entries)
                    + "\n\nConsider updating stale decisions or marking them as superseded."
                )

            if not sections:
                return None

            return "\n\n".join(sections)
        finally:
            conn.close()
    except Exception as exc:
        try:
            repo_path = _find_git_root(data.get("cwd", "."))
            if repo_path:
                _record_hook_warning(repo_path, "session_start_decisions", exc)
        except Exception:
            pass
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_hooks.py::TestOnSessionStartDecisions -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/hooks/decision_hooks.py tests/test_decision_hooks.py
git commit -m "feat(hooks): add on_session_start_decisions for context surfacing"
```

---

### Task 5: Implement `maybe_extract_decisions` (SessionEnd background extraction)

**Files:**
- Modify: `src/entirecontext/hooks/decision_hooks.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_decision_hooks.py`:

```python
import json
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


class TestMaybeExtractDecisions:
    def _setup_session_with_summaries(self, ec_db, summaries):
        """Helper: create session with turns that have given summaries."""
        from entirecontext.core.project import get_project

        project = get_project(ec_db)
        session = create_session(ec_db, project["id"])
        for i, summary in enumerate(summaries):
            turn = create_turn(ec_db, session["id"], i + 1, user_message=f"msg {i}")
            ec_db.execute(
                "UPDATE turns SET assistant_summary = ?, turn_status = 'completed' WHERE id = ?",
                (summary, turn["id"]),
            )
        ec_db.commit()
        return session

    def test_disabled_by_config(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": False, "extract_keywords": ["decided"]},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), "fake-session-id")

    def test_no_keyword_matches_no_worker(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["just a normal conversation"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0

    def test_keyword_match_launches_worker(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(kw) or 0,
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.worker_status",
            lambda *a, **kw: {"running": False, "pid": None},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 1

    def test_worker_already_running_skips(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.worker_status",
            lambda *a, **kw: {"running": True, "pid": 999},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0

    def test_idempotency_marker_skips(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        # Set marker
        ec_db.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"decisions_extracted": True}), session["id"]),
        )
        ec_db.commit()

        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_hooks.py::TestMaybeExtractDecisions -v`
Expected: FAIL with `ImportError: cannot import name 'maybe_extract_decisions'`

- [ ] **Step 3: Implement `maybe_extract_decisions`**

Add to `src/entirecontext/hooks/decision_hooks.py`:

```python
from ..core.async_worker import launch_worker, worker_status


def _session_has_extraction_marker(conn, session_id: str) -> bool:
    """Check if session metadata has decisions_extracted flag."""
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["metadata"]:
        return False
    try:
        import json
        meta = json.loads(row["metadata"])
        return meta.get("decisions_extracted", False) is True
    except (ValueError, TypeError):
        return False


def _summaries_match_keywords(summaries: list[str], keywords: list[str]) -> bool:
    """Check if any summary matches any keyword."""
    if not keywords:
        return False
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    return any(pattern.search(s) for s in summaries)


def maybe_extract_decisions(repo_path: str, session_id: str) -> None:
    """Launch background decision extraction if keywords match. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_extract", False):
            return

        from ..db import get_db

        conn = get_db(repo_path)
        try:
            # Idempotency check
            if _session_has_extraction_marker(conn, session_id):
                return

            # Collect summaries
            rows = conn.execute(
                "SELECT assistant_summary FROM turns "
                "WHERE session_id = ? AND assistant_summary IS NOT NULL "
                "ORDER BY turn_number ASC",
                (session_id,),
            ).fetchall()
            summaries = [r["assistant_summary"] for r in rows if r["assistant_summary"]]
            if not summaries:
                return

            # Keyword gate
            keywords = config.get("extract_keywords", [])
            if not _summaries_match_keywords(summaries, keywords):
                return

            # Check worker slot
            if worker_status(repo_path, pid_name="worker-decision").get("running"):
                return

            # Launch background worker
            import sys
            launch_worker(
                repo_path,
                [sys.executable, "-m", "entirecontext.cli", "decision", "extract-from-session", session_id],
                pid_name="worker-decision",
            )
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_extract_decisions", exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_hooks.py::TestMaybeExtractDecisions -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/hooks/decision_hooks.py tests/test_decision_hooks.py
git commit -m "feat(hooks): add maybe_extract_decisions with keyword gate and background worker"
```

---

### Task 6: Implement `extract-from-session` CLI command

**Files:**
- Modify: `src/entirecontext/cli/decisions_cmds.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_decision_hooks.py`:

```python
class TestExtractFromSessionCLI:
    def _setup_session_with_turns(self, ec_db, turn_data):
        """Helper: create session with turns. turn_data = [(summary, files_touched), ...]"""
        from entirecontext.core.project import get_project

        project = get_project(ec_db)
        session = create_session(ec_db, project["id"])
        for i, (summary, files) in enumerate(turn_data):
            turn = create_turn(ec_db, session["id"], i + 1, user_message=f"msg {i}")
            ec_db.execute(
                "UPDATE turns SET assistant_summary = ?, files_touched = ?, turn_status = 'completed' WHERE id = ?",
                (summary, json.dumps(files) if files else None, turn["id"]),
            )
        ec_db.commit()
        return session

    def test_creates_decisions_from_llm_response(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("We decided to use Redis for caching", ["src/cache.py"]),
        ])
        llm_response = json.dumps([
            {"title": "Use Redis for caching", "rationale": "Fast in-memory store", "scope": "caching", "rejected_alternatives": ["memcached"]},
        ])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        titles = [d["title"] for d in decisions]
        assert "Use Redis for caching" in titles

        # Check idempotency marker
        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is True

    def test_auto_links_files(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("We decided to use Redis", ["src/cache.py", "src/config.py"]),
        ])
        llm_response = json.dumps([
            {"title": "Use Redis", "rationale": "Fast", "scope": "cache", "rejected_alternatives": []},
        ])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        d = get_decision(ec_db, decisions[0]["id"])
        assert "src/cache.py" in d.get("files", [])

    def test_empty_array_sets_marker(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("We decided nothing", []),
        ])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: "[]",
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is True

    def test_invalid_json_no_marker(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("We decided something", []),
        ])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: "not json at all",
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is not True

    def test_max_5_decisions(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("Many decisions decided", []),
        ])
        llm_response = json.dumps([
            {"title": f"Decision {i}", "rationale": "r", "scope": "s", "rejected_alternatives": []}
            for i in range(8)
        ])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        assert len(decisions) <= 5

    def test_idempotency_second_run_skips(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(ec_db, [
            ("We decided X", []),
        ])
        call_count = []
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: (call_count.append(1), "[]")[1],
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        assert len(call_count) == 1  # LLM called only once
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_hooks.py::TestExtractFromSessionCLI -v`
Expected: FAIL with `ImportError: cannot import name '_extract_from_session_impl'`

- [ ] **Step 3: Implement in `decisions_cmds.py`**

Add to `src/entirecontext/cli/decisions_cmds.py`, before the `register` function:

```python
def _get_llm_response(summaries: str, repo_path: str) -> str:
    """Call LLM to extract decisions. Separated for testability."""
    from ..core.config import load_config
    from ..core.llm import get_backend

    config = load_config(repo_path)
    backend_name = config.get("futures", {}).get("default_backend", "openai")
    model = config.get("futures", {}).get("default_model", None)
    backend = get_backend(backend_name, model=model)

    system = (
        "Extract architectural/technical decisions from this coding session. "
        "Return a JSON array: [{\"title\": str, \"rationale\": str, \"scope\": str, \"rejected_alternatives\": [str]}] "
        "Only include actual decisions (choosing one approach over another), "
        "not tasks, plans, or status updates. "
        "Return [] if no decisions were made."
    )
    return backend.complete(system, summaries)


def _extract_from_session_impl(conn, session_id: str, repo_path: str) -> None:
    """Core extraction logic. Used by CLI command and testable directly."""
    import json as _json
    import re

    from ..core.config import load_config
    from ..core.decisions import create_decision, link_decision_to_file

    # Idempotency check
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row and row["metadata"]:
        try:
            meta = _json.loads(row["metadata"])
            if meta.get("decisions_extracted") is True:
                return
        except (ValueError, TypeError):
            pass

    # Collect summaries with files
    rows = conn.execute(
        "SELECT assistant_summary, files_touched FROM turns "
        "WHERE session_id = ? AND assistant_summary IS NOT NULL "
        "ORDER BY turn_number ASC",
        (session_id,),
    ).fetchall()
    if not rows:
        return

    summaries = [r["assistant_summary"] for r in rows if r["assistant_summary"]]
    all_files: set[str] = set()
    for r in rows:
        if r["files_touched"]:
            try:
                files = _json.loads(r["files_touched"])
                if isinstance(files, list):
                    all_files.update(files)
            except (ValueError, TypeError):
                pass

    # Keyword filter
    config = load_config(repo_path)
    keywords = config.get("decisions", {}).get("extract_keywords", [])
    if keywords:
        pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
        summaries = [s for s in summaries if pattern.search(s)]
    if not summaries:
        return

    # LLM call
    combined = "\n".join(summaries)
    raw = _get_llm_response(combined, repo_path)

    # Parse
    try:
        decisions_data = _json.loads(raw)
    except (ValueError, TypeError):
        console.print(f"[yellow]Invalid JSON from LLM, skipping extraction[/yellow]")
        return

    if not isinstance(decisions_data, list):
        return

    # Truncate to 5
    decisions_data = decisions_data[:5]

    # Create decisions
    for item in decisions_data:
        try:
            if not isinstance(item, dict) or "title" not in item:
                continue
            d = create_decision(
                conn,
                title=item["title"],
                rationale=item.get("rationale"),
                scope=item.get("scope"),
                rejected_alternatives=item.get("rejected_alternatives"),
            )
            # Auto-link files
            for f in all_files:
                try:
                    link_decision_to_file(conn, d["id"], f)
                except Exception:
                    pass
        except Exception:
            continue

    # Set idempotency marker (null-safe)
    conn.execute(
        "UPDATE sessions SET metadata = json_set(COALESCE(metadata, '{}'), '$.decisions_extracted', json('true')) WHERE id = ?",
        (session_id,),
    )
    conn.commit()


@decision_app.command("extract-from-session")
def decision_extract_from_session(
    session_id: str = typer.Argument(..., help="Session ID to extract decisions from"),
):
    """Extract decisions from a session using LLM (background worker target)."""
    conn = _get_repo_connection()
    try:
        from ..core.project import find_git_root

        repo_path = find_git_root()
        if not repo_path:
            console.print("[red]Not in a git repository.[/red]")
            raise typer.Exit(1)
        _extract_from_session_impl(conn, session_id, repo_path)
    except Exception as exc:
        console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_hooks.py::TestExtractFromSessionCLI -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/cli/decisions_cmds.py tests/test_decision_hooks.py
git commit -m "feat(cli): add extract-from-session command with idempotency and auto file linking"
```

---

### Task 7: Wire hooks into handler and session_lifecycle

**Files:**
- Modify: `src/entirecontext/hooks/handler.py`
- Modify: `src/entirecontext/hooks/session_lifecycle.py`
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_decision_hooks.py`:

```python
import io
import sys


class TestHandlerIntegration:
    def test_session_start_prints_decisions(self, ec_repo, ec_db, monkeypatch):
        """Verify _handle_session_start prints decision context to stdout."""
        create_decision(ec_db, title="Integration test decision", staleness_status="stale")
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )

        from entirecontext.hooks.handler import _handle_session_start

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        _handle_session_start({"cwd": str(ec_repo), "session_id": "test-session"})
        output = captured.getvalue()
        assert "Integration test decision" in output

    def test_session_end_calls_decision_hooks(self, ec_repo, ec_db, monkeypatch, isolated_global_db):
        from entirecontext.core.session import create_session

        session = create_session(ec_db, session_type="claude", workspace_path=str(ec_repo))
        stale_called = []
        extract_called = []
        monkeypatch.setattr(
            "entirecontext.hooks.session_lifecycle.maybe_check_stale_decisions",
            lambda rp: stale_called.append(rp),
        )
        monkeypatch.setattr(
            "entirecontext.hooks.session_lifecycle.maybe_extract_decisions",
            lambda rp, sid: extract_called.append((rp, sid)),
        )
        from entirecontext.hooks.handler import _handle_session_end

        _handle_session_end({"cwd": str(ec_repo), "session_id": session["id"]})
        assert len(stale_called) == 1
        assert len(extract_called) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_hooks.py::TestHandlerIntegration -v`
Expected: FAIL (hooks not wired yet)

- [ ] **Step 3: Modify `handler.py` — print decision context on SessionStart**

In `src/entirecontext/hooks/handler.py`, change `_handle_session_start`:

```python
def _handle_session_start(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_session_start

    on_session_start(data)

    try:
        from .decision_hooks import on_session_start_decisions

        result = on_session_start_decisions(data)
        if result:
            print(result)
    except Exception:
        pass
    return 0
```

- [ ] **Step 4: Modify `session_lifecycle.py` — call decision hooks on SessionEnd**

In `src/entirecontext/hooks/session_lifecycle.py`, at the end of `on_session_end` (after line 280), add:

```python
    _maybe_check_stale_decisions(repo_path)
    _maybe_extract_decisions(repo_path, session_id)
```

And add these wrapper functions at the bottom of the file (before the final empty line):

```python
def _maybe_check_stale_decisions(repo_path: str) -> None:
    try:
        from .decision_hooks import maybe_check_stale_decisions
        maybe_check_stale_decisions(repo_path)
    except Exception as exc:
        _record_hook_warning(repo_path, "decision_stale_dispatch", exc)


def _maybe_extract_decisions(repo_path: str, session_id: str) -> None:
    try:
        from .decision_hooks import maybe_extract_decisions
        maybe_extract_decisions(repo_path, session_id)
    except Exception as exc:
        _record_hook_warning(repo_path, "decision_extract_dispatch", exc)
```

The test monkeypatches the `decision_hooks` module directly (not `session_lifecycle`) since the wrappers use deferred imports. Update `test_session_end_calls_decision_hooks` test monkeypatch targets:
```python
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.maybe_check_stale_decisions",
            lambda rp: stale_called.append(rp),
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.maybe_extract_decisions",
            lambda rp, sid: extract_called.append((rp, sid)),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_hooks.py::TestHandlerIntegration -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add src/entirecontext/hooks/handler.py src/entirecontext/hooks/session_lifecycle.py tests/test_decision_hooks.py
git commit -m "feat(hooks): wire decision hooks into handler and session_lifecycle"
```

---

### Task 8: Validate stdout contract and implement fallback

**Files:**
- Modify: `src/entirecontext/hooks/decision_hooks.py`
- Modify: `src/entirecontext/hooks/handler.py`
- Test: `tests/test_decision_hooks.py`

This task validates the design assumption that Claude Code captures hook stdout as `additionalContext`. If validation fails, implement the `.entirecontext/decisions-context.md` file fallback.

- [ ] **Step 1: Write integration test for stdout output**

Append to `tests/test_decision_hooks.py`:

```python
class TestStdoutContract:
    def test_handler_prints_decision_context(self, ec_repo, ec_db, monkeypatch, capsys):
        """Verify _handle_session_start actually prints decision text to stdout."""
        create_decision(ec_db, title="Stdout test decision", staleness_status="stale")
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.handler import _handle_session_start

        _handle_session_start({"cwd": str(ec_repo), "session_id": "stdout-test"})
        captured = capsys.readouterr()
        assert "Stdout test decision" in captured.out
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_decision_hooks.py::TestStdoutContract -v`
Expected: PASS (handler already prints in Task 7)

- [ ] **Step 3: Manual validation**

Run a real Claude Code session with `show_related_on_start = true` in `.entirecontext/config.toml` and verify the output appears as `additionalContext` in the system prompt. Document the result in the commit message.

- [ ] **Step 4: If stdout doesn't work, implement file fallback**

If manual validation shows stdout is NOT captured as agent context, add a fallback in `on_session_start_decisions` that writes the output to `.entirecontext/decisions-context.md`:

```python
# At the end of on_session_start_decisions, before returning:
from pathlib import Path
context_file = Path(repo_path) / ".entirecontext" / "decisions-context.md"
context_file.parent.mkdir(parents=True, exist_ok=True)
context_file.write_text(output, encoding="utf-8")
```

If stdout DOES work, skip this step and note "stdout validated" in the commit.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "feat(hooks): validate stdout contract for decision context surfacing"
```

---

### Task 9: Full integration test and cleanup

**Files:**
- Test: `tests/test_decision_hooks.py`

- [ ] **Step 1: Run the complete test file**

Run: `uv run pytest tests/test_decision_hooks.py -v`
Expected: All tests pass

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `uv run pytest -x`
Expected: All tests pass

- [ ] **Step 3: Run linter**

Run: `uv run ruff check src/entirecontext/hooks/decision_hooks.py src/entirecontext/core/async_worker.py src/entirecontext/cli/decisions_cmds.py tests/test_decision_hooks.py --fix`
Expected: No errors (or auto-fixed)

- [ ] **Step 4: Run formatter**

Run: `uv run ruff format src/entirecontext/hooks/decision_hooks.py src/entirecontext/core/async_worker.py src/entirecontext/cli/decisions_cmds.py tests/test_decision_hooks.py`
Expected: Files formatted

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -u
git commit -m "style: format decision hooks code"
```

- [ ] **Step 6: Final full test run**

Run: `uv run pytest -x -v`
Expected: All tests pass
