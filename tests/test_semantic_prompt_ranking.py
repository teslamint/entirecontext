"""Opt-in semantic signal tests for the decision ranker."""

import json
from contextlib import contextmanager
from uuid import UUID
import struct
import threading

import pytest

from entirecontext.core.config import DEFAULT_CONFIG
from entirecontext.core.decisions import rank_related_decisions


def _seed(conn):
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, updated_at) VALUES ('semantic', 'unrelated words', 'none', '2020-01-01')"
    )
    conn.execute("INSERT INTO decisions (id, title, rationale) VALUES ('baseline', 'matching keyword', 'none')")
    # 25 newer decisions fill the recent-decision padding, so 'semantic' can enter only through its score.
    for i in range(25):
        conn.execute(
            "INSERT INTO decisions (id, title, rationale, updated_at) VALUES (?, 'filler entry', 'none', '2030-01-01')",
            (f"filler-{i}",),
        )
    conn.commit()


def test_semantic_only_candidate_surfaces(ec_db):
    _seed(ec_db)
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        semantic_scores={"semantic": 0.8},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    match = next(item for item in ranked if item["id"] == "semantic")
    assert match["score_breakdown"]["semantic"] == 2.4
    assert match["base_score"] >= 2.4


def test_semantic_below_threshold_adds_nothing(ec_db):
    _seed(ec_db)
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        semantic_scores={"semantic": 0.29},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    assert "semantic" not in {item["id"] for item in ranked}


def test_without_semantic_scores_breakdown_is_unchanged(ec_db):
    """MCP and CLI callers pass no scores; their score_breakdown keys must not change."""
    _seed(ec_db)
    ranked = rank_related_decisions(ec_db, diff_text="matching keyword")
    assert ranked
    assert all("semantic" not in item["score_breakdown"] for item in ranked)
    assert "semantic" not in {item["id"] for item in ranked}
    assert DEFAULT_CONFIG["decisions"]["semantic"]["enabled"] is False


def test_semantic_candidate_respects_until(ec_db):
    """A decision created after the cutoff stays out even with a high semantic score."""
    _seed(ec_db)
    ec_db.execute(
        "INSERT INTO decisions (id, title, rationale, created_at) VALUES ('future', 'later', 'none', '2027-01-01')"
    )
    ec_db.commit()
    ranked = rank_related_decisions(
        ec_db,
        diff_text="matching keyword",
        until="2026-01-01",
        semantic_scores={"future": 0.99},
        semantic_weight=3.0,
        semantic_min_similarity=0.3,
    )
    assert "future" not in {item["id"] for item in ranked}


def _enabled(ec_repo):
    (ec_repo / ".entirecontext" / "config.toml").write_text("[decisions.semantic]\nenabled = true\n")


def _hook(ec_repo, session="session-1", prompt="semantic lookup"):
    from entirecontext.hooks.handler import _handle_user_prompt

    return _handle_user_prompt({"cwd": str(ec_repo), "session_id": session, "prompt": prompt})


def _session(ec_db):
    ec_db.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) VALUES ('session-1', (SELECT id FROM projects LIMIT 1), 'claude', '2026-01-01', '2026-01-01')"
    )
    ec_db.commit()


def _vector(*values):
    return struct.pack(f"{len(values)}f", *values)


def test_pending_prompt_file_is_redacted_and_private(ec_repo, monkeypatch):
    from entirecontext.core.semantic_scores import write_pending_prompt

    config = {"capture": {"exclusions": {"enabled": True, "redact_patterns": ["privateword"]}}}
    path = write_pending_prompt(str(ec_repo), "s/1", "privateword ghp_abcdefghijklmnopqrstuvwxyz1234567890", config)
    assert path.name == "semantic-prompt-s_1.txt"
    assert "privateword" not in path.read_text()
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    target = ec_repo / "untouched.txt"
    target.write_text("untouched")
    temp = path.parent / f".{path.name}.{__import__('os').getpid()}.00000000000000000000000000000001.tmp"
    temp.symlink_to(target)
    monkeypatch.setattr("entirecontext.core.semantic_scores.uuid4", lambda: UUID(int=1))
    with pytest.raises(FileExistsError):
        write_pending_prompt(str(ec_repo), "s/1", "new", config)
    assert target.read_text() == "untouched"


