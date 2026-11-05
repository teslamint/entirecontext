"""Behavioral tests for the per-repository enrichment lease store."""

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context

from entirecontext.core.enrichment_claims import claim_candidates, record_failure, record_success, release_claim


def _claim_in_process(args):
    return claim_candidates(*args, now=100)


def test_concurrent_claims(tmp_path):
    candidates = [{"id": str(i)} for i in range(30)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        batches = list(pool.map(lambda _: claim_candidates(str(tmp_path), candidates, now=100), range(16)))
    ids = [row["id"] for batch in batches for row in batch]
    assert len(ids) == len(set(ids)) == 30

    other = tmp_path / "process"
    with get_context("spawn").Pool(2) as pool:
        batches = pool.map(_claim_in_process, [(str(other), candidates)] * 2)
    ids = [row["id"] for batch in batches for row in batch]
    assert len(ids) == len(set(ids)) == 20


def test_expiry_backoff_attempts_and_release(tmp_path):
    repo = str(tmp_path)
    rows = [{"id": "a"}, {"id": "b"}]
    assert claim_candidates(repo, rows, max_claims=1, lease_seconds=600, now=0) == rows[:1]
    assert claim_candidates(repo, rows[:1], lease_seconds=600, now=599) == []
    assert claim_candidates(repo, rows[:1], lease_seconds=600, now=600) == rows[:1]
    record_failure(repo, "a", now=600, base_seconds=10, cap_seconds=25)
    assert claim_candidates(repo, rows[:1], now=619) == []
    assert claim_candidates(repo, rows[:1], now=620) == rows[:1]
    record_failure(repo, "a", now=620, base_seconds=10, cap_seconds=25)
    assert claim_candidates(repo, rows[:1], now=644) == []
    assert claim_candidates(repo, rows[:1], now=645) == rows[:1]
    release_claim(repo, "a", now=645)
    assert claim_candidates(repo, rows[:1], now=645) == rows[:1]
    record_success(repo, "a")
    assert claim_candidates(repo, rows[:1], now=645) == rows[:1]


def test_max_attempts_and_corrupt_file(tmp_path):
    repo = str(tmp_path)
    path = tmp_path / ".entirecontext" / "state" / "enrich-claims.json"
    path.parent.mkdir(parents=True)
    path.write_text("invalid")
    row = [{"id": "a"}]
    assert claim_candidates(repo, row, max_attempts=2, lease_seconds=1, now=0) == row
    assert claim_candidates(repo, row, max_attempts=2, lease_seconds=1, now=1) == row
    assert claim_candidates(repo, row, max_attempts=2, lease_seconds=1, now=2) == []
