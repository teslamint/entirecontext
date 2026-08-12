---
title: "@overload for the include_warnings cross-repo functions"
status: draft
date: 2026-08-12
schema: spec/v1
---

# @overload for the `include_warnings` cross-repo functions Design

_Created 2026-08-12._

## Overview

Eleven public functions in `src/entirecontext/core/cross_repo.py` return one shape when
`include_warnings=False` and a different shape when `include_warnings=True`, declared as a
union. mypy cannot pick the arm from a literal argument, so callers receive the union and four
MCP call sites suppress the consequence with `cast`. This replaces the union declarations with
`@overload` variants keyed on `Literal[False]` / `Literal[True]` and deletes the four casts.

No runtime behavior changes. The deliverable is a type declaration that matches what the
functions already do.

## User Scenarios

### S1: A new MCP tool calls a cross-repo function

An agent adds an MCP tool that needs warnings. It writes the obvious code and mypy accepts it,
because the `Literal[True]` overload resolves the return type to the tuple.

```python
result, warnings = cross_repo_rewind(checkpoint_id, repos=repo_names, include_warnings=True)
if not result:
    return runtime.error_payload(f"Checkpoint not found: {checkpoint_id}", warnings=warnings)
return json.dumps({"checkpoint_id": result.get("id", "")})   # .get() type-checks
```

Today the same code fails type checking and the author must copy a `cast` and its explanatory
comment from a neighboring file.

### S2: A caller that does not want warnings

`cli/session_cmds.py:27` calls `cross_repo_sessions(repos=repo, limit=limit)` with
`include_warnings` omitted. The `Literal[False]` overload applies and the return type is
`list[dict]` rather than a union, so iterating it needs no narrowing.

### S3: Removing a cast does not change what the tool returns

`ec_rewind`'s cross-repo branch produces the same JSON payload before and after. The `cast` was
a compile-time assertion with no runtime effect; deleting it is observationally inert. The
existing MCP tests are the evidence.

### S4: A caller passes `include_warnings` positionally

`cross_repo_rewind(checkpoint_id, repos, True)` no longer type-checks: the `Literal[True]`
overload makes `include_warnings` keyword-only. This is a deliberate narrowing — see Interface.
No such caller exists today (measured, see Assumptions).

### S5: mypy stays enforcing

`mypy src/entirecontext/` is already clean and already covers `entirecontext.mcp.*` after
PR #215 lifted its overrides. This change must keep it at zero, not merely avoid adding
`ignore_errors` back.

## Scope

### In

- `@overload` pairs for the eleven public `cross_repo_*` functions carrying `include_warnings`.
- Deletion of the four `cast` calls, their explanatory comments, and the `cast` imports left
  unused in `mcp/tools/search.py` and `mcp/tools/checkpoint.py`.
- The ROADMAP v0.16.0 `@overload` item marked complete.

### Out

- Any runtime behavior change in `cross_repo.py` or the MCP tools.
- `_return_with_warnings`'s `-> Any` return annotation. See Open Decisions.
- Widening `dict` to `dict[str, Any]` in the return types. The existing bare `dict` is
  imprecise, but tightening it is a separate change with its own blast radius across the
  eleven functions' internals.
