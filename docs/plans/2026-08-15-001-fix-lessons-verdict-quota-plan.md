---
schema: plan/v1
title: "Verdict-quota selection for get_lessons"
type: fix
status: draft
date: 2026-08-15
execution: code
---

# Verdict-quota selection for `get_lessons`

## Goal

`get_lessons` selects lessons with a flat recency window, so a run of routine `neutral`
assessments evicts the option-shaping lessons `LESSONS.md` exists to carry. Reserve a per-verdict
floor inside the same total cap, bounded so recency keeps at least half the budget. The `limit`
contract stays a total cap: no caller ever receives more rows than it asked for.

## Architecture notes

**The defect, measured.** `src/entirecontext/core/futures.py:142-148` is a single
`ORDER BY created_at DESC LIMIT ?` with no verdict partitioning. Measured in this worktree at
`74212bb` against `.entirecontext/db/local.db`:

| Query | Result |
|---|---|
| `get_lessons(conn)` returns | 50 rows — `expand` 1, `neutral` 49 |
| Corpus (`feedback IS NOT NULL`) holds | 120 rows — `neutral` 98, `expand` 22, `narrow` 0 |
| `awk` count of `###` entries in `LESSONS.md`'s Expand section | 1 |

So 21 of 22 `expand` lessons are evicted. **`narrow` is zero in the corpus, not evicted** — the
absence of a Narrow section in `LESSONS.md` is corpus truth, and no selection change can create
one. The ROADMAP row wording overstates this and U3 corrects it.

**The feedback loop that makes it worse.** Each assessment *of* the regenerated `LESSONS.md` is
itself a `neutral` row, so assessing the artifact evicts one more `expand` lesson from the window.
Four independent assessments record the same collapse: `ddcf264d`, `bbd6b204`, `b1302519`,
`2a7c4bcd`.

**Why a floor, not an equal split.** An equal split (`limit // 3`) would make `LESSONS.md`
one-third `expand` regardless of how the corpus actually skews, discarding recency as the primary
ordering. A small floor plus recency fill keeps the document recency-dominated — its existing
character — while guaranteeing the option-shaping exemplars survive.

**Why the floor budget is capped at half the limit.** A naive round-robin floor allocation
consumes the entire budget whenever `limit <= len(VALID_VERDICTS) * min_per_verdict`. Measured by
running the allocation standalone during planning: at `limit=9, min_per_verdict=5` an uncapped
allocation yields floors of 3/3/3, so all nine slots are quota and recency ordering disappears
completely; at `limit=10` it yields 4/3/3, again the whole budget. That is invisible on the
`LESSONS.md` path (`limit=50`) but changes `ec_lessons(limit=...)` for small limits — a caller
asking for three lessons would get one per verdict rather than the three newest. Capping the total
floor allocation at `limit // 2` fixes this with one expression and no special case:

| `limit` | Floors (`min_per_verdict=5`) | Floor share |
|---|---|---|
| 1 | 0 / 0 / 0 | 0% |
| 3 | 1 / 0 / 0 | 33% |
| 9 | 2 / 1 / 1 | 44% |
| 20 | 4 / 3 / 3 | 50% |
| 50 | 5 / 5 / 5 | 30% |

The production path is unchanged: at `limit=50, min_per_verdict=5` the cap is inactive and the
floors are the full 5/5/5. `min_per_verdict=0` disables floors entirely, which is the documented
escape hatch back to pure recency.

**No window function.** `ROW_NUMBER() OVER (PARTITION BY ...)` would express this in one query,
but `rg "ROW_NUMBER\(\) OVER|OVER \(PARTITION" src/entirecontext/` returns nothing — this
repository has no window-function precedent, and every aggregation in `core/futures.py` and
`core/auto_assess.py` uses plain SQL plus Python post-processing. Three bounded per-verdict
queries match the established style and carry no SQLite-version assumption. `VALID_VERDICTS`
(`core/futures.py:12`) has three members, so this is three small queries, each `LIMIT ?`-bounded.

**Known Pattern — the fix will revert itself if only the checkout is changed.**
`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md` records this exact
function reverting a shipped fix: hooks invoke `ec` from a uv tool install, not from the checkout,
so hook-driven `auto_distill` regenerates `LESSONS.md` with the stale code. Both copies reported
`0.14.0`, so no version comparison detects it. That document also warns that the repair destroys
the measurement, so the pre-repair install state must be recorded before reinstalling, and it
prescribes reinstalling **after merging** anything the hooks execute. U4 carries all three
obligations, and the post-merge half is registered as a Ship-phase obligation in Deferred to
Follow-Up Work because this plan's units end before merge.

**Sibling with the same shape, deliberately out of scope.**
`src/entirecontext/core/lesson_surfacing.py:11-27` (`get_surfaceable_lessons`) is a second
recency-ordered lessons query — `ORDER BY a.created_at DESC` at line 23, `LIMIT ?` at line 24 —
called by `rank_lessons_for_prompt` at line 110 with `limit=200`. Against a 120-row corpus it
evicts nothing today, so it is not the reported defect. It is also a different contract: it builds
a wide candidate set that `rank_lessons_for_prompt` then re-ranks by file overlap, so imposing a
document-shaped quota there could displace file-relevant candidates. Deferred, with the trigger
recorded.

**Naming precedent.** `core/auto_assess.py:237-262` already uses `per_verdict` as the key for
verdict-partitioned aggregation, so this plan uses `min_per_verdict` rather than inventing a new
vocabulary for the same partition.

**Vocabulary.** `CONCEPTS.md` defines no term for lesson, verdict, or assessment (verified:
`grep -i "lesson\|verdict\|assessment" CONCEPTS.md` returns nothing), so this plan introduces no
canonical-vocabulary conflict. It uses the terms as `core/futures.py` already does: an
*assessment* carries a *verdict* in `VALID_VERDICTS`; an assessment with non-null `feedback` is a
*lesson*.

