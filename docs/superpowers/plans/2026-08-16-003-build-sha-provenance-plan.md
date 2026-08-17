# Build SHA Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development and execute this plan as one independently reviewable unit.

**Goal:** Stamp EntireContext distribution artifacts with full Git provenance and make `ec doctor` detect stale installed copies without warning in consumer repositories.

**Architecture:** Replace `uv_build` with a Hatchling custom build hook that injects a temporary `_build_provenance.py` file into wheels and source distributions. Keep a tracked unavailable-provenance fallback for editable execution. Gate `ec doctor` comparison to the EntireContext source checkout, then compare the artifact stamp with checkout HEAD.

**Tech Stack:** Python 3.12+, Hatchling custom build hooks, Typer/Rich, pytest, uv, ZIP/tar artifact inspection.

**Spec:** `docs/specs/2026-08-16-build-sha-provenance-design.md`

**ADR:** `docs/adr/0011-build-provenance-hook.md`

**EC Decision:** `edfd67be-253f-46a9-93ce-3b41f37e222e`

---

## Global Constraints

- Do not derive or change the package version from Git.
- Do not mutate tracked source files during a build.
- Do not compare the package build SHA with arbitrary consumer-repository HEADs.
- Do not auto-install, reinstall, or upgrade the executing CLI.
- Use full 40-character lowercase Git SHAs in artifacts and comparisons.
- Treat dirty or unavailable installed provenance as unverifiable, never healthy.
- Preserve provenance when a wheel is built from an sdist without `.git`.

### Task 1: Add executable provenance measurements

**Files:**
- Create: `docs/specs/2026-08-16-build-sha-provenance-design.md`
- Create: `docs/adr/0011-build-provenance-hook.md`
- Create: `docs/superpowers/plans/2026-08-16-003-build-sha-provenance-plan.md`
- Create: `tests/test_build_provenance.py`
- Modify: `tests/test_project_cmds.py`

**Interfaces:**
- Consumes: built wheel/sdist archives, checkout Git HEAD, `CliRunner` doctor output.
- Produces: binary measurements for artifact stamping, sdist preservation, stale detection, and consumer-repo isolation.

- [x] **Step 1: Pin the build-artifact contract**

Add tests that build a wheel directly from the current checkout and inspect `entirecontext/_build_provenance.py`. Require `BUILD_SHA` to equal `git rev-parse HEAD`, require `BUILD_DIRTY` to match tracked-file state, and retain representative package modules and the `ec` entry point. Build an sdist, unpack it outside `.git`, build a wheel from that source, and require the same provenance values.

Run before implementation:

```bash
uv run pytest -q tests/test_build_provenance.py
```

Authoring-time RED (2026-08-16): exit 2 during collection because `hatch_build` does not exist. The independent baseline probe built the current wheel successfully but reported `wheel_build_sha_stamp=0`; target is `1`.

- [x] **Step 2: Pin the doctor comparison boundary**

Add `TestDoctorBuildProvenance` cases for matching SHA, stale SHA, dirty build, unavailable stamp, direct checkout-source execution, and a consumer repository. The mismatch case must include both abbreviated SHAs and a reinstall instruction. The consumer case must remain free of build-provenance warnings even when the injected stamp differs.

Run the new cases before source implementation and record the failure output:

```bash
uv run pytest -q tests/test_project_cmds.py -k 'DoctorBuildProvenance'
```

Authoring-time RED (2026-08-16): exit 1; `6 failed, 77 deselected`. Every case stops because `project_cmds.BUILD_SHA` does not exist, before any new behavior can pass. The baseline installed command reported `doctor_provenance_check=0`; target is `1`.

### Task 2: Stamp wheel and source-distribution builds