def test_prompt_replaced_during_processing_is_not_deleted(ec_repo):
    from entirecontext.core.semantic_scores import (
        publish_scores_if_current,
        take_pending_prompts,
        write_pending_prompt,
    )

    write_pending_prompt(str(ec_repo), "s", "first", {})
    claimed = take_pending_prompts(str(ec_repo))[0][1]
    write_pending_prompt(str(ec_repo), "s", "second", {})
    assert not publish_scores_if_current(str(ec_repo), "s", {"d": 0.8}, model="m", top_n=20)
    claimed.unlink()
    assert (ec_repo / ".entirecontext/state/semantic-prompt-s.txt").read_text() == "second"


@pytest.mark.parametrize(
    "case",
    [
        "missing package",
        "model load error",
        "no vectors",
        "dimension mismatch",
        "corrupt scores file",
        "stale scores file",
        "model mismatch",
        "superseded by newer prompt",
        "valid scores",
    ],
)
def test_semantic_fail_closed(ec_repo, ec_db, monkeypatch, capsys, case):
    from entirecontext.core.semantic_scores import read_fresh_scores, write_pending_prompt, write_scores
    from entirecontext.core.semantic_worker import run_semantic_worker

    _seed(ec_db)
    _session(ec_db)
    _enabled(ec_repo)
    state = ec_repo / ".entirecontext/state"
    if case in {"missing package", "model load error", "no vectors", "dimension mismatch"}:
        write_pending_prompt(str(ec_repo), "session-1", "semantic lookup", {})
        if case == "dimension mismatch":
            ec_db.execute(
                "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('e', 'decision', 'semantic', 'all-MiniLM-L6-v2', ?, 3, 'h')",
                (_vector(1, 0, 0),),
            )
            ec_db.commit()

        def factory(_model):
            if case == "missing package":
                raise ImportError("package unavailable")
            if case == "model load error":
                raise OSError("model files unavailable offline")
            return lambda _text: _vector(1, 0)

        run_semantic_worker(str(ec_repo), embedder_factory=factory)
        assert not list(state.glob("semantic-prompt-*"))
        if case in {"missing package", "model load error"}:
            warnings = ec_db.execute(
                "SELECT error_class, message FROM operation_events WHERE phase = 'semantic_worker' AND status = 'warning'"
            ).fetchall()
            assert len(warnings) == 1
            assert "unavailable" not in warnings[0]["message"]
    else:
        write_scores(str(ec_repo), "session-1", {"semantic": 0.9}, model="all-MiniLM-L6-v2", top_n=20)
        path = state / "semantic-scores-session-1.json"
        if case == "corrupt scores file":
            path.write_text("{")
        elif case == "stale scores file":
            payload = json.loads(path.read_text())
            payload["computed_at"] = "2000-01-01T00:00:00+00:00"
            path.write_text(json.dumps(payload))
        elif case == "model mismatch":
            payload = json.loads(path.read_text())
            payload["model"] = "other"
            path.write_text(json.dumps(payload))
        elif case == "superseded by newer prompt":
            write_pending_prompt(str(ec_repo), "session-1", "newer", {})
    scores = read_fresh_scores(str(ec_repo), "session-1", model="all-MiniLM-L6-v2", max_age_seconds=900)
    assert (scores is not None) == (case == "valid scores")
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: None)
    _hook(ec_repo)
    output = capsys.readouterr().out
    assert ("unrelated words" in output) == (case == "valid scores")


