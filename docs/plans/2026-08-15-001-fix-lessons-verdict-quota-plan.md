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
floor inside the same total cap, so `expand` and `narrow` lessons cannot be pushed out by recency
alone. The `limit` contract stays a total cap: no caller ever receives more rows than it asked
for.

## Architecture notes

**The defect, measured.** `src/entirecontext/core/futures.py:142-148` is a single
`ORDER BY created_at DESC LIMIT ?` with no verdict partitioning. Measured in this worktree at
`74212bb` against `.entirecontext/db/local.db`:

| Query | Result |
|---|---|
| `get_lessons(conn)` returns | 50 rows — `expand` 1, `neutral` 49, `narrow` 0 |
| Corpus (`feedback IS NOT NULL`) holds | 120 rows — `neutral` 98, `expand` 22, `narrow` 0 |

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
character — while guaranteeing the option-shaping exemplars survive. With `limit=50` and a floor
of 5 against today's corpus, the result is `expand` ≥ 5 and the remaining 40+ slots filled by
recency.

**No window function.** `ROW_NUMBER() OVER (PARTITION BY ...)` would express this in one query,
but `rg "ROW_NUMBER\(\) OVER|OVER \(PARTITION" src/entirecontext/` returns nothing — this
repository has no window-function precedent, and every aggregation in `core/futures.py` and
`core/auto_assess.py` uses plain SQL plus Python post-processing. Three bounded per-verdict
queries match the established style and carry no SQLite-version assumption. `VALID_VERDICTS` has
three members, so this is three small queries, each `LIMIT ?`-bounded.

**Known Pattern — the fix will revert itself if only the checkout is changed.**
`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md` records this exact
function reverting a shipped fix: hooks invoke `ec` from a uv tool install, not from the checkout,
so hook-driven `auto_distill` regenerates `LESSONS.md` with the stale code. Both copies reported
`0.14.0`, so no version comparison detects it. That document also warns that the repair destroys
the measurement — the pre-repair install state must be recorded before reinstalling. U4 carries
both obligations.

**Sibling with the same shape, deliberately out of scope.**
`src/entirecontext/core/lesson_surfacing.py:11-17` (`get_surfaceable_lessons`) is a second
recency-ordered lessons query, called by `rank_lessons_for_prompt` at line 110 with `limit=200`.
Against a 120-row corpus it evicts nothing today, so it is not the reported defect. It acquires
the same bias once the corpus passes 200 rows. Deferred, with the trigger recorded.

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
inherited from an approved artifact. Baseline, recorded at planning time:

| Command | Observed |
|---|---|
| `uv run pytest tests/test_futures.py -q` | `14 passed in 1.94s` |
| `uv run mypy src/entirecontext/` | `Success: no issues found in 120 source files` |
| `uv run ruff check src/entirecontext/core/futures.py` | `All checks passed!` |
| `get_lessons(conn)` verdict census | `{'expand': 1, 'neutral': 49}`, 50 returned |
| `sqlite3 .entirecontext/db/local.db` verdict census | `neutral 98`, `expand 22`, total 120 |
| `uv run python -c "import sqlite3;print(sqlite3.sqlite_version)"` | `3.51.1` |

## File structure

| File | Change |
|---|---|
| `src/entirecontext/core/futures.py` | add `DEFAULT_LESSONS_MIN_PER_VERDICT`; rewrite `get_lessons` selection; add `_allocate_verdict_floors` helper |
| `src/entirecontext/core/config.py` | add `lessons_min_per_verdict` to the `futures` defaults block |
| `src/entirecontext/cli/futures_cmds.py` | `futures lessons` loads config and passes the floor |
| `src/entirecontext/mcp/tools/futures.py` | `ec_lessons` loads config and passes the floor |
| `tests/test_futures.py` | regression tests for floors, fill, clamping, and cap |
| `README.md` | document the new `[futures]` key |
| `docs/spec.md` | document the new `[futures]` key |
| `ROADMAP.md` | close the row and correct its `narrow` wording |
| `LESSONS.md` | regenerated output of the fixed selection |

No file is created. `auto_distill_lessons` (`core/futures.py:193-211`) already loads config, so it
gains the floor argument inside U1's file rather than needing its own row.

## Carry-forward trigger audit

Tracker examined: `ROADMAP.md` in this worktree — `HEAD` at `74212bb` plus this cycle's
newly registered row 407, which is uncommitted. Measured: 23 open `- [ ]` rows
(`grep -c '^- \[ \]' ROADMAP.md` → 23) plus one `- [~]` row at line 209.