**Files:**
- Create: `hatch_build.py`
- Create: `src/entirecontext/_build_provenance.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: source repository root, Git executable, an existing valid sdist stamp, Hatchling `build_data`.
- Produces: `BUILD_SHA: str | None` and `BUILD_DIRTY: bool` at `entirecontext/_build_provenance.py` in wheels and the corresponding `src/` path in sdists.

- [x] **Step 1: Switch to the extensible build backend**

Replace the `uv_build` backend requirement and configuration with bounded Hatchling configuration. Keep the static project version and source layout. Add Hatchling to the development dependency set so hook tests and no-isolation artifact probes use the same bounded backend, then refresh `uv.lock`.

- [x] **Step 2: Implement fail-closed provenance resolution**

In `hatch_build.py`, accept only exact 40-character lowercase hexadecimal SHAs. Prefer `git rev-parse HEAD`; record tracked-file dirtiness with `git status --porcelain --untracked-files=no`. If `.git` is unavailable, parse the existing fallback/stamped module and accept it only when both fields have the exact expected Python literal shapes. Otherwise leave provenance unavailable.

Do not swallow malformed stamped content as healthy. Do not invoke a shell.

- [x] **Step 3: Inject a temporary module through `force_include`**

Write the generated module in an external temporary directory so an in-tree build output cannot cause duplicate sdist members. Map it to `entirecontext/_build_provenance.py` for wheels and `src/entirecontext/_build_provenance.py` for sdists. Remove the temporary directory in `finalize()` without touching the tracked fallback module. Accept Git provenance only when the build root equals `git rev-parse --show-toplevel`; otherwise preserve the validated sdist stamp, including when the source is nested below an unrelated repository.

Run:

```bash
uv run pytest -q tests/test_build_provenance.py
```

Expected after Task 2: direct-wheel and sdist-to-wheel artifact tests pass.

### Task 3: Diagnose installed-copy drift

**Files:**
- Modify: `src/entirecontext/cli/project_cmds.py`
- Modify: `tests/test_project_cmds.py`

**Interfaces:**
- Consumes: `BUILD_SHA`, `BUILD_DIRTY`, target repository identity, running module path, `get_current_commit()`.
- Produces: zero or one operator-facing provenance warning appended to the existing `doctor()` warnings list.

- [x] **Step 1: Recognize the comparison scope**

Add a small helper that identifies the EntireContext checkout from `pyproject.toml` project metadata plus `src/entirecontext`. Add a second helper that recognizes when the running `project_cmds.py` is the target checkout's own source. Return without warning for consumer repositories or direct checkout-source execution.

- [x] **Step 2: Compare the installed artifact with checkout HEAD**

For an installed copy targeting the EntireContext checkout, warn when the checkout commit cannot be resolved, the build stamp is unavailable, the build was dirty, or the full SHAs differ. A matching clean stamp produces no provenance warning. Keep provenance warnings non-fatal, consistent with existing `doctor()` diagnostics.

Run:

```bash
uv run pytest -q tests/test_project_cmds.py -k 'DoctorBuildProvenance'
uv run pytest -q tests/test_project_cmds.py
```

Expected: the focused cases pass, then every project command test passes.

### Task 4: Close the tracked contract

**Files:**
- Modify: `README.md`
- Modify: `docs/spec.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md:360`

- [x] **Step 1: Document the operator behavior**

Explain that built distributions carry Git provenance, `ec doctor` compares it only in the EntireContext source checkout, and mismatches require reinstalling the CLI from that checkout. Do not imply normal user repositories are compared with the package source SHA.

- [x] **Step 2: Close the roadmap item**

Mark `ROADMAP.md:360` checked with the backend hook, full-SHA/dirty stamp, scoped doctor comparison, artifact tests, governing ADR, and focused test evidence. Add an Unreleased changelog entry.

### Task 5: Verify the complete changed contract

- [x] **Step 1: Run focused static and behavioral checks**

```bash
uv run ruff format hatch_build.py src/entirecontext/_build_provenance.py src/entirecontext/cli/project_cmds.py tests/test_build_provenance.py tests/test_project_cmds.py
uv run ruff check hatch_build.py src/entirecontext/_build_provenance.py src/entirecontext/cli/project_cmds.py tests/test_build_provenance.py tests/test_project_cmds.py
uv run pytest -q tests/test_build_provenance.py tests/test_project_cmds.py
```

Expected: Ruff exits 0 and both changed-source modules' complete test scopes pass.

- [x] **Step 2: Build and inspect release artifacts**

```bash
uv build
```

Inspect the wheel and sdist with Python's `zipfile` and `tarfile`: both contain `_build_provenance.py`; the stamp equals `git rev-parse HEAD`; a wheel rebuilt from the unpacked sdist preserves it. The build leaves no tracked or untracked provenance file behind.

Observed 2026-08-16: `uv build` produced the wheel and sdist; each contained exactly one generated provenance member with SHA `f3a8453160aacef86f98b8f29aaab3b07bc0edee`, `BUILD_DIRTY = True`, and identical contents. The wheel retained the runtime module and `ec` entry point; the tracked fallback remained unchanged. The declared focused verification reported 96 passed; adding the hook end-to-end module reported 100 passed. The full repository suite reported 2227 passed, 1 skipped; Ruff and mypy passed.

- [x] **Step 3: Run documentation and traceability checks**

Run the repository's active-reference validator from the governing specification-policy Plan against the committed checkout, then run `git diff --check` before commit.

Observed 2026-08-16 on the staged checkout: `81 checked; Markdown destinations: 8; bold references: 12; labels: 28`. The specification name-status was one `A` entry and no `D`, `M`, or `R`; `git diff --cached --check` exited 0. Repeat the same validator against `HEAD` after commit.

## Assumption Recheck

The authoring-time artifact probe reported `wheel_build_sha_stamp=0`; installed `ec doctor` reported `doctor_provenance_check=0`. The current backend is `uv_build>=0.10.2,<0.12.0`, and Astral's current build-backend documentation explicitly recommends Hatchling when build scripts are required. Hatchling's current build-hook contract supports temporary external paths through `build_data["force_include"]`. No contradiction remains.

## Scenario Coverage Map

| Scenario | Unit chain | Observable evidence |
|---|---|---|
| S1: stale installed tool | Task 1 Step 2 -> Task 3 | stale case emits SHA mismatch plus reinstall guidance |
| S2: matching installed build | Task 1 Step 2 -> Task 2 -> Task 3 | built SHA equals HEAD and doctor emits no provenance warning |
| S3: consumer repository | Task 1 Step 2 -> Task 3 Step 1 | mismatched injected stamp produces no provenance warning |
| S4: sdist preservation | Task 1 Step 1 -> Task 2 | wheels rebuilt outside Git or below an unrelated repository retain the sdist stamp; an in-tree sdist output contains one stamp |

## Carry-Forward Audit

- `ROADMAP.md:360` is the implemented target and closes in Task 4.
- `ROADMAP.md:354` fires by file overlap because this Plan changes `project_cmds.py`, but disable cleanup is independent and remains in the ordered follow-up work.
- `ROADMAP.md:359` fires because this Plan derives tests from a Spec. The scenario map and named-test list show no merged or dropped Spec test; the durable automated planning guard remains separate work.
- `ROADMAP.md:362` fires because this Plan declares verification commands. Every command is executed once during authoring: baseline artifact/doctor probes recorded 0/1, new-test commands record their RED states after test authoring, and the final commands are rerun after implementation. The durable enforcement guard remains separate work.
- `ROADMAP.md:363` does not fire: the build-backend edit changes artifact generation, not the public typing contract or `py.typed` policy.
- Fresh 2026-08-16 telemetry remains `maturity=64`, `applied_context_rate=1%`, `lesson_reuse_rate=20%`, and enriched assessment `n=24`; those open measurement rows retain current wording and status.

## Deferred to Follow-Up Work

- Symmetric `ec disable` MCP/Codex cleanup (`ROADMAP.md:354`).
- Durable Plan-vs-Spec test-enumeration enforcement (`ROADMAP.md:359`).
- Durable pre-execution enforcement for Plan verification commands (`ROADMAP.md:362`).
- Deliberate `py.typed` policy (`ROADMAP.md:363`).