## Assumption Recheck

No origin spec; no approved live assumptions to recheck.

Every factual claim above was measured in this worktree at `74212bb` during planning rather than
inherited from an approved artifact:

| Command | Observed |
|---|---|
| `uv run pytest tests/test_futures.py -q` | `14 passed in 1.94s` |
| `uv run mypy src/entirecontext/` | `Success: no issues found in 120 source files` |
| `uv run ruff check src/entirecontext/core/futures.py` | `All checks passed!` |
| `get_lessons(conn)` verdict census | `{'expand': 1, 'neutral': 49}`, 50 returned |
| `sqlite3 .entirecontext/db/local.db` verdict census | `neutral 98`, `expand 22`, total 120 |
| `awk '/^## /{inx=($0 ~ /Expand/)} inx && /^### /{n++} END{print n+0}' LESSONS.md` | `1` |
| `python -c "import sqlite3;print(sqlite3.sqlite_version)"` | `3.51.1` |
| `which -a ec` | `/Users/teslamint/.local/bin/ec` (exactly one install) |
| `ec dashboard` | maturity `71/100`, capture 17, distill 17, retrieve 25, intervene 12; applied-context 1%; lesson reuse 20% |
| `ec checkpoint assess-accuracy` | 24 enriched with feedback, agreement 95.8% |

The floor allocation and selection were also executed standalone against synthetic corpora during
planning, and every scenario assertion in U1 is transcribed from that observed output rather than
predicted. Two independent reviewers reproduced the same four traces.

## File structure

| File | Change | Unit |
|---|---|---|
| `src/entirecontext/core/futures.py` | add `DEFAULT_LESSONS_MIN_PER_VERDICT` and `_allocate_verdict_floors`; rewrite `get_lessons` selection | U1 |
| `tests/test_futures.py` | six core selection tests | U1, U2 |
| `src/entirecontext/core/config.py` | add `lessons_min_per_verdict` to the `futures` defaults | U2 |
| `src/entirecontext/core/futures.py` | thread the config value through `auto_distill_lessons` | U2 |
| `src/entirecontext/cli/futures_cmds.py` | `futures lessons` loads config and passes the floor | U2 |
| `src/entirecontext/mcp/tools/futures.py` | `ec_lessons` loads config and passes the floor | U2 |
| `tests/test_futures_cmds_assess.py` | CLI propagation test | U2 |
| `README.md` | document the new `[futures]` key | U3 |
| `docs/spec.md` | document the new `[futures]` key | U3 |
| `ROADMAP.md` | close the row and correct its `narrow` wording | U3 |
| `LESSONS.md` | regenerated output of the fixed selection | U4 |

No file is created. `core/futures.py` appears twice because U1 owns the selector and U2 owns the
configuration threading — the two are separately reviewable and the split is deliberate.

## Carry-forward trigger audit

Tracker examined: `ROADMAP.md` in this worktree — `HEAD` at `74212bb` plus this cycle's
newly registered row 407, uncommitted. Measured: `grep -c '^- \[ \]' ROADMAP.md` → 23, plus one
`- [~]` row at line 209, giving 24 open rows. Enumerated line numbers: 204, 209, 231, 265, 300,
301, 336, 338, 353, 354, 355, 358, 359, 360, 362, 363, 379, 382, 384, 395, 407, 411, 413, 418.

Classification — edit-based: 209, 338, 353, 354, 360, 363, 384, 407, 413, 418. Drift-based: 204,
231, 265, 300, 301, 336, 355, 382, 395. Event-based: 358, 359, 362, 379, 411.

Row 363 (`py.typed`) is edit-based, not event-based: its trigger names a file condition — the
absent marker — alongside the instruction to decide, and the mandated tiebreak resolves
file-plus-event to edit-based. Row 355 (spec directory drift) is drift-based, not event-based: it
names an observable divergence between `AGENTS.md`'s declared spec path and where specs are
actually written, which is checkable without any new event.

**Fired rows and their dispositions:**

| Row | Class | Why it fired | Disposition |
|---|---|---|---|
| 407 `get_lessons` flat recency window | edit-based | Names `core/futures.py:142-148`, this plan's primary edit | **Folded in** — U1 implements it, U3 closes the row |
| 362 Pre-execute plan verification commands | event-based | This plan declares verification commands | **Applied in this pass** — every command in Assumption Recheck was executed at planning time with its observed output recorded; no unit acceptance rests on an unrun check. The `xargs` defect in an earlier draft of U4 was found precisely because a reviewer executed it |
| 358 Re-query review threads before merge | event-based | This work will reach Ship | **Deferred** — governs `shipping`, not any planning unit |
| 204 Maturity ≥75 / distill | drift-based | Row records `distill=25`; `ec dashboard` observes `distill 17` | **Deferred** — recorded value is stale; refreshing embedded tracker measurements is a separate change |
| 231 Rule-based verdict mapping tuning | drift-based | Row records `latest check 2026-07-23: n=0`; `ec checkpoint assess-accuracy` observes 24 enriched with feedback | **Deferred** — n=24 approaches the row's own n≥30 gate but does not meet it; no code change is warranted yet |
| 300 `applied_context_rate` ≥ 10% | drift-based | Row records `current 8% (5/66)`; `ec dashboard` observes 1% | **Deferred** — the recorded value moved backwards, which is a measurement question, not this plan's scope |
| 301 `lesson_reuse_rate` progress | drift-based | Row records `current 2% (1/40)`; `ec dashboard` observes 20% | **Deferred** — the row's target is "steady upward trend"; one observation is not a trend, and closing it is a measurement judgment outside this plan's confirmed scope. Recorded so the next retro re-evaluates rather than rediscovers |
| 355 Spec directory drift | drift-based | `docs/specs/` holds five specs while `AGENTS.md` names `docs/superpowers/specs/`; the divergence is observable now | **Deferred** — relocating specs while `AGENTS.md` stays put converts an observable drift into a silent inconsistency. Same reasoning the 2026-08-12 plan recorded; the row stays open |
| 382 v0.15.0 carry-forward telemetry | drift-based | Row records `lesson_reuse_rate=5%`, `maturity 64`; observed 20% and 71 | **Deferred** — same stale-measurement class as 204/300/301 |

