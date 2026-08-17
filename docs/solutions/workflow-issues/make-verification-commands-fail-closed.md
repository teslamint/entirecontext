---
module: specification-governance
date: 2026-08-16
problem_type: workflow_issue
component: verification-command
severity: high
applies_when:
  - "A verification command gates acceptance, merge, or release decisions"
  - "A shell block contains multiple checks whose exit statuses can mask earlier failures"
  - "A validator must reject malformed files, wrong targets, or boundary-breaking matches"
  - "A policy check relies on regexes or textual assertions"
  - "A verification contract includes rejection paths as well as a valid baseline"
tags:
  - fail-closed
  - mutation-testing
  - verification-commands
  - rejection-paths
  - shell-safety
  - policy-validation
---

# Make Verification Commands Fail Closed

## Context

PR #224's implementation plan included a shell verification block intended to confirm the active Specification path, the companion ADR, and traceability targets. At the reviewed head `8f5baac`, the block asserted that the ADR contained `Status: accepted`, while `docs/adr/0010-spec-directory-policy.md` used the Markdown form `**Status:** accepted`. The assertion therefore raised `AssertionError` before traceability targets were checked ([PR #224 comment 3791367898](https://github.com/teslamint/entirecontext/pull/224#discussion_r3791367898)).

The same block used the raw regex `r"(?:origin|Spec|spec):[` ]+([^`\\s)]+)"`. In its character class, `\\s` excluded a literal `s`, so captures stopped before a complete `docs/...` path. Against the reviewed tree it found 27 matches but zero targets beginning with `docs/`; the script could print success without exercising `Path(target).exists()` ([PR #224 comment 3791367902](https://github.com/teslamint/entirecontext/pull/224#discussion_r3791367902)).

Verbatim execution of the block emitted the `AssertionError`, but the shell still returned status 0: it did not enable fail-fast behavior, and the later successful `git diff --name-status` became the block's final status. PR #225 recorded this masking behavior in [comment 3791532800](https://github.com/teslamint/entirecontext/pull/225#discussion_r3791532800) and replaced the validator in merge commit `72e0aa5`. The original policy PR had already merged as `7e07ccb`.

Evidence wording matters: `8f5baac` was the reviewed PR #224 head whose tree contained the defective plan. That commit itself changed only Specification formatting; it did not introduce the plan assertion.

## Guidance

Treat a verification command as a small program with two independent contracts:

1. **Exercise the intended success path.** Match the artifact's real syntax, validate files rather than merely existing paths, measure coverage, and reject results below the expected floor. A regex match count does not prove the guarded branch ran.
2. **Propagate every failure.** Start multi-command Bash blocks with `set -euo pipefail`, or explicitly capture and return each command's status. A traceback is not sufficient evidence when the enclosing command exits 0.
3. **Make negative policy executable.** If the contract prohibits edits, deletions, renames, missing files, or checkout escapes, make each prohibited state produce nonzero status.
4. **Prove rejection paths with mutations.** Temporarily introduce one controlled violation at a time, run the exact published command, confirm nonzero status and the expected diagnostic, then restore the checkout. A clean-tree pass proves only the acceptance path.
5. **Bound and reproduce validation inputs.** The repaired validator enumerates tracked Markdown, explicitly includes the newly created companion ADR, excludes archived evidence and fenced examples, resolves Markdown destinations relative to their containing file, requires targets to be files, and rejects paths outside the checkout (`docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md:74-225`).

### Prevention checklist

- [ ] Run the exact command block users or automation will copy, not an equivalent fragment.
- [ ] Confirm the enclosing shell returns nonzero when an inner command fails.
- [ ] Use `set -euo pipefail` or explicit status propagation for multi-command blocks.
- [ ] Match canonical artifact syntax, including Markdown punctuation and link forms.
- [ ] Assert that the intended branch executed with coverage counts or required labels.
- [ ] Require file targets with `is_file()`, not only `exists()`.
- [ ] Normalize local paths and reject targets outside the checkout.
- [ ] Cover staged and unstaged states when policy applies to both.
- [ ] Mutate every prohibited state and confirm the exact command rejects it.
- [ ] Restore each mutation and rerun the clean success path.
- [ ] Record both exit status and observable output in PR evidence.

## Why This Matters

Automation consumes exit status, not reviewer intent. A command that prints an error but exits 0 can satisfy CI, a merge gate, or a copied verification recipe while proving nothing. Likewise, a parser can report success when matching logic never reaches the validation branch. These are distinct failure modes: fail-open shell composition masks a real inner failure, while vacuous matching makes the inner check ineffective even when it exits successfully.

Positive-only verification cannot distinguish a working guard from a guard that accepts everything. Mutation probes close that gap by showing that known-invalid inputs are rejected. PR #225 established both sides: the final clean command printed `active traceability targets resolve: 68 checked; Markdown destinations: 5; bold references: 8; labels: 25`, while an intentional Python assertion failure exited 1, a simulated Specification modification exited 1, and broken reference-style and checkout-escaping links exited nonzero ([PR #225](https://github.com/teslamint/entirecontext/pull/225)).

## When to Apply

Apply this pattern whenever:

- a plan or runbook publishes a multi-command shell verification block;
- CI or a merge decision relies on that block's status;
- regexes or parsers discover files, links, labels, or policy markers;
- success depends on a minimum amount of coverage rather than one example;
- the contract includes negative constraints such as "must not modify," "must not escape," or "must reject missing targets";
- later commands can run after an earlier assertion, test, or validation step;
- a validator is changed in response to a false positive.

## Examples

### Fail-open composition

```bash
python - <<'PY'
assert "Status: accepted" in adr
PY

git diff --name-status -- docs/specs docs/superpowers/specs
```

The Python process can fail while the final `git diff` succeeds, leaving the whole block with status 0.

### Fail-closed composition

```bash
set -euo pipefail

python - <<'PY'
assert "**Status:** accepted" in adr
# Perform target, coverage, file, and checkout-boundary assertions.
PY

name_status=$(git diff HEAD --name-status -- docs/specs docs/superpowers/specs)
if printf '%s\n' "$name_status" | grep -Eq '^[DMR]'; then
  echo "Specification content edit, rename, or delete detected" >&2
  exit 1
fi
```

Here, a Python assertion stops the block immediately, and the shell guard explicitly rejects every prohibited Git status.

### Mutation evidence matrix

| Mutation | Required observation |
|---|---|
| Force a Python assertion to fail | Exact block exits nonzero; later commands do not mask it |
| Modify a protected Specification | `M` is reported and the block exits 1 |
| Delete or rename a protected Specification | `D` or `R` is reported and the block exits 1 |
| Break an inline or reference-style Markdown destination | Validator exits nonzero |
| Point a local destination outside the checkout | Validator exits nonzero |
| Restore all mutations | Exact block returns 0 with the expected coverage counts |