**Fired rows and their dispositions:**

| Row | Trigger class | Why it fired | Disposition |
|---|---|---|---|
| `ROADMAP.md:407` `get_lessons` flat recency window | edit-based — names `core/futures.py:142-148` | That file and range are this plan's primary edit | **Folded in** — U1 implements it, U3 closes the row |
| `ROADMAP.md:362` Pre-execute plan verification commands at authoring time | event-based — fires whenever a plan declares verification commands | This plan declares them | **Applied in this pass** — every command in Assumption Recheck was executed at planning time and its observed output recorded; no unit acceptance rests on an unrun check |
| `ROADMAP.md:358` Re-query review threads immediately before merge | event-based — fires at a merge | This work will reach Ship | **Deferred to Follow-Up Work** — it governs `shipping`, not any planning unit. Recorded so Ship inherits it |

**Not fired, with reasons:**

- Edit-based against files absent from this plan: `:353`, `:354` (`cli/project_cmds.py`), `:338`
  and `:384` (`core/archaeology.py`), `:360` (`ec doctor` plus build config), `:411`, `:416`
  (`core/decisions.py`).
- Event-based on occurrences this cycle does not produce: `:355` spec directory drift (this plan
  has no origin spec and writes nothing under either specs directory), `:359` plan-vs-spec test
  enumeration (fires only for a plan written from a spec), `:363` `py.typed` (no typed-surface
  decision here), `:379` post-squash archaeology (requires export authorization), `:409` product
  messaging.
- Drift-based against metrics observable today and unchanged by this plan: `:204`, `:265`, `:336`,
  `:382` maturity — `ec dashboard` reads 71/100 with breakdown capture 17, distill 17, retrieve 25,
  intervene 12; `:300` `applied_context_rate`; `:301` `lesson_reuse_rate`; `:231` verdict mapping
  (`assess-accuracy` enriched-with-feedback count still under 30); `:395` alpha status.
- `- [~] :209` Signal C — edit-based against `core/decisions.py` embedding paths, absent here.

`:301` deserves an explicit note rather than a silent pass: this plan changes *which* lessons
`LESSONS.md` shows, but `lesson_reuse_rate` is driven by `rank_lessons_for_prompt`
(`core/lesson_surfacing.py:97`), which does not call `get_lessons`. The rate is therefore
unaffected, and no unit claims to move it.

**Unobservable rows:** none.

Audited `ROADMAP.md` in this worktree: 24 open rows (23 `- [ ]` plus 1 `- [~]`), 3 fired,
0 unobservable.

## Scenario coverage map

No origin spec, therefore no User Scenarios section to trace. The scenarios below were derived
during planning from the observable behaviours of the three call sites, and carry S-IDs so unit
steps can reference them.

| S-ID | Scenario | Unit chain | Scenario evidence |
|---|---|---|---|
| S1 | A repo whose corpus skews neutral still gets `expand` lessons in `LESSONS.md` | U1 → U4 | `test_get_lessons_reserves_floor_for_minority_verdict`; U4's post-regeneration verdict census |
| S2 | A caller asking for N rows never receives more than N | U1 | `test_get_lessons_never_exceeds_limit` |
| S3 | A verdict with zero rows forfeits its floor rather than shrinking the result | U1 | `test_get_lessons_absent_verdict_forfeits_floor` |
| S4 | A limit smaller than the combined floors still returns exactly `limit` rows | U1 | `test_get_lessons_clamps_floors_below_limit` |
| S5 | Operators can tune or disable the floor without editing code | U2 → U3 | `test_futures_lessons_passes_config_floor`; the documented key in README and `docs/spec.md` |
| S6 | Hook-driven regeneration produces the fixed selection, not the stale install's | U4 | U4 step 3's grep of the installed package plus the regenerated `LESSONS.md` census |

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
| Identity | uv tool install of `entirecontext` at the path resolved from `which -a ec` |
| Pre-state | Installed package whose `core/futures.py` lacks the quota selection |
| Action | `uv tool install --force .` from the checkout root |
| Expected post-state | Installed `core/futures.py` contains `min_per_verdict`, verified by grep inside the installed directory |
| Owning unit | U4 |
| Evidence owner | U4 writes to `.release-loop/evidence/U4/` |