Nine fired rows. Six of them (204, 231, 300, 301, 355, 382) fired because a value embedded in the
row text has drifted from what the tooling now reports, not because this plan touches them. They
share one Deferred entry so the pattern is visible rather than scattered.

**Not fired, with reasons:**

- Edit-based against files absent from this plan's File structure: 209 and 413 and 418
  (`core/decisions.py` embedding, team-scoped visibility, `decision_files` rename tracking), 338
  and 384 (`core/archaeology.py` path escapes), 353 and 354 (`cli/project_cmds.py` hook install
  and `disable` asymmetry), 360 (`ec doctor` plus build config), 363 (`py.typed` marker).
- Event-based on occurrences this cycle does not produce: 359 plan-vs-spec test enumeration (fires
  only for a plan written from a spec; this plan has no origin spec), 379 post-squash archaeology
  (requires repository-content export authorization), 411 product messaging.
- Drift-based with no recorded value to deviate from: 265 and 336 state the maturity 75 target and
  the instruction to remeasure without recording a figure; 395 names the alpha badge and
  classifier, both still alpha.

Row 360 deserves one clause beyond its classification. Its trigger names files (`ec doctor`, build
config) that this plan does not touch, so the tiebreak keeps it edit-based and not fired. But U4
will directly observe the drift class the row exists to automate — step 2 expects a
`min_per_verdict` count of 0 in the installed package. The Deferred entry records that linkage so
the classification survives a strict drift-based reading.

Row 301 is worth one further note: this plan changes *which* lessons `LESSONS.md` shows, but
`lesson_reuse_rate` is driven by `rank_lessons_for_prompt` (`core/lesson_surfacing.py:97`), which
calls `get_surfaceable_lessons`, not `get_lessons`. No unit claims to move that rate.

**Unobservable rows:** none.

Audited `ROADMAP.md` in this worktree: 24 open rows (23 `- [ ]` plus 1 `- [~]`), 9 fired,
0 unobservable.

## Scenario coverage map

No origin spec, therefore no User Scenarios section to trace. The scenarios below were derived
during planning from the observable behaviours of the three call sites.

| S-ID | Scenario | Unit chain | Scenario evidence |
|---|---|---|---|
| S1 | A repo whose corpus skews neutral still gets `expand` lessons in `LESSONS.md` | U1 → U4 | `test_get_lessons_reserves_floor_for_minority_verdict`; U4 step 6's verdict census |
| S2 | A caller asking for N rows never receives more than N | U1 | `test_get_lessons_never_exceeds_limit` |
| S3 | A verdict with zero rows forfeits its floor rather than shrinking the result | U1 | `test_get_lessons_absent_verdict_forfeits_floor` |
| S4 | Non-reserved slots go to the globally newest rows, in deterministic order | U1 | `test_get_lessons_fills_remaining_slots_by_global_recency` |
| S5 | A small limit stays recency-ordered instead of becoming a per-verdict sampler | U1 | `test_get_lessons_small_limit_caps_floor_budget` |
| S6 | Operators can tune or disable the floor without editing code, on every entry point | U2 → U3 | `test_get_lessons_min_per_verdict_zero_is_pure_recency`; `test_futures_lessons_passes_config_floor`; the documented key in README and `docs/spec.md` |
| S7 | Hook-driven regeneration produces the fixed selection, not the stale install's | U4 | U4 step 3's grep of the installed package plus the regenerated `LESSONS.md` census |

Every S-ID completes end to end. No scenario is stranded mid-chain.

## Mutation/failure-state matrix

The deliverable includes one durable transition: U4 replaces the machine-global `ec` install so
that hook-driven `auto_distill` stops regenerating `LESSONS.md` from stale code. The replacement
persists across invocations, is observable outside this repository, and overwrites the prior
install irrecoverably — the failure mode
`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md` records under
"Capture the broken state before repairing it". Deviating from any row below is observable
behaviour and requires a committed addendum under `docs/deviations/` per
`docs/solutions/workflow-issues/review-introduced-state-machine-deviation.md`.

**Transition T1 — global `ec` install replaced from the checkout**

| Field | Value |
|---|---|
| Identity | every uv tool install of `entirecontext` reachable from `which -a ec` (observed: exactly one, `/Users/teslamint/.local/bin/ec`) |
| Pre-state | Installed package whose `core/futures.py` lacks the quota selection, captured as a path list, a per-file hash, and a `grep -c` count |
| Action | `uv tool install --force .` from the checkout root |
| Expected post-state | Installed `core/futures.py` contains `min_per_verdict`, verified by grep inside each installed package directory |
| Owning unit | U4 |
| Evidence owner | U4 writes to `.release-loop/evidence/U4/install-provenance.txt` and echoes the pre-state lines into the U4 commit message |
| Executes more than once | Yes, legitimately. The cited pattern prescribes reinstalling after merge; the Ship-phase obligation in Deferred to Follow-Up Work re-runs this transition if the branch was amended during review |

