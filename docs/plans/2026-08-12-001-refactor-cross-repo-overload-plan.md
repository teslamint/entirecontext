---
schema: plan/v1
title: "@overload for the include_warnings cross-repo functions"
type: refactor
status: draft
date: 2026-08-12
execution: code
origin: docs/specs/2026-08-12-cross-repo-overload-design.md
---

# @overload for the `include_warnings` cross-repo functions

## Goal

Declare `@overload` variants keyed on `Literal[False]` / `Literal[True]` for the eleven
`cross_repo_*` functions whose return type is conditional on `include_warnings`, then delete
the four MCP `cast` workarounds those unions forced. No runtime behavior changes.

## Architecture notes

The eleven functions split into two implementation styles, and the split is **exactly aligned**
with the return shape. This was verified during planning and is what makes the unit boundaries
clean rather than arbitrary:

| Return shape | Count | How the body returns | Function lines |
|---|---|---|---|
| `list[dict]` | 7 | `return _return_with_warnings(results, warnings, include_warnings)` | 180, 264, 279, 319, 335, 351, 421 |
| `dict \| None` | 3 | inline `if include_warnings: return result, warnings` | 298, 375, 391 |
| `dict` | 1 | inline `if include_warnings:` | 443 |

Helper call sites are at lines 261, 276, 295, 332, 348, 372, 440; inline branches at 314, 386,
412, 504. Seven plus four is eleven, and the helper-vs-inline split maps one-to-one onto
`list[dict]` vs. everything else.

`_return_with_warnings` (line 174) returns bare `Any` and is deliberately left alone — spec
Open Decision D1. Because it returns `Any`, the seven functions that route through it type-check
against any declared return, so their overloads are constrained by the *callers*, not by the
helper.

**Invariant that must survive**: the seven helper call sites pass `include_warnings`
**positionally** as the helper's third argument. The helper is not being overloaded, so this is
safe today. Anyone later applying the same keyword-only pattern to `_return_with_warnings` must
convert these seven call sites first.

**Known Pattern**: PR #215 (`chore(mcp): lift the entirecontext.mcp.* mypy overrides`, merged
`9dbfc90`) established this repository's approach to mypy debt — measure the error count first,
convert in shape-groups, and re-measure between groups rather than converting everything and
debugging a large error list. This plan follows that sequence. `docs/solutions/` contains no
typing or mypy learnings (verified: `rg -l -i "mypy|overload|typing" docs/solutions/` returns
nothing), so there is no prior guidance to apply.

**Vocabulary** (`CONCEPTS.md`): a *repo warning* is a per-repo failure returned alongside
results instead of aborting the query; a *partial cross-repo result* is what you get when some
repositories fail. `include_warnings` is the caller's choice to surface them.

## Assumption Recheck

The origin spec retains eight live assumptions. Every command was rerun in this worktree at
`c3aab1c` before authoring the units.

| # | Claim | Rerun result | Outcome |
|---|---|---|---|
| 1 | Eleven public functions carry `include_warnings`; the twelfth occurrence is the helper's parameter | `rg -c "include_warnings: bool"` → 12; `rg -n "^def cross_repo_" \| wc -l` → 11 | **match** |
| 2 | Three distinct return shapes: `list[dict]` ×7, `dict \| None` ×3, `dict` ×1 | `rg -n "^\) -> "` filtered per shape → 7 / 3 / 1 | **match** |
| 3 | No caller passes `include_warnings` as a non-literal | `rg -n "include_warnings=(?!True\|False)" -P src/ tests/` → 0 lines | **match** |
| 4 | No caller passes `include_warnings` positionally | `rg -n "include_warnings" src/ tests/` minus keyword and declaration forms → 28 lines, all of them test method names, `# cast:` comments, internal `if include_warnings:` branches, and the helper-forwarding calls; zero call-site positional uses | **match** |
| 5 | Spike: overloads on `cross_repo_search` + cast removal leaves mypy clean | Not re-executed. `git status --porcelain -- src/ tests/` returns 0 lines at the same commit the spike ran against, so the spike inputs are byte-identical and re-running would reproduce it by construction. U1's acceptance check re-establishes it as a first-class result | **match** (precondition re-verified, not re-executed) |
| 6 | The four `include_warnings` casts are the only `cast(` calls in the package | `rg -n "\bcast\(" src/entirecontext/` → 4 | **match** |
| 7 | The keyword-only `*` is a choice, not a syntactic necessity | Not re-executed; the scratch module was not committed. The claim is a negative about Python/mypy semantics, not about this repo, and U1's step 1 re-derives the chosen form directly | **match** (claim is repo-independent) |
| 8 | Baseline clean: 2183 passed / 1 skipped, mypy Success on 120 files | `uv run mypy src/entirecontext/` → `Success: no issues found in 120 source files`. The suite was not re-run (3m38s) and is re-established by U4 | **match** (mypy re-executed; suite deferred to U4) |

