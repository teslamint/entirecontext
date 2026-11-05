"""CLI-level enrichment retry and overlap checks using a fixture repository."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread, current_thread
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core import auto_assess
from entirecontext.cli.futures_cmds import futures_enrich_backlog
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.futures import create_assessment
from entirecontext.core.project import get_repo_roots
from tests.test_auto_assess import _create_test_session, _get_head


def _rows(ec_repo, ec_db, count):
    session = _create_test_session(ec_db)
    ids = []
    for _ in range(count):
        cp = create_checkpoint(ec_db, session, _get_head(ec_repo))
        ids.append(create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")["id"])
    ec_db.commit()
    return ids


def _invoke(ec_repo):
    roots = get_repo_roots(str(ec_repo))
    with patch("entirecontext.core.project.get_repo_roots", return_value=roots):
        return CliRunner().invoke(app, ["futures", "enrich-backlog"])


def test_failure_stop_backoff_and_retry(ec_repo, ec_db, monkeypatch):
    _rows(ec_repo, ec_db, 2)
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(complete=lambda *_: (_ for _ in ()).throw(RuntimeError("auth")))

    monkeypatch.setattr("entirecontext.core.llm.get_backend", fail)
    monkeypatch.setattr("entirecontext.core.enrichment_claims.time.time", lambda: 1000)
    first = _invoke(ec_repo)
    assert first.exit_code == 0, first.output
    assert len(calls) == 2
    second = _invoke(ec_repo)
    assert second.exit_code == 0, second.output
    assert len(calls) == 2
    monkeypatch.setattr("entirecontext.core.enrichment_claims.time.time", lambda: 1900)
    third = _invoke(ec_repo)
    assert third.exit_code == 0, third.output
    assert len(calls) > 2


def test_success_once_and_overlap(ec_repo, ec_db, monkeypatch):
    _rows(ec_repo, ec_db, 2)
    calls = []
    guard = Lock()
    barrier = Barrier(2)

    class Backend:
        def complete(self, *_):
            with guard:
                calls.append(1)
            return '{"verdict": "neutral", "impact_summary": "ok"}'

    monkeypatch.setattr("entirecontext.core.llm.get_backend", lambda *a, **kw: Backend())
    with ThreadPoolExecutor(max_workers=2) as pool:

        def run():
            barrier.wait()
            return _invoke(ec_repo)

        results = list(pool.map(lambda _: run(), range(2)))
    assert all(result.exit_code == 0 for result in results), [result.output for result in results]
    assert len(calls) == 2
    assert _invoke(ec_repo).exit_code == 0
    assert len(calls) == 2


def test_stale_candidate_snapshot_is_revalidated_after_claim(ec_repo, ec_db, monkeypatch):
    """Worker B snapshots candidates, worker A finishes the row and clears its lease, then B claims it."""
    _rows(ec_repo, ec_db, 1)
    calls = []
    guard = Lock()
    snapshots_taken = Barrier(2)
    a_finished = Event()

    class Backend:
        def complete(self, *_):
            with guard:
                calls.append(current_thread().name)
            return '{"verdict": "neutral", "impact_summary": "ok"}'

    monkeypatch.setattr("entirecontext.core.llm.get_backend", lambda *a, **kw: Backend())
    original = auto_assess.get_enrichment_candidates

    def snapshot_then_sync(*args, **kwargs):
        rows = original(*args, **kwargs)
        snapshots_taken.wait(timeout=10)
        if current_thread().name == "worker-B":
            assert a_finished.wait(timeout=30)
        return rows

    monkeypatch.setattr(auto_assess, "get_enrichment_candidates", snapshot_then_sync)
    errors = {}
    roots = get_repo_roots(str(ec_repo))
    monkeypatch.setattr("entirecontext.core.project.get_repo_roots", lambda *a, **kw: roots)

    def run(name):
        # Direct call: CliRunner swaps sys.stdout globally and is not thread-safe.
        try:
            futures_enrich_backlog()
        except BaseException as exc:  # noqa: BLE001 - surfaced via the assertion below
            errors[name] = exc
        finally:
            if name == "worker-A":
                a_finished.set()

    threads = [Thread(target=run, args=(name,), name=name) for name in ("worker-A", "worker-B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == {}
    assert calls == ["worker-A"]