| Outcome class | Behaviour and evidence |
|---|---|
| Success | Grep of the installed `core/futures.py` finds `min_per_verdict`; the pre-repair census, the resolved install path, and the post-repair grep are all captured to `.release-loop/evidence/U4/install-provenance.txt` **before** the reinstall runs |
| Forced failure | Injection boundary is the build input, not the installed tool: run `uv tool install --force .` from a scratch copy of the checkout whose `pyproject.toml` `version` line is corrupted, in a throwaway `UV_TOOL_DIR`, and confirm the command exits non-zero and the real install is untouched. Isolation is the separate `UV_TOOL_DIR`; the machine install is never the experiment subject |
| Rerun | Idempotent: a second `uv tool install --force .` from the same checkout yields the same installed content. Evidence is the grep repeated after the second run, appended to the same file |
| Rollback or compensation | No rollback — the overwrite is irreversible and the previous install's source revision is unrecoverable once replaced, which is why pre-state capture precedes the action. Compensation is forward-only: reinstall from the desired revision (`uv tool install --force .` at that checkout). The recorded pre-state is what makes the loss bounded rather than silent |
| Headless | The reinstall needs no TTY. In a headless run where no `ec` is on `PATH`, U4 step 3 records "no global install resolved" to the evidence file and skips the transition; it does not install one, because creating an install the user did not have is a new side effect rather than a repair |
| Cancellation or abort | Interrupting `uv tool install` can leave a partially written install. Detection is the same grep as Success, which fails closed; recovery is a rerun, which the Rerun row establishes as idempotent. The evidence file records the interruption so a partial install is never mistaken for a stale one |

## U1: verdict-floor selection inside the total cap

Depends on: nothing.
Produces: `DEFAULT_LESSONS_MIN_PER_VERDICT`, `_allocate_verdict_floors`, the rewritten
`get_lessons`, the `futures` config default, and the regression tests for all four selection
scenarios.
Consumes: the existing `assessments` table and `VALID_VERDICTS`.

Steps:

1. In `src/entirecontext/core/futures.py`, immediately below the
   `VALID_RELATIONSHIP_TYPES = ("causes", "fixes", "contradicts")` line (line 14), add:

   ```python
   DEFAULT_LESSONS_MIN_PER_VERDICT = 5
   ```