| Outcome class | Behaviour and evidence |
|---|---|
| Success | Grep of each installed `core/futures.py` finds `min_per_verdict` at a count of at least 8. The resolved paths, per-file hashes, and before-count are captured **before** the reinstall runs, and the same lines are echoed into the U4 commit message so the record survives `git clean -fdx` of the gitignored evidence directory |
| Forced failure | Injection boundary is the build input, never the installed tool: copy the checkout to a scratch directory, corrupt its `pyproject.toml` `version` line, and run `uv tool install --force .` there with **both** `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` pointed at throwaway paths. Both are required — `UV_TOOL_DIR` isolates the environment but the shim is written to `UV_TOOL_BIN_DIR`, which defaults to `~/.local/bin` where the real `ec` lives, so isolating only the former could overwrite the real shim to point into a directory that is then deleted. Confirm the command exits non-zero and that the real shim's hash is unchanged before and after |
| Rerun | Idempotent: a second `uv tool install --force .` from the same checkout yields the same installed content. Evidence is the grep repeated after the second run, appended as a distinct `_rerun` key |
| Rollback or compensation | No in-place rollback — the overwrite is irreversible. Compensation is forward-only: reinstall from the desired revision. The pre-state hash and archive make the loss diagnosable rather than merely bounded, which is the gap the cited incident could not close ("How long the install had been stale before the fix is unrecoverable") |
| Headless | The reinstall needs no TTY. When `which -a ec` resolves nothing, U4 **step 2** records `installed_state: no global install resolved` and skips the transition; it does not create an install the user never had, because that is a new side effect rather than a repair. Steps 5-7 still run from the checkout via `uv run`, and U4's acceptance accepts this line in place of the after-count |
| Cancellation or abort | Interrupting `uv tool install` can leave a partially written install. Detection is the same grep as Success, which fails closed on a count below 8; recovery is a rerun, established as idempotent above. The evidence file records the interruption so a partial install is never mistaken for a stale one |

## U1: verdict-floor selection inside the total cap

Depends on: nothing.
Produces: `DEFAULT_LESSONS_MIN_PER_VERDICT`, `_allocate_verdict_floors`, the rewritten
`get_lessons`, and six core selection tests.
Consumes: the existing `assessments` table and `VALID_VERDICTS` (`core/futures.py:12`).

This unit owns the selector contract only. The config key and its threading through production
call sites belong to U2, so a reviewer can accept the algorithm while rejecting the
operator-tunable surface.

Steps:

1. In `src/entirecontext/core/futures.py`, immediately below the
   `VALID_RELATIONSHIP_TYPES = ("causes", "fixes", "contradicts")` line (line 14), add:

   ```python
   DEFAULT_LESSONS_MIN_PER_VERDICT = 5
   ```

2. In the same file, add this helper immediately above `get_lessons` (currently line 142):

   ```python
   def _allocate_verdict_floors(limit: int, min_per_verdict: int) -> dict[str, int]:
       """Reserve slots per verdict without letting floors dominate the budget.

       Slots are handed out one verdict at a time in VALID_VERDICTS order, and
       the total is capped at half the limit so recency keeps the majority of
       the result. min_per_verdict <= 0 disables floors entirely.
       """
       floors = {verdict: 0 for verdict in VALID_VERDICTS}
       if limit <= 0 or min_per_verdict <= 0:
           return floors
       remaining = min(limit // 2, min_per_verdict * len(VALID_VERDICTS))
       for _ in range(min_per_verdict):
           for verdict in VALID_VERDICTS:
               if remaining == 0:
                   return floors
               floors[verdict] += 1
               remaining -= 1
       return floors
   ```

3. Replace the body of `get_lessons` (lines 142-148) with the quota selection. The signature gains
   a keyword-only `min_per_verdict`; `limit` keeps its meaning as a total cap:

   ```python
   def get_lessons(
       conn,
       limit: int = 50,
       *,
       min_per_verdict: int = DEFAULT_LESSONS_MIN_PER_VERDICT,
   ) -> list[dict]:
       """Get assessments that have feedback — these are lessons learned.

       Selection reserves a bounded per-verdict floor before filling the rest
       by recency, so a run of one verdict cannot evict every lesson of
       another. limit remains a total cap on the rows returned.
       """
       if limit <= 0:
           return []

       floors = _allocate_verdict_floors(limit, min_per_verdict)
       reserved: list[dict] = []
       overflow: list[dict] = []

       for verdict in VALID_VERDICTS:
           rows = conn.execute(
               """SELECT * FROM assessments
               WHERE feedback IS NOT NULL AND verdict = ?
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
               (verdict, limit),
           ).fetchall()
           candidates = [dict(r) for r in rows]
           floor = floors[verdict]
           reserved.extend(candidates[:floor])
           overflow.extend(candidates[floor:])

       def _recency_key(item: dict) -> tuple[str, str]:
           return (item.get("created_at") or "", item.get("id") or "")

       overflow.sort(key=_recency_key, reverse=True)
       selected = reserved + overflow[: max(0, limit - len(reserved))]
       selected.sort(key=_recency_key, reverse=True)
       return selected
   ```

   Four notes on why this shape:
   - The per-verdict `LIMIT ?` uses `limit`, not `floor`, so the overflow pool is large enough to
     fill the remaining slots when one verdict dominates. Total rows read stay bounded at
     `len(VALID_VERDICTS) * limit`.
   - `reserved` can be shorter than the sum of the floors when a verdict has fewer rows than its
     floor — that verdict forfeits the difference and the fill pass reclaims those slots, so the
     result still reaches `limit` whenever the corpus can supply it.
   - The `(created_at, id)` tie-break makes ordering deterministic for rows sharing a timestamp.
     The `or ""` fallbacks keep a NULL `created_at` sortable; `created_at` has a default but is not
     `NOT NULL` in the observed schema.
   - `overflow.sort` is what makes the fill *global* rather than per-verdict. Step 4's
     `test_get_lessons_fills_remaining_slots_by_global_recency` exists specifically because the
     other tests would still pass if this sort were removed.