No contradictions. No deviation addendum required.

## File structure

| File | Change |
|---|---|
| `src/entirecontext/core/cross_repo.py` | add `Literal` and `overload` imports; add 22 `@overload` stubs |
| `src/entirecontext/mcp/tools/search.py` | delete 1 cast + its comment; drop `cast` from the `typing` import |
| `src/entirecontext/mcp/tools/session.py` | delete 2 casts + their comments; drop `cast` from the `typing` import |
| `src/entirecontext/mcp/tools/checkpoint.py` | delete 1 cast + its comment; drop `cast` from the `typing` import |
| `ROADMAP.md` | mark the v0.16.0 `@overload` row complete |

No file is created. No test file is added: the overloads are a static declaration, and a
runtime test asserting a type declaration would duplicate mypy at worse fidelity. mypy is the
added check, made a measured one by the non-vacuity and positional-rejection steps in U4.

## Carry-forward trigger audit

Tracker examined: `ROADMAP.md`, 22 open `- [ ]` rows at `c3aab1c`.

**Fired rows and their dispositions:**

| Row | Trigger class | Why it fired | Disposition |
|---|---|---|---|
| `ROADMAP.md:360` `@overload` cross-repo functions | edit-based — names `core/cross_repo.py` and the four MCP tool files | Every named file is in this plan's File structure | **Folded in** — this plan implements the row; U4 marks it complete |
| `ROADMAP.md:355` Spec directory drift | drift-based — names the observable divergence between AGENTS.md's `docs/superpowers/specs/` and where specs are actually written | This cycle's spec was written to `docs/specs/2026-08-12-cross-repo-overload-design.md`, continuing the drift rather than resolving it | **Deferred to Follow-Up Work** — relocating one spec while five others stay put converts an observable drift into a silent inconsistency. Same reasoning PR #205 recorded; the row stays open |
| `ROADMAP.md:358` Plan-vs-spec test enumeration check | event-based — fires whenever a plan is written from a spec | This is such a plan | **Applied in this pass** — the spec's Testing section names five checks and no new test functions. All five appear in U4's acceptance. Nothing was merged or dropped; see U4 |
| `ROADMAP.md:357` Re-query review threads before merge | event-based — fires at a merge | This loop will reach Ship | **Deferred to Follow-Up Work** — it governs `shipping`, not any planning unit. Recorded so the Ship phase inherits it rather than rediscovering it |

**Unobservable rows:** none. Every remaining row's trigger is either edit-based against files
absent from this plan (`cli/project_cmds.py` ×3 at 353/354/356, `core/archaeology.py` ×2 at
338/381, `core/decisions.py` at 413, build config at 359), drift-based against metrics readable
today and unchanged by this plan (204/265/336/379 maturity 64, 300 applied-context 1%, 301
lesson-reuse 14%, 392 alpha status, 231 verdict mapping), or event-based on an occurrence this
cycle does not produce (376 export authorization, 406/408 product scope).

**Attestation**: all 22 open rows were classified; 4 fired; 4 have dispositions above; 0 were
skipped.

## Scenario coverage map

| S-ID | Scenario | Unit chain | Scenario evidence |
|---|---|---|---|
| S1 | A new MCP tool calls a cross-repo function and gets warnings | U2 | `uv run pytest tests/test_mcp.py` plus `uv run mypy src/entirecontext/` with the three `dict \| None` casts deleted — the de-cast `.get()` calls are the assertion |
| S2 | A caller that does not want warnings | U1 | `uv run pytest tests/test_cross_repo.py tests/test_cross_repo_expanded.py`; `test_include_warnings_false*` walk the omitted/False arm |
| S3 | Removing a cast does not change what the tool returns | U1 → U2 | `uv run pytest tests/test_mcp.py` — same payload assertions before and after |
| S4 | A caller passing `include_warnings` positionally is now rejected | U1 → U2 → U3 | U4 step 3's explicit positional-rejection check, which is the only place this becomes observable |
| S5 | mypy stays enforcing | U4 | `uv run mypy src/entirecontext/` → Success on 120 files, with `rg -c "entirecontext.mcp\|entirecontext.core" pyproject.toml` confirming no override was reintroduced |

Every S-ID completes. No scenario is stranded mid-chain.

## Mutation/failure-state matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## U1: `@overload` for the seven `list[dict]` functions