2. In the same file, add this helper immediately above `get_lessons` (currently line 142):

   ```python
   def _allocate_verdict_floors(limit: int, min_per_verdict: int) -> dict[str, int]:
       """Reserve up to min_per_verdict slots per verdict without exceeding limit.

       Slots are handed out one verdict at a time in VALID_VERDICTS order so a
       limit smaller than len(VALID_VERDICTS) * min_per_verdict degrades evenly
       instead of starving the last verdict.
       """
       floors = {verdict: 0 for verdict in VALID_VERDICTS}
       if limit <= 0 or min_per_verdict <= 0:
           return floors
       remaining = limit
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

       Selection reserves up to min_per_verdict slots per verdict before
       filling the rest by recency, so a run of one verdict cannot evict every
       lesson of another. limit remains a total cap on the rows returned.
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

   Three notes on why this shape:
   - The per-verdict `LIMIT ?` uses `limit`, not `floor`, so the overflow pool is large enough to
     fill the remaining slots when one verdict dominates. The total rows read stay bounded at
     `len(VALID_VERDICTS) * limit`.
   - `reserved` can be shorter than the sum of the floors when a verdict has fewer rows than its
     floor — that verdict forfeits the difference and the fill pass reclaims those slots, so the
     result still reaches `limit` whenever the corpus can supply it.
   - The `(created_at, id)` tie-break makes ordering deterministic for rows sharing a timestamp,
     which the tests in step 6 rely on.

4. In `src/entirecontext/core/config.py`, add one line to the `futures` block (lines 68-75), after
   `"lessons_output": "LESSONS.md",`:

   ```python
   "lessons_min_per_verdict": 5,
   ```

   Keep the literal `5` rather than importing `DEFAULT_LESSONS_MIN_PER_VERDICT`: every other value
   in this defaults table is a literal, and importing `core.futures` into `core.config` would
   invert the existing dependency direction — `core/futures.py:195` imports `load_config` from
   `.config`.

5. In `auto_distill_lessons` (`core/futures.py:193-211`), which already holds a loaded `config`,
   change the `get_lessons(conn)` call at line 204 to:

   ```python
   lessons = get_lessons(
       conn,
       min_per_verdict=config.get("futures", {}).get("lessons_min_per_verdict", DEFAULT_LESSONS_MIN_PER_VERDICT),
   )
   ```

6. In `tests/test_futures.py`, add four tests below the existing
   `test_distill_lessons_headings_are_unique_per_assessment` (ends line 159). All four use the
   existing `ec_db` fixture, the same one `test_get_lessons` at line 62 uses. Each seeds rows with
   explicit `created_at` values so recency order is deterministic rather than dependent on
   insertion timing — `create_assessment` stamps `created_at` itself, so these tests write the
   column directly:

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
       for i in range(40):
           _seed_lesson(ec_db, "neutral", f"2026-08-14T{i // 60:02d}:{i % 60:02d}:00+00:00")
       for i in range(8):
           _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=20, min_per_verdict=5)

       assert len(lessons) == 20
       expands = [item for item in lessons if item["verdict"] == "expand"]
       assert len(expands) >= 5


   def test_get_lessons_never_exceeds_limit(ec_db):
       """limit stays a total cap across all verdicts (S2)."""
       for verdict in ("expand", "narrow", "neutral"):
           for i in range(10):
               _seed_lesson(ec_db, verdict, f"2026-08-1{i}T00:00:00+00:00")

       assert len(get_lessons(ec_db, limit=9, min_per_verdict=5)) == 9


   def test_get_lessons_absent_verdict_forfeits_floor(ec_db):
       """A verdict with no rows must not shrink the result (S3)."""
       for i in range(12):
           _seed_lesson(ec_db, "neutral", f"2026-08-10T00:{i:02d}:00+00:00")

       lessons = get_lessons(ec_db, limit=10, min_per_verdict=5)

       assert len(lessons) == 10
       assert {item["verdict"] for item in lessons} == {"neutral"}


   def test_get_lessons_clamps_floors_below_limit(ec_db):
       """limit smaller than the combined floors still returns exactly limit (S4)."""
       for verdict in ("expand", "narrow", "neutral"):
           for i in range(4):
               _seed_lesson(ec_db, verdict, f"2026-08-0{i + 1}T00:00:00+00:00")

       lessons = get_lessons(ec_db, limit=2, min_per_verdict=5)

       assert len(lessons) == 2
   ```

   Add `DEFAULT_LESSONS_MIN_PER_VERDICT` to the existing
   `from entirecontext.core.futures import (...)` block at lines 8-15 only if a test references
   it; the four tests above pass `min_per_verdict` explicitly, so no import change is required.

7. Run `uv run pytest tests/test_futures.py -q`. The module held 14 passing tests at baseline, so
   expect 18. `test_get_lessons` at line 62 asserts a single seeded lesson comes back and must
   still pass unchanged — it is the guard that the new selection did not break the trivial case.

Acceptance: `uv run pytest tests/test_futures.py -q` reports 18 passed;
`uv run mypy src/entirecontext/` reports `Success: no issues found in 120 source files`;
`uv run ruff check src/entirecontext/core/futures.py src/entirecontext/core/config.py
tests/test_futures.py` exits 0; and
`rg -c "min_per_verdict" src/entirecontext/core/futures.py` returns a count of at least 6.

## U2: the three call sites honour the config key

Depends on: U1.
Produces: `futures lessons` and `ec_lessons` reading `lessons_min_per_verdict`; a CLI test proving
the config value reaches the core function.
Consumes: U1's `get_lessons` signature and config default.

Steps:

1. In `src/entirecontext/cli/futures_cmds.py`, the `futures_lessons` command (lines 231-259) does
   not currently load config at all. Replace the import line at 239 and the call at 250. The
   import becomes:

   ```python
   from ..core.futures import DEFAULT_LESSONS_MIN_PER_VERDICT, distill_lessons, get_lessons
   ```

   and after `repo_path = find_git_root()` succeeds and before `conn = get_db(repo_path)`, add:

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

2. In `src/entirecontext/mcp/tools/futures.py`, `ec_lessons` (lines 160-171) already receives the
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
   element is the repository path. If it is not a path, keep `_` and call
   `find_git_root()` from `...core.project` instead — do not pass a non-path into `load_config`.