def test_default_config_never_launches_semantic_worker(ec_repo, ec_db, monkeypatch, capsys):
    from entirecontext.core.semantic_scores import write_scores

    _seed(ec_db)
    _session(ec_db)
    launches = []
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: launches.append(a))
    _hook(ec_repo)
    without_scores = capsys.readouterr().out
    # A fresh scores file left from an earlier opt-in must be ignored while the signal is off.
    write_scores(str(ec_repo), "session-1", {"semantic": 0.9}, model="all-MiniLM-L6-v2", top_n=20)
    _hook(ec_repo)
    with_scores = capsys.readouterr().out
    assert "unrelated words" not in with_scores
    assert with_scores == without_scores
    assert not launches
    assert not list((ec_repo / ".entirecontext/state").glob("semantic-prompt-*"))
    _enabled(ec_repo)
    _hook(ec_repo)
    assert len(launches) == 1


@pytest.mark.parametrize(
    "gate", ["none", "auto_capture", "experiment", "injection", "semantic", "capture_disabled", "skip_turn"]
)
def test_launch_conditions_gate_semantic_worker(ec_repo, ec_db, monkeypatch, gate):
    _session(ec_db)
    _enabled(ec_repo)
    cfg = ec_repo / ".entirecontext/config.toml"
    additions = {
        "none": "",
        "auto_capture": "[capture]\nauto_capture = false\n",
        "experiment": '[decisions.injection]\nexperiment_block = "off"\n',
        "injection": "[decisions.injection]\ninject_on_user_prompt = false\n",
        "semantic": None,
        "skip_turn": '[capture.exclusions]\nenabled = true\ncontent_patterns = ["semantic lookup"]\n',
    }
    if gate == "capture_disabled":
        ec_db.execute("UPDATE sessions SET metadata = '{\"capture_disabled\": true}' WHERE id = 'session-1'")
        ec_db.commit()
    elif gate == "semantic":
        cfg.write_text("[decisions.semantic]\nenabled = false\n")
    else:
        # Append, so [decisions.semantic] enabled = true stays and only the gate under test blocks.
        cfg.write_text(cfg.read_text() + additions[gate])
    launches = []
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: launches.append(a))
    _hook(ec_repo)
    pending = list((ec_repo / ".entirecontext/state").glob("semantic-prompt-*.txt"))
    if gate == "none":
        assert len(launches) == 1
        assert len(pending) == 1
    else:
        assert not launches
        assert not pending


def test_two_pass_semantic_candidate_surfaces_on_next_prompt(ec_repo, ec_db, monkeypatch, capsys):
    """Spec success criterion 3: prompt 1 queues the worker, prompt 2 injects a decision found only by its score."""
    from entirecontext.core.semantic_worker import run_semantic_worker

    _seed(ec_db)
    _session(ec_db)
    _enabled(ec_repo)
    launches = []
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: launches.append(a))
    _hook(ec_repo)
    assert "unrelated words" not in capsys.readouterr().out
    assert len(launches) == 1
    ec_db.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('e', 'decision', 'semantic', 'all-MiniLM-L6-v2', ?, 2, 'h')",
        (_vector(1, 0),),
    )
    ec_db.commit()
    # Run the worker that prompt 1 would have launched, in-process with a fake embedder.
    run_semantic_worker(str(ec_repo), embedder_factory=lambda _: lambda __: _vector(1, 0))
    _hook(ec_repo)
    assert "unrelated words" in capsys.readouterr().out


def test_semantic_worker_launches_after_ranking_timeout(ec_repo, ec_db, monkeypatch, capsys):
    import time

    _session(ec_db)
    _enabled(ec_repo)
    cfg = ec_repo / ".entirecontext/config.toml"
    cfg.write_text(cfg.read_text() + "[decisions.injection]\ninject_timeout_ms = 20\n")

    def slow(*a, **k):
        time.sleep(0.3)
        return [], [], None

    monkeypatch.setattr("entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt", slow)
    launches = []
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: launches.append(a))
    _hook(ec_repo)
    assert capsys.readouterr().out == ""
    assert len(launches) == 1