Depends on: nothing.
Produces: `Literal`/`overload` imports and 14 overload stubs in `cross_repo.py`; `search.py` cast-free.
Consumes: the existing bodies, unchanged.

Steps:

1. In `src/entirecontext/core/cross_repo.py`, change line 8 from
   `from typing import Any, Callable` to
   `from typing import Any, Callable, Literal, overload`.

2. For each of these seven functions — `cross_repo_search` (line 180), `cross_repo_sessions`
   (264), `cross_repo_checkpoints` (279), `cross_repo_events` (319), `cross_repo_attribution`
   (335), `cross_repo_related` (351), `cross_repo_assessments` (421) — insert two `@overload`
   stubs immediately above the existing `def`, leaving the existing `def` and its body
   untouched. Each stub copies the target function's full parameter list verbatim, replacing
   every default value with `...`. The first stub ends its parameter list with
   `include_warnings: Literal[False] = ...` and returns `list[dict]`. The second stub inserts a
   bare `*` before `include_warnings`, declares `include_warnings: Literal[True]` with **no**
   default, and returns `tuple[list[dict], list[WarningEntry]]`. Both stub bodies are `...` on
   the same line as the closing `:`.

   Worked form for `cross_repo_sessions`, whose real signature is
   `(repos: list[str] | None = None, limit: int = 20, include_warnings: bool = False)`:

   ```python
   @overload
   def cross_repo_sessions(
       repos: list[str] | None = ...,
       limit: int = ...,
       include_warnings: Literal[False] = ...,
   ) -> list[dict]: ...
   @overload
   def cross_repo_sessions(
       repos: list[str] | None = ...,
       limit: int = ...,
       *,
       include_warnings: Literal[True],
   ) -> tuple[list[dict], list[WarningEntry]]: ...
   def cross_repo_sessions(
       repos: list[str] | None = None,
       limit: int = 20,
       include_warnings: bool = False,
   ) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
   ```

   Read each function's real parameter list from the file rather than adapting this example —
   the seven differ (`cross_repo_search` has eleven parameters, `cross_repo_assessments` has a
   `verdict` filter).

   Do **not** give the `Literal[True]` stub a `= ...` default. That form also type-checks, but
   it makes a no-argument call match both stubs, so resolution then depends on stub order —
   spec Architecture records the measurement behind this choice.

3. Leave the implementation `def` line and its `-> list[dict] | tuple[list[dict], list[WarningEntry]]`
   annotation exactly as they are. The union is what the body satisfies; the stubs are what
   callers see.

4. In `src/entirecontext/mcp/tools/search.py`, delete the three-line `# cast:` comment at lines
   58-60 and unwrap the `cast(...)` at line 61 so the assignment becomes
   `results = cross_repo_search(` with its existing argument list and the trailing `)` of the
   cast removed. Then change line 8 from `from typing import Any, cast` to
   `from typing import Any` — `Any` is still used by the `results: list[dict[str, Any]]`
   declaration at line 30.

5. Run `uv run mypy src/entirecontext/`. Expect `Success: no issues found in 120 source files`.
   A failure here means a stub's parameter list diverged from its body's.

Acceptance: `uv run mypy src/entirecontext/` reports Success on 120 files;
`uv run ruff check src/entirecontext/` exits 0; `uv run pytest tests/test_cross_repo.py
tests/test_cross_repo_expanded.py tests/test_cross_repo_futures.py` is green; and
`rg -c "^@overload" src/entirecontext/core/cross_repo.py` returns 14.

## U2: `@overload` for the three `dict | None` functions

Depends on: U1 (the `Literal`/`overload` imports).
Produces: 6 overload stubs; `session.py` and `checkpoint.py` cast-free.
Consumes: U1's imports.

Steps:

1. Insert two `@overload` stubs immediately above each of `cross_repo_session_detail`
   (line 298), `cross_repo_rewind` (375), and `cross_repo_turn_content` (391), leaving each
   existing `def` and body untouched. Each stub copies its target's full parameter list
   verbatim with every default replaced by `...`. The first stub ends with
   `include_warnings: Literal[False] = ...` and returns `dict | None`; the second inserts a
   bare `*` before `include_warnings`, declares `include_warnings: Literal[True]` with no
   default, and returns `tuple[dict | None, list[WarningEntry]]`. Both stub bodies are `...` on
   the same line as the closing `:`. Do not give the `Literal[True]` stub a `= ...` default —
   that form makes a no-argument call match both stubs, so resolution would depend on stub
   order.

   Worked form for `cross_repo_rewind`, whose real signature is
   `(checkpoint_id: str, repos: list[str] | None = None, include_warnings: bool = False)`:

   ```python
   @overload
   def cross_repo_rewind(
       checkpoint_id: str,
       repos: list[str] | None = ...,
       include_warnings: Literal[False] = ...,
   ) -> dict | None: ...
   @overload
   def cross_repo_rewind(
       checkpoint_id: str,
       repos: list[str] | None = ...,
       *,
       include_warnings: Literal[True],
   ) -> tuple[dict | None, list[WarningEntry]]: ...
   ```

   `checkpoint_id` has no default, so it keeps none in the stubs. Read the other two functions'
   real first parameters from the file — `cross_repo_session_detail` takes `session_id: str` and
   `cross_repo_turn_content` takes `turn_id: str`.

