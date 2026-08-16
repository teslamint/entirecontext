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
set -euo pipefail

python - <<'PY'
from pathlib import Path
import os
import re
import subprocess

assert "docs/specs/" in Path("AGENTS.md").read_text()
assert "docs/superpowers/specs/" not in Path("AGENTS.md").read_text()
adr = Path("docs/adr/0010-spec-directory-policy.md").read_text()
assert "**Status:** accepted" in adr
assert "0aaa4fa6-6974-4dcf-bf2f-e1ce7d44308b" in adr
checked = 0
markdown_links = 0
bold_references = 0
labels = set()
structural_labels = {
    "create",
    "modify",
    "test",
    "interfaces",
    "consumes",
    "produces",
    "measured by",
    "branch",
    "base",
    "feature",
}
label_pattern = re.compile(
    r"(?i)(?P<bold>\*\*)?(?P<label>\b[A-Za-z][A-Za-z _-]*?)(?:\*\*)?\s*:\s*(?P<value>.*)$"
)
docs_target_pattern = re.compile(
    r"(?<![\w/])(?P<target>docs/[A-Za-z0-9._/-]*\.md)(?![\w/-])"
)
markdown_link_pattern = re.compile(
    r"\[[^\]]*?docs/[^\s`\])]+[^\]]*\]\((?P<link>[^)\s]+)\)"
)
reference_link_pattern = re.compile(
    r"\[[^\]]*?docs/[^\s`\])]+[^\]]*\]\[(?P<reference>[^\]]+)\]"
)
reference_definition_pattern = re.compile(
    r"^\s*\[(?P<reference>[^\]]+)\]:\s*(?:<(?P<angle>[^>]+)>|(?P<bare>\S+))"
)
fence_pattern = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
checkout = Path.cwd().resolve()


def normalized_reference(reference: str) -> str:
    return " ".join(reference.split()).casefold()


def assert_checkout_file(candidate: Path, description: str) -> None:
    resolved = candidate.resolve()
    assert resolved.is_relative_to(checkout), (
        f"target escapes checkout: {description} from {candidate}"
    )
    assert resolved.is_file(), f"missing target file {description} from {candidate}"


markdown_paths = [
    Path(os.fsdecode(raw_path))
    for raw_path in subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    if raw_path
]
companion_adr = Path("docs/adr/0010-spec-directory-policy.md")
assert_checkout_file(companion_adr, str(companion_adr))
if companion_adr not in markdown_paths:
    markdown_paths.append(companion_adr)
for path in markdown_paths:
    if ".release-loop/archive/" in path.as_posix():
        continue
    active_lines = []
    active_fence = None
    for line in path.read_text().splitlines():
        fence = fence_pattern.match(line)
        if fence:
            marker = fence.group("fence")[0]
            if active_fence is None:
                active_fence = marker
            elif marker == active_fence:
                active_fence = None
            continue
        if active_fence is None:
            active_lines.append(line)
    references = {}
    for line in active_lines:
        definition = reference_definition_pattern.match(line)
        if definition:
            target = definition.group("angle") or definition.group("bare")
            references[normalized_reference(definition.group("reference"))] = target
    for line in active_lines:
        for field in label_pattern.finditer(line):
            label = field.group("label").strip().lower()
            if label in structural_labels:
                continue
            value = field.group("value")
            for target_match in docs_target_pattern.finditer(value):
                target = target_match.group("target")
                checked += 1
                labels.add(label)
                assert_checkout_file(Path(target), target)
                if field.group("bold"):
                    bold_references += 1
            for link_match in markdown_link_pattern.finditer(value):
                markdown_links += 1
                link_target = link_match.group("link").split("#", 1)[0]
                if link_target.startswith(("http://", "https://")):
                    continue
                assert_checkout_file(path.parent / link_target, link_target)
            for link_match in reference_link_pattern.finditer(value):
                markdown_links += 1
                reference = normalized_reference(link_match.group("reference"))
                assert reference in references, (
                    f"missing reference-style link definition [{reference}] from {path}"
                )
                link_target = references[reference].split("#", 1)[0]
                if link_target.startswith(("http://", "https://")):
                    continue
                assert_checkout_file(path.parent / link_target, link_target)
assert checked >= 10, f"unexpectedly low traceability coverage: {checked}"
assert markdown_links >= 4, f"unexpectedly low Markdown-link coverage: {markdown_links}"
assert bold_references >= 3, f"unexpectedly low bold-reference coverage: {bold_references}"
assert {
    "spec",
    "plan",
    "deviation",
    "adr",
    "approved matrix",
    "previous retro",
    "current reference",
} <= labels, f"missing traceability labels: {labels}"
print(
    f"active traceability targets resolve: {checked} checked; "
    f"Markdown destinations: {markdown_links}; bold references: {bold_references}; "
    f"labels: {len(labels)}"
)
PY

name_status=$(git diff HEAD --name-status -- docs/specs docs/superpowers/specs)
printf '%s\n' "$name_status"
if printf '%s\n' "$name_status" | grep -Eq '^[DMR]'; then
  echo "Specification content edit, rename, or delete detected" >&2
  exit 1
fi
```

Expected: the Python check prints `active traceability targets resolve:` and meets every asserted coverage floor. This retro closure reports `74 checked; Markdown destinations: 5; bold references: 9; labels: 27`; counts may increase as current tracked documents grow. The name-status output contains no `D`, `M`, or `R` entry.

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