def test_concurrent_prompts_launch_one_semantic_worker(ec_repo, ec_db, monkeypatch):
    from entirecontext.core import async_worker
    from entirecontext.core.config import load_config
    from entirecontext.hooks.handler import _maybe_launch_semantic_worker

    _session(ec_db)
    _enabled(ec_repo)
    config = load_config(str(ec_repo))
    launched = []
    both_checked = threading.Barrier(2, timeout=2)

    def status(*a, **k):
        # Read the state before the barrier. Without the launch lock both threads read "not running",
        # meet at the barrier, and both launch. With the lock the second thread enters only after the
        # first launched, so it reads "running"; the first thread's barrier times out alone.
        running = bool(launched)
        try:
            both_checked.wait()
        except threading.BrokenBarrierError:
            pass
        return {"running": running}

    monkeypatch.setattr(async_worker, "worker_status", status)
    monkeypatch.setattr(async_worker, "launch_worker", lambda *a, **k: launched.append(a) or 123)
    threads = [
        threading.Thread(
            target=_maybe_launch_semantic_worker,
            args=({"session_id": f"session-{i}", "prompt": "semantic lookup"}, config, str(ec_repo), str(ec_repo)),
        )
        for i in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(launched) == 1


def test_prompt_arriving_at_worker_exit_is_processed(ec_repo, ec_db, monkeypatch):
    from entirecontext.core import semantic_worker
    from entirecontext.core.semantic_scores import write_pending_prompt

    _session(ec_db)
    _enabled(ec_repo)
    ec_db.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('e', 'decision', 'd', 'all-MiniLM-L6-v2', ?, 2, 'h')",
        (_vector(1, 0),),
    )
    ec_db.commit()
    original_lock = semantic_worker.file_lock
    exit_checks = 0

    @contextmanager
    def arriving(lock_path):
        nonlocal exit_checks
        if lock_path.name == "worker-semantic.lock":
            exit_checks += 1
            if exit_checks == 1:
                write_pending_prompt(str(ec_repo), "session-1", "late", {})
        with original_lock(lock_path):
            yield

    monkeypatch.setattr(semantic_worker, "file_lock", arriving)
    semantic_worker.run_semantic_worker(str(ec_repo), embedder_factory=lambda _: lambda __: _vector(1, 0))
    assert exit_checks >= 2
    assert (ec_repo / ".entirecontext/state/semantic-scores-session-1.json").exists()


def test_user_prompt_hook_surfaces_semantic_decision_within_budget(ec_repo, ec_db, monkeypatch, capsys):
    from entirecontext.core.semantic_scores import write_scores

    _seed(ec_db)
    _session(ec_db)
    _enabled(ec_repo)
    for i in range(973):
        ec_db.execute("INSERT INTO decisions (id, title, rationale) VALUES (?, 'filler entry', 'none')", (f"more-{i}",))
    ec_db.commit()
    monkeypatch.setattr("entirecontext.core.async_worker.launch_worker_exclusive", lambda *a, **k: None)
    scores = {"semantic": 0.9, **{f"more-{i}": 0.31 for i in range(19)}}
    for _ in range(20):
        write_scores(str(ec_repo), "session-1", scores, model="all-MiniLM-L6-v2", top_n=20)
        _hook(ec_repo)
        assert "unrelated words" in capsys.readouterr().out