4. In `tests/test_futures.py`, add a seed helper and six tests below the existing
   `test_distill_lessons_headings_are_unique_per_assessment` (ends line 159). All use the existing
   `ec_db` fixture, as `test_add_feedback` (lines 53-64) already does. Each seeds rows with
   explicit `created_at` values so recency order is deterministic rather than dependent on
   insertion timing — `create_assessment` stamps `created_at` itself, so these tests write the
   column directly. The observed schema has only `verdict` as `NOT NULL` beyond the primary key,
   so a five-column insert is valid.

   ```python
   def _seed_lesson(conn, verdict: str, created_at: str, feedback: str = "agree") -> str:
       from uuid import uuid4

       lesson_id = str(uuid4())
       conn.execute(
           """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
           VALUES (?, ?, ?, ?, ?)""",
           (lesson_id, verdict, f"{verdict} at {created_at}", feedback, created_at),
       )
       return lesson_id


   def test_get_lessons_reserves_floor_for_minority_verdict(ec_db):
       """A neutral flood must not evict every expand lesson (S1)."""
       for i in range(60):
           _seed_lesson(ec_db, "neutral", f"2026-08-14T{i // 60:02d}:{i % 60:02d}:00+00:00")
       for i in range(8):
           _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=50, min_per_verdict=5)

       assert len(lessons) == 50
       assert len([item for item in lessons if item["verdict"] == "expand"]) >= 5


   def test_get_lessons_never_exceeds_limit(ec_db):
       """limit stays a total cap across all verdicts (S2)."""
       for verdict in ("expand", "narrow", "neutral"):
           for i in range(10):
               _seed_lesson(ec_db, verdict, f"2026-08-1{i}T00:00:00+00:00")

       assert len(get_lessons(ec_db, limit=9, min_per_verdict=5)) == 9
       assert get_lessons(ec_db, limit=0, min_per_verdict=5) == []


   def test_get_lessons_absent_verdict_forfeits_floor(ec_db):
       """A verdict with no rows must not shrink the result (S3)."""
       for i in range(12):
           _seed_lesson(ec_db, "neutral", f"2026-08-10T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=10, min_per_verdict=5)

       assert len(lessons) == 10
       assert {item["verdict"] for item in lessons} == {"neutral"}


   def test_get_lessons_fills_remaining_slots_by_global_recency(ec_db):
       """Non-reserved slots take the globally newest rows, in deterministic order (S4).

       Guards the overflow.sort that makes the fill global rather than
       per-verdict — every other test here passes without it.
       """
       for i in range(6):
           _seed_lesson(ec_db, "expand", f"2026-08-02T00:{i:02d}:00+00:00")
       for i in range(6):
           _seed_lesson(ec_db, "neutral", f"2026-08-03T00:{i:02d}:00+00:00")
       for i in range(6):
           _seed_lesson(ec_db, "narrow", f"2026-08-04T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=12, min_per_verdict=1)

       assert len(lessons) == 12
       stamps = [item["created_at"] for item in lessons]
       assert stamps == sorted(stamps, reverse=True)
       # narrow is newest, so after the 1-per-verdict floors the fill is
       # narrow-then-neutral; no expand row beyond its floor can appear.
       assert len([item for item in lessons if item["verdict"] == "expand"]) == 1


   def test_get_lessons_small_limit_caps_floor_budget(ec_db):
       """A small limit stays recency-ordered, not a per-verdict sampler (S5)."""
       for i in range(4):
           _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")
       for i in range(4):
           _seed_lesson(ec_db, "neutral", f"2026-08-09T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=3, min_per_verdict=5)

       assert len(lessons) == 3
       # floor budget is limit // 2 == 1, so at most one slot is reserved and
       # the newest rows (neutral) take the rest.
       assert len([item for item in lessons if item["verdict"] == "neutral"]) >= 2


   def test_get_lessons_min_per_verdict_zero_is_pure_recency(ec_db):
       """min_per_verdict=0 restores the pre-fix ordering exactly (S6)."""
       for i in range(4):
           _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")
       for i in range(4):
           _seed_lesson(ec_db, "neutral", f"2026-08-09T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=4, min_per_verdict=0)

       assert [item["verdict"] for item in lessons] == ["neutral"] * 4
   ```

5. Run `uv run pytest tests/test_futures.py -q`. The module held 14 passing tests at baseline, so
   expect 20. `test_add_feedback` (lines 53-64) calls `get_lessons(ec_db)` and asserts a single
   seeded lesson comes back; it must still pass unchanged, and it is the guard that the new
   selection did not break the trivial case.

Acceptance: `uv run pytest tests/test_futures.py -q` reports 20 passed;
`uv run mypy src/entirecontext/` reports `Success: no issues found in 120 source files`;
`uv run ruff check src/entirecontext/core/futures.py tests/test_futures.py` exits 0; and
`rg -c "min_per_verdict" src/entirecontext/core/futures.py` returns at least 7 — the helper
signature, its docstring, its two guards, its loop, the `get_lessons` parameter, and the helper
call. Note `rg -c` counts matching lines, and lowercase `min_per_verdict` does not match the
uppercase constant `DEFAULT_LESSONS_MIN_PER_VERDICT`. U2 raises this count to 9 by adding the
`auto_distill_lessons` keyword argument and the config-key string, which is why U4's install
verification asserts at least 8.

## U2: the config key and all three production call sites

Depends on: U1.
Produces: the `futures.lessons_min_per_verdict` default and all three call sites honouring it, plus
a CLI propagation test.
Consumes: U1's `get_lessons` signature and `DEFAULT_LESSONS_MIN_PER_VERDICT`.

This unit owns the complete configuration contract. Splitting it — configuring auto-distill while
the CLI and MCP paths ignore the same key — would leave neither unit a coherent acceptance
boundary.

Steps:

1. In `src/entirecontext/core/config.py`, add one line to the `futures` block (lines 68-75), after
   `"lessons_output": "LESSONS.md",`:

   ```python
   "lessons_min_per_verdict": 5,
   ```

   Keep the literal `5` rather than importing `DEFAULT_LESSONS_MIN_PER_VERDICT`: every other value
   in this defaults table is a literal, and importing `core.futures` into `core.config` would
   invert the existing dependency direction — `core/futures.py:195` imports `load_config` from
   `.config`.