- Changing `include_warnings`'s default or removing the parameter.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| Exactly eleven public functions carry `include_warnings`; the twelfth occurrence is the helper's own parameter | `rg -c "include_warnings: bool" src/entirecontext/core/cross_repo.py` and `rg -n "^def cross_repo_" src/entirecontext/core/cross_repo.py` | `2026-08-12T15:00:00+09:00` | 12 occurrences; 11 public functions at lines 180, 264, 279, 298, 319, 335, 351, 375, 391, 421, 443; line 174 is `_return_with_warnings` | Worktree at `94291a4` |
| The eleven span three distinct return shapes, so overloads cannot be written from one template | `rg -n "^\) -> " src/entirecontext/core/cross_repo.py` | `2026-08-12T15:00:00+09:00` | `list[dict]` ×7 (193, 269, 285, 325, 341, 357, 427); `dict \| None` ×3 (302, 379, 395); `dict` ×1 (447) — 7+3+1 = 11 | Worktree at `94291a4` |
| No caller passes `include_warnings` as a non-literal, so `Literal` overloads cover every call site | `rg -n "include_warnings=(?!True\|False)" -P src/ tests/` | `2026-08-12T15:02:00+09:00` | zero matches | Worktree at `94291a4` |
| No caller passes `include_warnings` positionally, so making the `True` overload keyword-only breaks nothing | `rg -n "include_warnings" src/ tests/` reviewed for positional use | `2026-08-12T15:02:00+09:00` | every occurrence is `include_warnings=True` or `include_warnings=False`; none positional | Worktree at `94291a4` |
| The mechanism works and removing a cast leaves mypy clean — verified by spike on one function of each shape, then reverted | overloads added to `cross_repo_rewind` (`dict \| None`) and `cross_repo_search` (`list[dict]`), casts removed in `mcp/tools/checkpoint.py` and `mcp/tools/search.py`, then `uv run mypy src/entirecontext/` | `2026-08-12T15:05:00+09:00` | `Success: no issues found in 120 source files`; `ruff check` reported exactly 2 errors, both the now-unused `typing.cast` imports | Spike applied and reverted in the worktree; `git checkout --` restored `94291a4` and mypy re-confirmed clean |
| The four `include_warnings` casts are the only `cast(` calls in the package, so removing them makes the package-wide count zero | `rg -n "\bcast\(" src/entirecontext/` | `2026-08-12T15:10:00+09:00` | 4 matches: `mcp/tools/search.py` ×1, `mcp/tools/session.py` ×2, `mcp/tools/checkpoint.py` ×1; zero elsewhere | Worktree at `94291a4` |
| The existing suite exercises both arms | `sed -n '109p;113p;242p' tests/test_cross_repo_futures.py` | `2026-08-12T15:10:00+09:00` | `cross_repo_assessments(include_warnings=False)`, `cross_repo_assessments(include_warnings=True)`, `trends, warnings = cross_repo_assessment_trends(include_warnings=True)` | Worktree at `94291a4` |
| The keyword-only `*` is a choice, not a syntactic necessity — the `= ...` alternative also resolves correctly | a scratch module declaring both overloads with `flag: Literal[True] = ...` and no `*`, checked with `uv run mypy` and `reveal_type` on four call forms | `2026-08-12T16:05:00+09:00` | `Success: no issues found`; `f(1)` → `list[int]`, `f(1, False)` → `list[int]`, `f(1, True)` → `tuple[...]`, `f(1, flag=True)` → `tuple[...]`. The no-argument call matches both stubs and resolves by declaration order | Scratch file, not committed |
| The bare-`dict` shape works against its two live unpacking call sites | `@overload` added to `cross_repo_assessment_trends` only, then `uv run mypy src/entirecontext/` | `2026-08-12T16:10:00+09:00` | `Success: no issues found in 120 source files`, with `cli/futures_cmds.py:450` and `mcp/tools/futures.py:178` both unpacking the tuple arm | Spike applied and reverted; `git checkout --` restored `94291a4` and mypy re-confirmed clean |
| Baseline is clean before any change | `uv run pytest -q --tb=no`; `uv run mypy src/entirecontext/` | `2026-08-12T15:00:00+09:00` | 2183 passed, 1 skipped; `Success: no issues found in 120 source files` | Worktree at `94291a4` |

Repository invariants that still apply: `pyproject.toml` carries no `ignore_errors` override
for `entirecontext.core.*` or `entirecontext.mcp.*` after PR #215, so both packages are
enforced by the CI type-check job.

## Architecture

Nothing moves. Each of the eleven functions gains two `@overload` stubs directly above its
existing definition; the implementation body is untouched.

```
@overload
def cross_repo_X(..., include_warnings: Literal[False] = ...) -> X: ...
@overload
def cross_repo_X(..., *, include_warnings: Literal[True]) -> tuple[X, list[WarningEntry]]: ...
def cross_repo_X(..., include_warnings: bool = False) -> X | tuple[X, list[WarningEntry]]:
    <unchanged body>
```