3. Add one CLI test to `tests/test_futures_cmds_assess.py`, which already exercises this command
   group and already patches config at line 136. Place it at the end of the file:

   ```python
   def test_futures_lessons_passes_config_floor(ec_repo, monkeypatch, tmp_path):
       """The configured floor reaches get_lessons rather than the default (S5)."""
       from typer.testing import CliRunner

       from entirecontext.cli import app

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

       result = CliRunner().invoke(
           app, ["futures", "lessons", "--output", str(tmp_path / "OUT.md")]
       )

       assert result.exit_code == 0
       assert seen["min_per_verdict"] == 3
   ```

   Before running it, confirm the import style matches the file's existing tests: read
   `tests/test_futures_cmds_assess.py:1-40` and reuse whatever `app` and runner construction is
   already there rather than introducing a second convention. The command imports `get_lessons`
   into its local namespace at call time, so the `monkeypatch.setattr` target above is the module
   attribute the command resolves — verify with the test's own assertion rather than assuming.

4. Run `uv run pytest tests/test_futures.py tests/test_futures_cmds_assess.py tests/test_mcp.py -q`.

Acceptance: the pytest invocation in step 4 is green with one more test than baseline in
`tests/test_futures_cmds_assess.py`; `uv run mypy src/entirecontext/` reports Success on 120
files; `uv run ruff check src/entirecontext/` exits 0; and
`rg -l "lessons_min_per_verdict" src/entirecontext/ | wc -l` returns 4 — the config default,
`auto_distill_lessons`, and the two call sites.

## U3: document the key and close the ROADMAP row

Depends on: U1, U2.
Produces: the documented config key, the closed ROADMAP row, and the corrected `narrow` wording.
Consumes: the shipped config key name.

Steps:

1. In `README.md`, the `[futures]` config block shows `auto_distill = false` at line 619 and
   `lessons_output = "LESSONS.md"` at line 620. Read lines 610-630 first to see the block's exact
   comment style, then add below line 620:

   ```toml
   lessons_min_per_verdict = 5
   ```

   with a one-line explanation in the surrounding prose style: the minimum slots reserved per
   verdict inside the total lesson cap, so a run of one verdict cannot evict every lesson of
   another. Set it to `0` to restore pure recency ordering.

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
     the measured statement — `Expand 1 of 22 surviving, Neutral 49; narrow is absent from the
     corpus entirely (0 rows), so its missing section is corpus truth rather than eviction` — and
     append the closure sentence: `Fixed by per-verdict floor allocation inside the existing total
     cap; config key futures.lessons_min_per_verdict (default 5).`

   Leave every other row untouched.

4. Verify the row reads as intended: `rg -n "^- \[x\].*get_lessons" ROADMAP.md` must match exactly
   one line, and `grep -c "^- \[ \]" ROADMAP.md` must return 22 — one fewer than the 23 open
   `- [ ]` rows measured during this plan's trigger audit.

Acceptance: step 4's two commands return the stated values;
`rg -c "lessons_min_per_verdict" README.md docs/spec.md` returns 1 for each file; and
`rg -n "narrow" ROADMAP.md | rg -c "corpus"` returns at least 1, confirming the corrected wording
landed.

## U4: regenerate LESSONS.md against a verified install

Depends on: U1, U2, U3.
Produces: the regenerated `LESSONS.md`, and the install-provenance evidence required by transition
T1.
Consumes: the shipped selection code.

This unit carries the Known Pattern obligation. Skipping it does not merely leave `LESSONS.md`
stale — the next hook-driven `auto_distill` regenerates it from the stale global install and
reverts the fix, exactly as recorded for this function in
`docs/solutions/developer-experience/installed-tool-drifts-from-checkout.md`.

Steps:

1. Create the evidence directory and record the pre-repair state **before** touching the install.
   Every variable below is assigned in this step:

   ```sh
   mkdir -p .release-loop/evidence/U4
   EVIDENCE=.release-loop/evidence/U4/install-provenance.txt
   EC_BIN=$(command -v ec || true)
   {
     echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
     echo "checkout_head: $(git rev-parse HEAD)"
     echo "resolved_ec: ${EC_BIN:-none}"
   } > "$EVIDENCE"
   ```

2. If `EC_BIN` is empty, append `installed_state: no global install resolved` to `$EVIDENCE` and
   skip to step 5 — the headless row of transition T1. Otherwise resolve the installed package and
   record whether the fix is present in it:

   ```sh
   EC_PY=$(head -1 "$EC_BIN" | sed 's/^#!//')
   PKG_DIR=$("$EC_PY" -c 'import entirecontext, os; print(os.path.dirname(entirecontext.__file__))')
   {
     echo "installed_python: $EC_PY"
     echo "installed_pkg_dir: $PKG_DIR"
     echo "min_per_verdict_in_install_before: $(grep -c min_per_verdict "$PKG_DIR/core/futures.py" || true)"
   } >> "$EVIDENCE"
   ```

   A count of `0` is the expected pre-state and confirms the drift this unit repairs. Do not use
   `ec --version` as the check — the Known Pattern records that both copies report the same version
   string while the code differs.