2. In `auto_distill_lessons` (`core/futures.py:193-212`), which already holds a loaded `config`,
   change the `get_lessons(conn)` call at line 204 to:

   ```python
   lessons = get_lessons(
       conn,
       min_per_verdict=config.get("futures", {}).get(
           "lessons_min_per_verdict", DEFAULT_LESSONS_MIN_PER_VERDICT
       ),
   )
   ```

3. In `src/entirecontext/cli/futures_cmds.py`, the `futures_lessons` command (lines 231-259) does
   not currently load config at all. Change the import at line 239 to:

   ```python
   from ..core.futures import DEFAULT_LESSONS_MIN_PER_VERDICT, distill_lessons, get_lessons
   ```

   After `repo_path = find_git_root()` succeeds and before `conn = get_db(repo_path)`, add:

   ```python
   from ..core.config import load_config

   floor = (
       load_config(repo_path)
       .get("futures", {})
       .get("lessons_min_per_verdict", DEFAULT_LESSONS_MIN_PER_VERDICT)
   )
   ```

   then change line 250 to `lessons = get_lessons(conn, min_per_verdict=floor)`.

   Leave the `--output` default and the `--since` post-filter exactly as they are. This command
   ignoring `futures.lessons_output` is pre-existing behaviour and out of scope — U4's regeneration
   passes `--output` explicitly rather than relying on it.

4. In `src/entirecontext/mcp/tools/futures.py`, `ec_lessons` (lines 160-171) already receives the
   repo from `runtime.open_repo()` but discards it as `_`. Bind it and use it:

   ```python
   async def ec_lessons(limit: int = 50) -> str:
       try:
           conn, repo_path = runtime.open_repo()
       except runtime.RepoResolutionError as exc:
           return runtime.error_payload(str(exc))
       try:
           from ...core.config import load_config
           from ...core.futures import DEFAULT_LESSONS_MIN_PER_VERDICT, get_lessons

           floor = (
               load_config(repo_path)
               .get("futures", {})
               .get("lessons_min_per_verdict", DEFAULT_LESSONS_MIN_PER_VERDICT)
           )
           lessons = get_lessons(conn, limit=limit, min_per_verdict=floor)
           return json.dumps({"lessons": lessons, "count": len(lessons)})
       finally:
           conn.close()
   ```

   Confirm what `open_repo` returns before editing: run
   `rg -n "def open_repo" -A 12 src/entirecontext/mcp/runtime.py` and check the second tuple
   element is the repository path. If it is not a path, keep `_` and call `find_git_root()` from
   `...core.project` instead — do not pass a non-path into `load_config`.

5. Add one CLI test to `tests/test_futures_cmds_assess.py`, which already exercises this command
   group and already patches config at line 136. Read that file's first 40 lines and reuse its
   existing `app` import and runner construction rather than introducing a second convention;
   the body below assumes a module-level `runner`:

   ```python
   def test_futures_lessons_passes_config_floor(ec_repo, monkeypatch, tmp_path):
       """The configured floor reaches get_lessons rather than the default (S6)."""
       seen = {}

       def fake_get_lessons(conn, limit=50, *, min_per_verdict=5):
           seen["min_per_verdict"] = min_per_verdict
           return []

       monkeypatch.chdir(ec_repo)
       monkeypatch.setattr("entirecontext.core.futures.get_lessons", fake_get_lessons)
       monkeypatch.setattr(
           "entirecontext.core.config.load_config",
           lambda *a, **k: {"futures": {"lessons_min_per_verdict": 3}},
       )

       result = runner.invoke(
           app, ["futures", "lessons", "--output", str(tmp_path / "OUT.md")]
       )

       assert result.exit_code == 0
       assert seen["min_per_verdict"] == 3
   ```

   The `monkeypatch.setattr` target is the module attribute because the command performs its
   import inside the function body at call time. The assertion is what proves it, so do not
   substitute a different target without re-running the test.

6. Run `uv run pytest tests/test_futures.py tests/test_futures_cmds_assess.py tests/test_mcp.py -q`.

Acceptance: the pytest invocation in step 6 is green with one more test in
`tests/test_futures_cmds_assess.py` than baseline; `uv run mypy src/entirecontext/` reports Success
on 120 files; `uv run ruff check src/entirecontext/` exits 0; and
`rg -l "lessons_min_per_verdict" src/entirecontext/ | wc -l` returns 4 — the config default,
`auto_distill_lessons`, and the two call sites.

## U3: document the key and close the ROADMAP row

Depends on: U2.
Produces: the documented config key, the closed ROADMAP row, and the corrected `narrow` wording.
Consumes: the shipped config key name.

Runs independently of U4; neither consumes the other's output.

Steps:

1. In `README.md`, the `[futures]` config block shows `auto_distill = false` at line 619 and
   `lessons_output = "LESSONS.md"` at line 620. Read lines 610-630 first to match the block's
   comment style, then add below line 620:

   ```toml
   lessons_min_per_verdict = 5
   ```

   with a one-line explanation in the surrounding prose style: the slots reserved per verdict
   inside the total lesson cap, so a run of one verdict cannot evict every lesson of another;
   the reservation never exceeds half the cap, and `0` restores pure recency ordering.

2. In `docs/spec.md`, make the same addition below line 385 (`lessons_output = "LESSONS.md"`), and
   extend the sentence at line 282 that enumerates `[futures]` keys — it currently names
   `auto_distill`, `assess_enrich`, and `assess_backfill_window_days` — so it also names
   `lessons_min_per_verdict`. Read lines 275-290 and 378-392 before editing to match the
   surrounding form.

3. In `ROADMAP.md`, the row at line 407 is the `get_lessons` flat-recency-window item added this
   cycle. Two edits to it:
   - Change `- [ ]` to `- [x]`.
   - Correct the `narrow` claim. The row currently reads the collapse as `Expand 1 ... Narrow 0,
     Neutral 49`, which implies `narrow` lessons were evicted. Measured: the corpus holds zero
     `narrow` rows, so no selection change can produce a Narrow section. Replace that clause with
     `Expand 1 of 22 surviving, Neutral 49; narrow is absent from the corpus entirely (0 rows), so
     its missing section is corpus truth rather than eviction`, and append the closure sentence:
     `Fixed by a per-verdict floor capped at half the total cap; config key
     futures.lessons_min_per_verdict (default 5).`

   Leave every other row untouched. In particular, do not refresh the stale measurements in rows
   204, 231, 300, 301, and 382 — they are registered as Deferred, and rewriting them here would
   expand this plan into tracker maintenance.