`X` is per-function and takes three values (Assumptions row 2): `list[dict]` for seven,
`dict | None` for three, and bare `dict` for one — `cross_repo_assessment_trends`, whose
non-warnings arm returns a mapping rather than a list. The implementation signature keeps its
union return so the body — which returns both arms — still type-checks against it.

The `*` in the second stub is a **choice with a trade-off**, not a necessity. An earlier draft
of this spec claimed it was the only legal ordering; that was falsified by measurement
(Assumptions row 7). The alternative — `include_warnings: Literal[True] = ...` with no `*` —
parses, type-checks, and resolves every call correctly, including positional ones.

The two differ in one respect that matters here:

| | keyword-only (`*`) — chosen | `= ...` — rejected |
|---|---|---|
| Positional `include_warnings` | rejected by mypy | accepted |
| A call omitting the argument | matches only the `Literal[False]` stub | matches **both** stubs; mypy resolves it by picking the first, so correctness depends on stub order |

Order-independence wins. Eleven near-identical stub pairs are exactly where a reordering slips
through review, and under `= ...` a reordered pair would silently resolve the no-argument call
to the tuple type rather than failing. The cost is the narrowing in Interface, which is free
today (Assumptions row 4).

Design-for-isolation: an overload set is a declaration about an existing callable. Callers
depend on the resolved return type, not on how the stubs are written; the body can change
freely as long as it still satisfies the union.

## Interface

The public API is unchanged in every respect a runtime caller can observe. Two static-only
changes:

| Change | Before | After |
|---|---|---|
| Return type at a call site | `X \| tuple[X, list[WarningEntry]]` regardless of argument | `X` when `include_warnings` is omitted or `False`; `tuple[X, list[WarningEntry]]` when `True` |
| `include_warnings=True` passed positionally | accepted by mypy | rejected — keyword-only on that overload |

The second is a deliberate narrowing. It costs nothing today (Assumptions row 4) and its
alternative — declaring `include_warnings: Literal[True] = ...` in the stub — would state a
default of `True` that the implementation contradicts.

## Error handling

Unchanged. `FTSQueryError` and `ValueError` propagate exactly as they do now, and the
per-repo fault isolation that collects `WarningEntry` rows is untouched. No overload
introduces a new failure mode, because overloads have no runtime effect: at import time
Python binds the final definition and discards the stubs.

## Testing

The existing suite is the regression evidence, and it is substantial: `tests/test_cross_repo.py`,
`tests/test_cross_repo_futures.py`, and `tests/test_cross_repo_expanded.py` already exercise both
arms — `test_cross_repo_futures.py:109` and `:113` call `cross_repo_assessments` with
`include_warnings=False` and `=True` respectively, and `:242` unpacks the tuple form.

Because the change is static-only, runtime tests can prove *absence of regression* but cannot
prove the overloads are correct. That proof is the type checker, so it is the added check:

| Check | Asserts |
|---|---|
| `uv run mypy src/entirecontext/` | zero issues across 120 files, with the four casts deleted — this is what fails if an overload is wrong |
| `uv run pytest tests/test_cross_repo.py tests/test_cross_repo_futures.py tests/test_cross_repo_expanded.py` | both arms still return what they returned |
| `uv run pytest tests/test_mcp.py` | the four de-cast MCP tools still produce their payloads |
| `uv run ruff check .` | no unused `cast` import survives the deletion |
| full `uv run pytest -q` | 2183 passed, 1 skipped — unchanged from baseline |

No new test file is added. A test that asserts a type declaration would duplicate mypy at
worse fidelity.

## Measurement

Per the Measure-First principle, the measurement infrastructure already exists and was
exercised before this spec was written: `mypy` is in CI and its pre-change reading is
recorded in Assumptions (0 issues, 120 files), as is the spike that produced the same reading
with two functions converted and two casts deleted. The metric that must move is the cast
count, from 4 to 0, with mypy holding at 0.

## Risks