def test_mixed_vector_dimensions_keep_matching_scores(ec_repo, ec_db):
    """One stale-dimension vector must not discard the scores of vectors that match the query."""
    from entirecontext.core.semantic_scores import read_fresh_scores, write_pending_prompt
    from entirecontext.core.semantic_worker import run_semantic_worker

    _session(ec_db)
    _enabled(ec_repo)
    ec_db.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('ok', 'decision', 'match', 'all-MiniLM-L6-v2', ?, 2, 'h')",
        (_vector(1, 0),),
    )
    ec_db.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('bad', 'decision', 'other', 'all-MiniLM-L6-v2', ?, 3, 'h')",
        (_vector(1, 0, 0),),
    )
    ec_db.commit()
    write_pending_prompt(str(ec_repo), "session-1", "semantic lookup", {})
    run_semantic_worker(str(ec_repo), embedder_factory=lambda _: lambda __: _vector(1, 0))
    scores = read_fresh_scores(str(ec_repo), "session-1", model="all-MiniLM-L6-v2", max_age_seconds=900)
    assert scores == {"match": 1.0}


def test_worker_discards_prompts_claimed_by_dead_worker(ec_repo, ec_db):
    """A worker killed after claiming leaves prompt text on disk; the next worker deletes it."""
    from entirecontext.core.semantic_worker import run_semantic_worker

    _enabled(ec_repo)
    state = ec_repo / ".entirecontext/state"
    state.mkdir(parents=True, exist_ok=True)
    orphan = state / "semantic-prompt-session-1.999999.abc.processing"
    orphan.write_text("redacted prompt")
    live = state / f"semantic-prompt-session-2.{__import__('os').getpid()}.abc.processing"
    live.write_text("in progress")
    run_semantic_worker(str(ec_repo), embedder_factory=lambda _: lambda __: _vector(1, 0))
    assert not orphan.exists()
    assert live.exists()


def test_invalid_semantic_settings_do_not_break_injection_when_disabled(ec_repo, ec_db, capsys):
    _seed(ec_db)
    _session(ec_db)
    (ec_repo / ".entirecontext" / "config.toml").write_text('[decisions.semantic]\nenabled = false\nweight = "bad"\n')
    _hook(ec_repo, prompt="matching keyword")
    assert "matching keyword" in capsys.readouterr().out


@pytest.mark.parametrize("setting", ['weight = "bad"', 'max_age_seconds = "bad"'])
def test_invalid_semantic_settings_fall_back_when_enabled(ec_repo, ec_db, capsys, setting):
    from entirecontext.core.semantic_scores import write_scores

    _seed(ec_db)
    _session(ec_db)
    (ec_repo / ".entirecontext" / "config.toml").write_text(f"[decisions.semantic]\nenabled = true\n{setting}\n")
    write_scores(str(ec_repo), "session-1", {"semantic": 0.9}, model="all-MiniLM-L6-v2", top_n=20)
    _hook(ec_repo, prompt="matching keyword")
    output = capsys.readouterr().out
    assert "matching keyword" in output
    assert "unrelated words" not in output


@pytest.mark.parametrize("value", ['"bad"', "-3"])
def test_invalid_top_n_uses_default(ec_repo, ec_db, value):
    from entirecontext.core.semantic_scores import read_fresh_scores, write_pending_prompt
    from entirecontext.core.semantic_worker import run_semantic_worker

    _session(ec_db)
    (ec_repo / ".entirecontext" / "config.toml").write_text(f"[decisions.semantic]\nenabled = true\ntop_n = {value}\n")
    ec_db.execute(
        "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) VALUES ('e', 'decision', 'd', 'all-MiniLM-L6-v2', ?, 2, 'h')",
        (_vector(1, 0),),
    )
    ec_db.commit()
    write_pending_prompt(str(ec_repo), "session-1", "semantic lookup", {})
    run_semantic_worker(str(ec_repo), embedder_factory=lambda _: lambda __: _vector(1, 0))
    assert read_fresh_scores(str(ec_repo), "session-1", model="all-MiniLM-L6-v2", max_age_seconds=900) == {"d": 1.0}
    assert not list((ec_repo / ".entirecontext/state").glob("semantic-prompt-*"))
