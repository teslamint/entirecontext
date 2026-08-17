---
title: Build SHA Provenance
status: approved
date: 2026-08-16
schema: spec/v1
---

# Build SHA Provenance Design

_Created 2026-08-16._

## Overview

Make same-version drift between the EntireContext checkout and an installed `ec` executable observable. Distribution builds carry the source Git commit and dirty-state provenance; `ec doctor` compares that provenance with the current checkout when, and only when, it is diagnosing the EntireContext source repository.

## User Scenarios

### S1: Detect a stale installed tool

A contributor runs a globally installed `ec doctor` in the EntireContext checkout after the checkout advances. The command warns with the installed build SHA and current checkout SHA and tells the contributor to reinstall from the checkout.

### S2: Accept a matching installed build

A contributor builds and installs `ec` from the current clean EntireContext commit. `ec doctor` finds the same full SHA and emits no provenance warning.

### S3: Diagnose a normal consumer repository

A user runs `ec doctor` in a different project that uses EntireContext. The command does not compare EntireContext's build SHA with that unrelated project's HEAD and emits no provenance warning.

### S4: Preserve provenance through an sdist

A source distribution built from a Git checkout carries the build provenance file. A wheel subsequently built from that sdist, where `.git` is absent, preserves the original SHA and dirty-state value.

## Scope

### In

- Replace `uv_build` with Hatchling because the package now requires a build-time hook.
- Inject `BUILD_SHA` and `BUILD_DIRTY` into wheel and source-distribution artifacts without modifying tracked source files during a build.
- Preserve a stamped source-distribution value when building a wheel without `.git` metadata.
- Add an EntireContext-checkout-only provenance check to `ec doctor`.
- Warn for mismatched, dirty, or unavailable installed-build provenance in the EntireContext checkout.
- Keep consumer-repository diagnostics unchanged.
- Close `ROADMAP.md:360` and document the operator-facing check.

### Out

- Making hooks execute the checkout via `uv run ec`.
- Comparing package versions instead of commit provenance.
- Reinstalling or upgrading the user's installed tool automatically.
- Refusing builds from dirty worktrees.
- Adding provenance checks to normal consumer repositories.
- Changing release versioning or deriving `project.version` from Git.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| Current wheels contain no build provenance module. | `uv build --wheel --out-dir <tmp>` plus ZIP member inspection | 2026-08-16 | `wheel_build_sha_stamp=0`; target is `1`. | authoring-time baseline |
| Current `ec doctor` has no provenance check. | installed `ec doctor` in this checkout | 2026-08-16 | `doctor_provenance_check=0`; target is `1`. | authoring-time baseline |
| Version comparison cannot detect the incident class. | `docs/retros/2026-08-12-init-installs-hooks-retro.md:T14-T15` | 2026-08-16 | stale installed and checkout copies both reported `0.14.0`. | retrospective evidence |
| `uv_build` does not support build scripts. | Astral uv build-backend documentation | 2026-08-16 | the official guidance says to use Hatchling when build scripts are required. | <https://docs.astral.sh/uv/concepts/build-backend/> |
| Hatchling custom hooks may add a generated file through `build_data["force_include"]`. | Hatch build-hook reference | 2026-08-16 | `initialize()` may modify build data; `force_include` maps an external generated path into an artifact. | <https://hatch.pypa.io/1.18/plugins/build-hook/reference/> |

## Architecture

EC decision `edfd67be-253f-46a9-93ce-3b41f37e222e` selects Hatchling's custom build hook over a wrapper around `uv_build`.

`hatch_build.py` uses Git provenance only when `git rev-parse --show-toplevel` resolves to the build root itself, then resolves the source commit with `git rev-parse HEAD` and records whether tracked files differ from that commit. This prevents an unpacked sdist below an unrelated repository from inheriting the parent repository's SHA. The hook writes a temporary Python module outside the project tree, and `force_include` places that module at `entirecontext/_build_provenance.py` in wheels and `src/entirecontext/_build_provenance.py` in source distributions. A tracked fallback module contains `BUILD_SHA = None` and `BUILD_DIRTY = False` for editable/source execution. When the build root is not itself a Git repository, the hook reads a valid previously stamped module so wheels built from sdists preserve the original provenance.