| Risk | Mitigation |
|---|---|
| An overload's declared shape does not match the body's actual return, so callers get a wrong type that mypy trusts | mypy checks the implementation signature against every overload; a mismatch is an error, not a silent acceptance. The four shapes were read from the existing annotations rather than inferred |
| Tightening return types surfaces previously-masked errors at the twelve non-cast call sites | Measured for all three shapes, each spiked alone and reverted: `list[dict]` (`cross_repo_search`), `dict \| None` (`cross_repo_rewind`), and bare `dict` (`cross_repo_assessment_trends`, whose two call sites at `cli/futures_cmds.py:450` and `mcp/tools/futures.py:178` unpack without a cast). mypy stayed at zero in every case |
| The keyword-only narrowing breaks an unmeasured caller | Assumptions row 4 enumerates every occurrence in `src/` and `tests/`; all are keyword form. A missed caller fails the type check rather than failing at runtime |
| Eleven near-identical stub pairs invite copy-paste drift between a stub and its body | The parameter lists are copied verbatim from each body with defaults replaced by `...`; mypy rejects a stub whose parameters do not match the implementation |
| The diff is large and mechanical, which makes review fatigue likely | Split into units by shape group, so a reviewer checks one pattern per unit rather than eleven independent changes |

## Success Criteria

**SC1: The four casts are gone.** These four are the only `cast(` calls in the package
(measured, see Assumptions), so the package-wide count is the criterion.
_Measured by:_ `rg -c "\bcast\(" src/entirecontext/` returns no matches.

**SC2: No unused import survives.** `ruff check` is clean after the casts are deleted.
_Measured by:_ `uv run ruff check .` exits 0 and reports no `F401` for `typing.cast`.

**SC3: mypy remains at zero with the casts removed.** The overloads carry the weight the
casts were carrying.
_Measured by:_ `uv run mypy src/entirecontext/` reports `Success: no issues found in 120
source files`.

**SC4: All eleven functions are converted.** No `include_warnings` function is left declaring
the bare union to its callers.
_Measured by:_ `rg -c "^@overload" src/entirecontext/core/cross_repo.py` returns 22, and
`rg -n "include_warnings: Literal" src/entirecontext/core/cross_repo.py` returns 22 lines
(one `Literal[False]` and one `Literal[True]` per function).

**SC5: Runtime behavior is unchanged.** The full suite matches the pre-change baseline
exactly.
_Measured by:_ `uv run pytest -q` reports 2183 passed, 1 skipped — the same counts recorded in
Assumptions before any edit.

**SC6: The overloads are actually load-bearing.** Reverting any single overload pair
reintroduces a type error at its call site rather than being inert.
_Measured by:_ a non-vacuity check during implementation — remove one converted function's
overloads, confirm `mypy` reports an error at the corresponding de-cast call site, restore.
Recorded in the ledger with the observed error text.

## Review provenance

This spec did **not** receive an independent review. The intended reviewer — a heterogeneous
model via `codex exec` — completed one pass whose report was lost to a truncated capture, and
every retry since has failed against a dead local routing proxy (`127.0.0.1:10100` returns
connection-refused). The next rung of the degradation ladder, a fresh-context reviewer
subagent, was not used because this session carries an instruction not to spawn subagents
without the user's request, and the user was away when asked.

What was done instead, per the documented fallback: a distanced self-review pass that attacked
the spec's own claims with commands rather than reasoning. It falsified two of them — the
"four distinct return shapes" count (three) and the "the `*` is the only legal ordering" claim
(Assumptions row 7) — and closed the one unmeasured shape. Both corrections are in the text
above.

This is weaker than an independent review and is recorded as such rather than glossed. The
approval gate is the place to decide whether to require one before planning.

## Open Decisions

**D1: `_return_with_warnings` keeps `-> Any`.** The helper at line 174 is the point where
type information is discarded, and seven of the eleven functions return through it. Giving it
overloads too would let the seven bodies keep a precise internal type. Deferred rather than
included: the helper's `Any` is invisible to callers once the public functions are overloaded,
so fixing it is cleanup with no external effect, and it would enlarge a diff whose main risk is
review fatigue. Recorded here so the next reader knows it was considered, not missed.