4. Verify the row reads as intended: `rg -n "^- \[x\].*get_lessons" ROADMAP.md` must match exactly
   one line, and `grep -c "^- \[ \]" ROADMAP.md` must return 22 — one fewer than the 23 open
   `- [ ]` rows measured during this plan's trigger audit.

Acceptance: step 4's two commands return the stated values;
`rg -c "lessons_min_per_verdict" README.md docs/spec.md` returns 1 for each file; and
`rg -n "narrow" ROADMAP.md | rg -c "corpus"` returns at least 1, confirming the corrected wording
landed.

## U4: regenerate LESSONS.md against a verified install

Depends on: U1, U2.
Produces: the regenerated `LESSONS.md`, and the install-provenance evidence required by
transition T1.
Consumes: the shipped selection code and config threading. Consumes nothing from U3.

This unit carries the Known Pattern obligation. Skipping it does not merely leave `LESSONS.md`
stale — the next hook-driven `auto_distill` regenerates it from the stale global install and
reverts the fix, exactly as recorded for this function in
`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md`. The same document
prescribes reinstalling *after* merge; this unit performs the pre-merge repair because the working
tree is already being clobbered today, and the post-merge re-verification is registered as a
Ship-phase obligation in Deferred to Follow-Up Work.

Steps:

1. Create the evidence directory and record the pre-repair state **before** touching any install.
   Every variable is assigned in this step:

   ```sh
   mkdir -p .release-loop/evidence/U4
   EVIDENCE="$PWD/.release-loop/evidence/U4/install-provenance.txt"
   {
     echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
     echo "checkout_head: $(git rev-parse HEAD)"
     echo "resolved_ec: $(which -a ec | tr '\n' ' ')"
   } > "$EVIDENCE"
   ```

   Use `which -a`, not `command -v`: the cited pattern's domain is multiple coexisting installs,
   and `command -v` reports only the first PATH hit. On this machine `which -a ec` resolves exactly
   one path, `/Users/teslamint/.local/bin/ec`, so the loop below runs once — but it must be a loop
   so a second install is recorded rather than hidden.

2. If `which -a ec` produced nothing, append `installed_state: no global install resolved` to
   `$EVIDENCE` and skip to step 5 — the headless row of transition T1. Otherwise, for each
   resolved shim, record the interpreter, the package directory, a per-file hash of the package's
   `core/` modules, and the before-count:

   ```sh
   for shim in $(which -a ec); do
     EC_PY=$(head -1 "$shim" | sed 's/^#!//')
     PKG_DIR=$("$EC_PY" -c 'import entirecontext, os; print(os.path.dirname(entirecontext.__file__))')
     {
       echo "shim: $shim"
       echo "installed_python: $EC_PY"
       echo "installed_pkg_dir: $PKG_DIR"
       echo "min_per_verdict_before: $(grep -c min_per_verdict "$PKG_DIR/core/futures.py" || true)"
       shasum "$PKG_DIR"/core/*.py | sed 's/^/  hash_before: /'
     } >> "$EVIDENCE"
     tar czf ".release-loop/evidence/U4/pre-install-$(basename "$(dirname "$shim")").tgz" "$PKG_DIR" 2>/dev/null || \
       echo "  archive: skipped (package too large or unreadable)" >> "$EVIDENCE"
   done
   ```

   A before-count of `0` is the expected pre-state and confirms the drift this unit repairs. The
   hash and archive exist because the Rollback row declares the overwrite irreversible — without
   them, the record proves only that the fix was absent, not what was destroyed, which is the
   exact information the cited incident could not recover. Do not use `ec --version` as the drift
   check: the pattern records that both copies report the same version string.

3. Reinstall from the checkout, then verify the reinstall actually took. Do not use a
   `xargs -I{} {}` pipeline to resolve the package path — the replacement token cannot be the
   utility name, and it was observed failing with `xargs: {}: No such file or directory`, exit 127,
   leaving the path empty and the subsequent grep silently blank. Reuse the step-2 form:

   ```sh
   uv tool install --force .
   for shim in $(which -a ec); do
     EC_PY=$(head -1 "$shim" | sed 's/^#!//')
     PKG_DIR=$("$EC_PY" -c 'import entirecontext, os; print(os.path.dirname(entirecontext.__file__))')
     test -f "$PKG_DIR/core/futures.py" || { echo "MISSING $PKG_DIR/core/futures.py"; exit 1; }
     AFTER=$(grep -c min_per_verdict "$PKG_DIR/core/futures.py")
     echo "min_per_verdict_after: $AFTER ($PKG_DIR)" >> "$EVIDENCE"
     test "$AFTER" -ge 8 || { echo "REINSTALL DID NOT TAKE: $AFTER"; exit 1; }
   done
   ```

   The explicit `test -f` and `test -ge 8` are what make this fail closed. A blank or zero count
   means the fix is inert in the environment whose output lands back in this repository — stop and
   resolve it before proceeding, because the global mutation has already happened.

4. Re-run the same verification once more to establish the Rerun row of transition T1:
   `uv tool install --force .` again, repeat step 3's loop, and append the count as
   `min_per_verdict_after_rerun:`. The two counts must match.

5. Regenerate the artifact from the checkout, not the install, so the committed file is the
   reviewed code's output:

   ```sh
   uv run ec futures lessons --output LESSONS.md
   ```