`ec doctor` first recognizes whether its target repository is the EntireContext source checkout. Normal consumer repositories skip the check. Executing the target checkout's own source is authoritative and also skips the installed-copy comparison. Otherwise, the command compares the stamped full SHA with `core.git_utils.get_current_commit(repo_path)` and warns when the stamp is missing, dirty, or different.

## Testing

1. Unit-test SHA resolution from Git for clean, tracked-dirty, untracked-only, and linked-worktree roots; test stamped-sdist fallback, ambiguous or invalid fallback rejection, unborn-repository failure, and generated module contents.
2. Unit-test `ec doctor` for matching, mismatched, dirty, unavailable, checkout-source, and consumer-repository cases.
3. Run the complete `tests/test_project_cmds.py` module because `doctor` is modified.
4. Build a wheel from the checkout and assert its provenance module contains `git rev-parse HEAD`.
5. Build an sdist, build wheels from the unpacked sdist both outside Git and below an unrelated Git working tree, and assert both wheels preserve the original stamp. Build an sdist with its output directory inside the source root and assert the archive contains exactly one provenance member.
6. Run the release build command and inspect both artifacts.

## Risks

- **False warning in consumer repositories:** comparing unrelated repository SHAs would make the feature unusable. Mitigation: gate on the target checkout's project identity and source layout.
- **Unverifiable dirty build:** a commit SHA alone would overstate what source was packaged. Mitigation: stamp and warn on tracked worktree dirtiness.
- **Lost or overwritten sdist provenance:** a downstream wheel build may not have `.git` or may be nested below an unrelated repository. Mitigation: use Git only when the build root is the repository top level, then reuse the validated sdist stamp.
- **Build-backend regression:** changing backends can alter artifact contents. Mitigation: build and inspect both wheel and sdist, run focused tests, and retain static project versioning.
- **Source-tree mutation or duplicate archive members:** generating under `src/` can race or dirty the checkout, while generating under an in-tree output directory can duplicate the forced sdist member. Mitigation: generate in an external temporary directory and inject exactly one member through `force_include`.

## Success Criteria

1. A wheel built from the checkout contains `entirecontext/_build_provenance.py` with `BUILD_SHA` equal to `git rev-parse HEAD`.
   - **Measured by**: `test_built_wheel_contains_current_git_sha` and `test_built_wheel_preserves_runtime_package_and_entry_point` pass, and direct artifact inspection confirms the stamp and package contents.
2. A wheel built from the generated sdist preserves the same full SHA without a `.git` directory and when the unpacked source is nested below an unrelated Git repository.
   - **Measured by**: `test_sdist_to_wheel_preserves_git_sha`, `test_sdist_to_wheel_ignores_enclosing_repository`, and `test_sdist_build_inside_source_tree_contains_one_stamp` pass.
3. `ec doctor` warns when the installed stamp differs from the EntireContext checkout HEAD and emits no provenance warning when they match.
   - **Measured by**: `test_doctor_warns_for_stale_build_sha` and `test_doctor_accepts_matching_build_sha` pass.
4. Dirty or unavailable installed provenance is never reported as healthy in the EntireContext checkout.
   - **Measured by**: dedicated dirty and unavailable provenance tests pass.
5. Consumer repositories receive no unrelated build-SHA warning.
   - **Measured by**: `test_doctor_skips_build_sha_check_for_consumer_repo` passes.
6. Existing project diagnostics remain green.
   - **Measured by**: `uv run pytest -q tests/test_project_cmds.py tests/test_build_provenance.py` and focused Ruff checks exit 0.

## Open Decisions

None. The user approved continuing the ordered `ROADMAP.md` work on 2026-08-16. The durable backend and comparison-scope decision is recorded as EC decision `edfd67be-253f-46a9-93ce-3b41f37e222e` and companion ADR 0011.