3. Reinstall from the checkout and verify the reinstall actually took, rather than assuming it did:

   ```sh
   uv tool install --force .
   PKG_DIR=$(head -1 "$(command -v ec)" | sed 's/^#!//' | xargs -I{} {} -c 'import entirecontext, os; print(os.path.dirname(entirecontext.__file__))')
   echo "min_per_verdict_in_install_after: $(grep -c min_per_verdict "$PKG_DIR/core/futures.py")" >> "$EVIDENCE"
   ```

   The after-count must be at least 6, matching U1's acceptance. A count of `0` means the reinstall
   did not take and the fix is inert in the environment whose output lands back in this repository
   — stop and resolve it before proceeding.

4. Re-run the same verification a second time to establish the Rerun row of transition T1:
   `uv tool install --force .` again, repeat the grep, and append the count as
   `min_per_verdict_in_install_rerun:`. The two counts must match.

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
   " | tee -a .release-loop/evidence/U4/install-provenance.txt
   ```

   Expect `returned 50` and an `expand` count of at least 5, against the planning-time baseline of
   `{'expand': 1, 'neutral': 49}`. A `narrow` key will still be absent — the corpus has no `narrow`
   rows, and U3 step 3 records that as corpus truth.

7. Confirm `LESSONS.md` changed and that its Expand section now holds more than one entry:
   `rg -c "^### " LESSONS.md` returns 50, and the count of `### ` lines between the
   `## 🟢 Expand` heading and the next `## ` heading is at least 5.

Acceptance: `.release-loop/evidence/U4/install-provenance.txt` exists and contains a
`min_per_verdict_in_install_after` count of at least 6 (or the headless `no global install
resolved` line); step 6 reports an `expand` count of at least 5; step 7's two counts hold; and
`uv run pytest tests/test_futures.py -q` is still green after the regeneration.

## Open unknowns

**Planning-time** — none. The one contract fork (whether `limit` stays a total cap or becomes
per-verdict) was resolved before authoring: `limit` stays a total cap, because it is exposed as the
`ec_lessons` MCP parameter and reinterpreting it would silently return up to three times what a
caller asked for.

**Implementation-time**:
- Whether `runtime.open_repo()`'s second tuple element is a repository path. U2 step 2 names the
  command that answers it and the fallback to use if it is not.
- The exact import and runner construction already used by `tests/test_futures_cmds_assess.py`.
  U2 step 3 instructs the implementer to read the file's first 40 lines and reuse its convention
  rather than introducing a second one.
- The surrounding prose form of the `[futures]` blocks in `README.md` and `docs/spec.md`. U3 steps
  1 and 2 name the line ranges to read first.
- The pre-repair `min_per_verdict` count in the installed package. Expected to be `0`, but it is
  recorded when observed rather than predicted — the install may already have been refreshed.

## Deferred to Follow-Up Work

- **`get_surfaceable_lessons` carries the same flat-recency shape.**
  `src/entirecontext/core/lesson_surfacing.py:11-17`, called at line 110 with `limit=200`. Against
  today's 120-row corpus it evicts nothing, so it is not the reported defect and fixing it now
  would be an unmeasured change. Revisit trigger: the feedback-bearing corpus passing 200 rows,
  measurable with
  `sqlite3 .entirecontext/db/local.db "SELECT COUNT(*) FROM assessments WHERE feedback IS NOT NULL"`.
- **`futures lessons` ignores `futures.lessons_output`.** The `--output` option defaults to the
  literal `LESSONS.md` rather than the configured value, unlike `auto_distill_lessons`. Pre-existing
  inconsistency, unrelated to verdict selection.
- **`ROADMAP.md:360` build-SHA provenance stamp.** U4 repairs this instance of install drift
  operationally; the row asks for `ec doctor` to detect it automatically. That is a different
  change to different files and stays open.
- **`ROADMAP.md:358` re-query review threads immediately before merge.** Fires at this work's Ship
  phase, not in any planning unit. Recorded so `shipping` inherits it.
