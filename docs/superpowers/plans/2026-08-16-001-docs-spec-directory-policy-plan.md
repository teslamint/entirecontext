# Spec Directory Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docs/specs/` the sole active Specification path and close the registered roadmap drift without rewriting historical release evidence.

**Architecture:** Add a companion ADR recording why `docs/specs/` is the sole active path, then update the repository policy, roadmap, and current traceability pointers in place. Keep all Specification files where they already exist; distinguish current policy/reference files from `.release-loop/archive/` evidence. Validate the resulting graph with repository-relative path checks rather than runtime code changes.

**Tech Stack:** Markdown, Git path inspection, POSIX shell, Python standard library for deterministic reference validation.

**Spec:** `docs/specs/2026-08-16-spec-directory-policy-design.md`

**Decision:** EC decision `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`; companion ADR `docs/adr/0010-spec-directory-policy.md`

## Global Constraints

- New active Specifications use `docs/specs/` only.
- Do not move or rename existing Specification files.
- Do not rewrite `.release-loop/archive/` evidence.
- Do not change runtime modules, schemas, CLI behavior, or public APIs.
- Preserve links to older Specifications under `docs/superpowers/specs/` when those files genuinely remain there.
- Every active traceability path must resolve to an existing file.

---

### Task 1: Align policy and current traceability references

**Files:**
- Create: `docs/adr/0010-spec-directory-policy.md`
- Modify: `AGENTS.md:20`
- Modify: `docs/adr/0005-init-installs-integrations.md:91`
- Modify: `docs/adr/0008-overload-include-warnings-keyword-only.md:57`
- Modify: `docs/deviations/2026-08-11-git-hook-installation-safety.md:11`
- Modify: `docs/plans/2026-07-19-v0.15.0-self-archaeology-blame-plan.md:4`
- Modify: `docs/plans/2026-07-21-001-fix-blame-sha-lookup-complexity-plan.md:8`
- Modify: `docs/plans/2026-07-29-001-refactor-consolidate-pr-enrichment-plan.md:9`
- Modify: `docs/plans/2026-08-11-001-feat-init-installs-hooks-plan.md:9,68,185`
- Modify: `docs/plans/2026-08-12-001-refactor-cross-repo-overload-plan.md:9,99,394-395`
- Modify: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md:173`
- Modify: `ROADMAP.md:355`
- Test: repository path validation commands below

**Interfaces:**
- Consumes: existing Specification files under `docs/specs/` and `docs/superpowers/specs/`.
- Produces: one active policy path and current traceability references that resolve without moving files.

- [ ] **Step 1: Write the failing reference check**

Run this before editing to capture the current drift:

```bash
python - <<'PY'
from pathlib import Path
text = Path("AGENTS.md").read_text()
assert "docs/superpowers/specs/" in text
assert "docs/specs/" not in text
print("baseline policy drift reproduced")
PY
```

Expected: PASS with `baseline policy drift reproduced`.

- [ ] **Step 2: Create the companion ADR and update current references**

Create `docs/adr/0010-spec-directory-policy.md` with status `accepted`, the date, EC decision `0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b`, the rejected move/dual-path alternatives, and the consequences of preserving historical paths. Change `AGENTS.md` to state `Spec (`docs/specs/`) → ADR...`. Update current ADR, deviation, and Plan links whose target files are under `docs/specs/`. Do not change links to the nine older Specifications that genuinely remain under `docs/superpowers/specs/`. Update the init and cross-repo Plan prose so their path examples and verification commands describe the official active directory without changing their historical execution claims.

- [ ] **Step 3: Close the roadmap row with the exact decision**

Replace the unchecked `ROADMAP.md:355` entry with a checked entry stating that `docs/specs/` is now the official active path, existing files were not moved, and historical archive paths remain preserved. Keep the PR provenance reference and P2 classification in the entry.

- [ ] **Step 4: Run the focused reference checks**

```bash
python - <<'PY'
from pathlib import Path
import re

assert "docs/specs/" in Path("AGENTS.md").read_text()
assert "docs/superpowers/specs/" not in Path("AGENTS.md").read_text()
adr = Path("docs/adr/0010-spec-directory-policy.md").read_text()
assert "Status: accepted" in adr
assert "0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b" in adr
for path in Path("docs").rglob("*.md"):
    if ".release-loop/archive" in str(path):
        continue
    text = path.read_text()
    for match in re.finditer(r"(?:origin|Spec|spec):[` ]+([^`\\s)]+)", text):
        target = match.group(1).rstrip("`;")
        if target.startswith("docs/"):
            assert Path(target).exists(), f"missing target {target} from {path}"
print("active traceability targets resolve")
PY

git diff --name-status -- docs/specs docs/superpowers/specs
```

Expected: the Python check prints `active traceability targets resolve`; the name-status output is empty.
- [ ] **Step 5: Run documentation checks and inspect the full diff**

Run the repository-configured documentation/lint checks if present, then:

```bash
git diff --check
git diff -- AGENTS.md ROADMAP.md docs/adr docs/deviations docs/plans
```

Expected: no whitespace errors, no Specification rename/delete, and no content changes outside policy/reference wording.

- [ ] **Step 6: Commit the coherent documentation change**

```bash
git add AGENTS.md ROADMAP.md docs/adr/0010-spec-directory-policy.md docs/adr docs/deviations docs/plans
git commit -m "docs(roadmap): align active specification path"
```

Expected: one commit containing the companion ADR, active policy, traceability references, and roadmap closure.

## Verification Matrix

| Spec criterion | Plan evidence |
|---|---|
| Sole active path | Task 1, Steps 2 and 4 |
| Active pointers resolve | Task 1, Step 4 |
| No files moved | Task 1, Steps 4 and 5 |
| Roadmap item closed | Task 1, Step 3 |
| Historical evidence preserved | Task 1, Steps 2 and 5 |

## Plan Self-Review

- **Spec coverage:** all five Success Criteria map to Task 1 and the verification matrix.
- **Completeness scan:** no unfinished or unspecified implementation step remains.
- **Type/interface consistency:** this is documentation-only; no runtime signatures are introduced.
- **Scope:** one independently shippable policy/reference change; no implementation subsystem is included.