2. These three bodies use an inline `if include_warnings: return result, warnings` rather than
   the `_return_with_warnings` helper. Do not change that; the stubs describe it correctly
   either way.

3. In `src/entirecontext/mcp/tools/session.py`, delete the two `# cast:` comment pairs (lines
   23-24 and 193-194) and unwrap both `cast(...)` calls so each becomes
   `result, warnings = cross_repo_session_detail(session_id, repos=repo_names, include_warnings=True)`
   and `result, warnings = cross_repo_turn_content(turn_id, repos=repo_names, include_warnings=True)`
   respectively. Then drop `cast` from that file's `typing` import, keeping `Any` if the file
   still uses it — check with `rg -n "\bAny\b" src/entirecontext/mcp/tools/session.py` before
   editing the import line.

4. In `src/entirecontext/mcp/tools/checkpoint.py`, delete the `# cast:` comment at lines 107-108
   and unwrap the `cast(...)` at line 109 so it becomes
   `result, warnings = cross_repo_rewind(checkpoint_id, repos=repo_names, include_warnings=True)`.
   Then drop `cast` from that file's `typing` import, keeping `Any` — it is used by
   `params: list[Any]` at line 58 and `register_tools(mcp: Any, ...)` at line 163.

5. Run `uv run mypy src/entirecontext/`. This is the unit's real assertion: all three de-cast
   sites call `.get()` on the unpacked first element, which only type-checks if the
   `Literal[True]` stub resolved to `tuple[dict | None, ...]`.

Acceptance: `uv run mypy src/entirecontext/` reports Success on 120 files;
`uv run ruff check src/entirecontext/` exits 0; `uv run pytest tests/test_mcp.py` is green;
`rg -c "^@overload" src/entirecontext/core/cross_repo.py` returns 20; and
`rg -n "\bcast\(" src/entirecontext/` returns no matches.

## U3: `@overload` for the bare-`dict` function

Depends on: U1 (imports).
Produces: 2 overload stubs on `cross_repo_assessment_trends`.
Consumes: U1's imports.

Steps:

1. Insert two `@overload` stubs immediately above `cross_repo_assessment_trends` (line 443),
   leaving its existing `def` and body untouched. The first stub ends its parameter list with
   `include_warnings: Literal[False] = ...` and returns `dict`; the second inserts a bare `*`
   before `include_warnings`, declares `include_warnings: Literal[True]` with no default, and
   returns `tuple[dict, list[WarningEntry]]`. Both stub bodies are `...` on the same line as
   the closing `:`. Do not give the `Literal[True]` stub a `= ...` default — that form makes a
   no-argument call match both stubs, so resolution would depend on stub order.

   The function's real signature is
   `(repos: list[str] | None = None, since: str | None = None, include_warnings: bool = False)`,
   giving:

   ```python
   @overload
   def cross_repo_assessment_trends(
       repos: list[str] | None = ...,
       since: str | None = ...,
       include_warnings: Literal[False] = ...,
   ) -> dict: ...
   @overload
   def cross_repo_assessment_trends(
       repos: list[str] | None = ...,
       since: str | None = ...,
       *,
       include_warnings: Literal[True],
   ) -> tuple[dict, list[WarningEntry]]: ...
   def cross_repo_assessment_trends(
       repos: list[str] | None = None,
       since: str | None = None,
       include_warnings: bool = False,
   ) -> dict | tuple[dict, list[WarningEntry]]:
   ```

2. This function has no cast to remove — its two call sites,
   `src/entirecontext/cli/futures_cmds.py:450` and `src/entirecontext/mcp/tools/futures.py:178`,
   already unpack the tuple without one. They are the assertion: both must still type-check.

3. Run `uv run mypy src/entirecontext/`.

Acceptance: `uv run mypy src/entirecontext/` reports Success on 120 files;
`rg -c "^@overload" src/entirecontext/core/cross_repo.py` returns 22; and
`uv run pytest tests/test_cross_repo_futures.py` is green.