6. Record the resulting verdict census and confirm S1 held against real data:

   ```sh
   uv run python -c "
   from collections import Counter
   from entirecontext.db import get_db
   from entirecontext.core.futures import get_lessons
   c = get_db('.')
   try:
       L = get_lessons(c)
       print('returned', len(L))
       print('by_verdict', dict(Counter(x['verdict'] for x in L)))
   finally:
       c.close()
   " | tee -a "$EVIDENCE"
   ```

   Expect `returned 50` and an `expand` count of at least 5, against the planning-time baseline of
   `{'expand': 1, 'neutral': 49}`. A `narrow` key will still be absent — the corpus has no `narrow`
   rows, and U3 step 3 records that as corpus truth.

7. Confirm the regenerated file's shape with two executable counts. The Expand-section count is the
   one that matters, and it was `1` before this change:

   ```sh
   test "$(grep -c '^### ' LESSONS.md)" -eq 50 || { echo "unexpected total entry count"; exit 1; }
   EXPAND=$(awk '/^## /{inx = ($0 ~ /Expand/)} inx && /^### /{n++} END{print n+0}' LESSONS.md)
   echo "expand_section_entries: $EXPAND" >> "$EVIDENCE"
   test "$EXPAND" -ge 5 || { echo "Expand section still collapsed: $EXPAND"; exit 1; }
   ```

8. Echo the pre-state lines into the U4 commit message body so the record outlives the gitignored
   evidence directory (`.release-loop` is gitignored, so `git clean -fdx` or a worktree removal
   would otherwise destroy the only trace of an irreversible mutation):

   ```sh
   grep -E '^(checkout_head|resolved_ec|shim|min_per_verdict_before|min_per_verdict_after):' "$EVIDENCE"
   ```

   Paste that output into the commit body when committing `LESSONS.md`.

Acceptance: `.release-loop/evidence/U4/install-provenance.txt` exists and contains a
`min_per_verdict_after` count of at least 8 for every resolved shim (or the headless
`no global install resolved` line); step 6 reports an `expand` count of at least 5; step 7's two
`test` commands both exit 0; step 8's output appears in the U4 commit body; and
`uv run pytest tests/test_futures.py -q` is still green after the regeneration.

## Open unknowns

**Planning-time** — none. The one contract fork (whether `limit` stays a total cap or becomes
per-verdict) was resolved before authoring: `limit` stays a total cap, because it is exposed as the
`ec_lessons` MCP parameter and reinterpreting it would silently return up to three times what a
caller asked for. The follow-on question that fork exposed — that floors could still consume the
whole budget at small limits — was resolved by the `limit // 2` cap, measured during planning.

**Implementation-time**:
- Whether `runtime.open_repo()`'s second tuple element is a repository path. U2 step 4 names the
  command that answers it and the fallback to use if it is not.
- The exact runner construction in `tests/test_futures_cmds_assess.py`. U2 step 5 instructs the
  implementer to read the file's first 40 lines and reuse its convention.
- The surrounding prose form of the `[futures]` blocks in `README.md` and `docs/spec.md`. U3 steps
  1 and 2 name the line ranges to read first.
- The pre-repair `min_per_verdict` count in the installed package. Expected `0`, but recorded when
  observed rather than predicted — the install may already have been refreshed.
- Whether `tar` can archive the installed package within a reasonable size. U4 step 2 falls back to
  the hash alone and records the skip.

## Deferred to Follow-Up Work

- **Ship-phase install re-verification.** The cited Known Pattern prescribes reinstalling after
  merging anything the hooks execute, but this plan's units all end before merge. After the merge,
  re-run U4 step 3's loop against the installed package, and reinstall from merged `main` if review
  amended the selection code — same-version drift would otherwise be undetectable. Transition T1's
  matrix row already records that the action may legitimately execute twice, and the Rerun row
  establishes it as idempotent.
- **`get_surfaceable_lessons` carries the same flat-recency shape.**
  `src/entirecontext/core/lesson_surfacing.py:11-27` — `ORDER BY a.created_at DESC` at line 23,
  `LIMIT ?` at line 24 — called at line 110 with `limit=200`. Against today's 120-row corpus it
  evicts nothing, and it feeds a file-overlap re-rank rather than a capped document, so a
  document-shaped quota could displace file-relevant candidates. Revisit trigger: the
  feedback-bearing corpus passing 200 rows, measurable with
  `sqlite3 .entirecontext/db/local.db "SELECT COUNT(*) FROM assessments WHERE feedback IS NOT NULL"`.
- **`futures lessons` ignores `futures.lessons_output`.** The `--output` option defaults to the
  literal `LESSONS.md` rather than the configured value, unlike `auto_distill_lessons`.
  Pre-existing inconsistency, unrelated to verdict selection.
- **ROADMAP embedded-measurement drift**, covering the six fired drift rows this plan defers:
  `:204` records `distill=25` against an observed 17; `:231` records `n=0` against an observed 24;
  `:300` records `8% (5/66)` against an observed 1%; `:301` records `2% (1/40)` against an observed
  20%; `:382` records `lesson_reuse_rate=5%, maturity 64` against an observed 20% and 71; `:355`
  records a spec-directory divergence that is still observable. Each fired because a figure written
  into the row text no longer matches what `ec dashboard` and `ec checkpoint assess-accuracy`
  report — not because this plan touches them. Refreshing them is tracker maintenance with its own
  measurement question (which figure is authoritative when the row and the dashboard disagree), and
  folding six row rewrites into a code fix would violate this plan's confirmed scope. `:301` in
  particular now exceeds the 20% figure its own text names as the non-mandatory threshold, so the
  next retro should decide whether it closes.
- **`ROADMAP.md:360` build-SHA provenance stamp.** U4 repairs this instance of install drift
  operationally and step 2 directly observes it, but the row asks for `ec doctor` to detect it
  automatically. That is a different change to different files and stays open.
- **`ROADMAP.md:358` re-query review threads immediately before merge.** Fires at this work's Ship
  phase, not in any planning unit. Recorded so `shipping` inherits it.