## U4: Verification gate and ROADMAP closure

Depends on: U1, U2, U3.
Produces: the measured evidence for all six success criteria, and the ROADMAP row marked done.
Consumes: the converted `cross_repo.py` and the three de-cast MCP files.

No new test file is added. The overloads are a static declaration; a runtime test asserting a
type declaration would duplicate mypy at worse fidelity. mypy **is** the added check, and steps
2 and 3 below make it a measured one rather than an assumed one.

Steps:

1. Run each of the spec's five declared checks and record the observed output in
   `.release-loop/progress.md`:
   - `uv run mypy src/entirecontext/`
   - `uv run pytest tests/test_cross_repo.py tests/test_cross_repo_futures.py tests/test_cross_repo_expanded.py`
   - `uv run pytest tests/test_mcp.py`
   - `uv run ruff check .`
   - `uv run pytest -q` (expect 2183 passed, 1 skipped)

2. Non-vacuity check for SC6, proving the overloads are load-bearing rather than inert. Delete
   only the two `@overload` stubs above `cross_repo_rewind`, leaving its implementation and the
   de-cast call in `mcp/tools/checkpoint.py` in place. Run `uv run mypy src/entirecontext/` and
   confirm it now reports an error at `src/entirecontext/mcp/tools/checkpoint.py`. Record the
   verbatim error text in the ledger, then restore the two stubs and re-run mypy to confirm
   Success. If mypy stays clean with the stubs removed, the overloads are not doing the work
   the plan claims and U2 must be revisited before proceeding.

3. Positional-rejection check, the only observable evidence for scenario S4. Write a scratch
   file outside the repository containing
   `from entirecontext.core.cross_repo import cross_repo_rewind` followed by
   `cross_repo_rewind("x", None, True)`, run `uv run mypy` on it, and confirm mypy reports a
   no-matching-overload error. Record the error text in the ledger and delete the scratch file.
   Do not add it to the repository — it is a check, not a test.

4. In `ROADMAP.md`, change the `@overload` row (line 360) from `- [ ]` to `- [x]` and append to
   its text: `Completed in this cycle: 22 overload stubs across the eleven functions, all four
   casts removed, mypy enforced at zero.` Leave every other row untouched.

5. Confirm no mypy override was reintroduced:
   `rg -n "entirecontext\.(mcp|core)" pyproject.toml` must return no `ignore_errors` context.

Acceptance: all five commands in step 1 pass with the recorded outputs; step 2's error appears
and then disappears; step 3's error appears; `rg -n "^- \[x\].*@overload" ROADMAP.md` matches
one line; and `rg -n "\bcast\(" src/entirecontext/` returns no matches.

## Open unknowns

**Planning-time** — none. Every fork the spec left open was resolved before approval, and the
Assumption Recheck found no contradictions.

**Implementation-time**:
- The exact parameter lists of the eleven functions are read from the file at edit time rather
  than reproduced here. U1 step 2 and U2 step 1 give one worked example each and instruct the
  implementer to read the rest; reproducing eleven full signatures in this plan would create a
  second source of truth that drifts.
- Whether `Any` remains needed in each MCP tool file's `typing` import after `cast` is dropped.
  U2 steps 3 and 4 name the check (`rg -n "\bAny\b" <file>`) and record what the answer is for
  `checkpoint.py`; `session.py` is left to the check because its usage was not enumerated.
- The verbatim mypy error texts from U4 steps 2 and 3. They are recorded when observed, not
  predicted.

## Deferred to Follow-Up Work

- **`_return_with_warnings` keeps `-> Any`** (spec Open Decision D1). Overloading the helper
  would let the seven `list[dict]` bodies keep a precise internal type, but the helper's `Any`
  is invisible to callers once the public functions are overloaded, so it is cleanup with no
  external effect. It would also require converting the seven positional forwarding calls at
  lines 261, 276, 295, 332, 348, 372, and 440 if the same keyword-only pattern were applied.
- **Widening bare `dict` to `dict[str, Any]`** in the eleven return types. Real imprecision,
  but its blast radius is the functions' internals rather than their signatures — a separate
  change with a separate measurement.
- **`ROADMAP.md:355` spec directory drift.** This cycle's spec went to `docs/specs/`, continuing
  the divergence from AGENTS.md's `docs/superpowers/specs/`. Relocating one spec while five
  others stay put converts an observable drift into a silent inconsistency. The row stays open.
- **`ROADMAP.md:357` re-query review threads immediately before merge.** Fires at this loop's
  Ship phase, not in any planning unit. Recorded here so `shipping` inherits it.
