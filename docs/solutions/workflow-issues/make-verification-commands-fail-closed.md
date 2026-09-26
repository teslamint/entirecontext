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

The implementation plan for pull request (PR) #224 included a shell verification block.
The block aimed to confirm the active Specification path, the companion architecture decision record (ADR), and traceability targets.
At the reviewed head `8f5baac`, the block asserted that the ADR contained `Status: accepted`.
However, `docs/adr/0010-spec-directory-policy.md` used the Markdown form `**Status:** accepted`.
The assertion therefore raised `AssertionError` before the block checked traceability targets ([PR #224 comment 3791367898](https://github.com/teslamint/entirecontext/pull/224#discussion_r3791367898)).

The same block used this raw regular expression (regex): `r"(?:origin|Spec|spec):[` ]+([^`\\s)]+)"`.
Its character class excluded a literal `s` with `\\s`, so each capture stopped before a complete `docs/...` path.
Against the reviewed tree, the block found 27 matches.
It found zero targets beginning with `docs/`.
Therefore, the script could print success without calling `Path(target).exists()` ([PR #224 comment 3791367902](https://github.com/teslamint/entirecontext/pull/224#discussion_r3791367902)).

When the block ran verbatim, it emitted `AssertionError`.
The shell still returned status 0.
The block did not enable fail-fast behavior.
The later successful `git diff --name-status` command set the block's final status to 0.

PR #225 recorded this masking behavior in [comment 3791532800](https://github.com/teslamint/entirecontext/pull/225#discussion_r3791532800).
It replaced the validator in merge commit `72e0aa5`.
The original policy PR had already merged as `7e07ccb`.

Use precise evidence wording.
`8f5baac` was the reviewed head of PR #224.
Its tree contained the defective plan.
That commit changed only Specification formatting.
It did not introduce the plan assertion.

## Guidance

Treat a verification command as a small program with two independent contracts:

1. **Exercise the intended success path.** Match the artifact's real syntax. Validate files, not just paths. Measure coverage. Reject results below the expected floor. A regex match count does not prove that the guarded branch ran.
2. **Propagate every failure.** Start multi-command Bash blocks with `set -euo pipefail`. Alternatively, capture and return each command's status explicitly. A traceback does not prove that the enclosing command exits nonzero.
3. **Make negative policy executable.** Make each prohibited state produce nonzero status when the contract forbids edits, deletions, renames, missing files, or checkout escapes.
4. **Prove rejection paths with mutations.** Temporarily introduce one controlled violation at a time. Run the exact published command. Confirm a nonzero status and the expected diagnostic. Restore the checkout. A clean-tree pass proves only the acceptance path.
5. **Bound the validation inputs. Reproduce them.** The repaired validator enumerates tracked Markdown and includes the newly created companion ADR. It excludes archived evidence and fenced examples, and it resolves Markdown destinations relative to their containing file. It requires each target to be a file. It rejects paths outside the checkout (`docs/superpowers/plans/2026-08-16-001-docs-spec-directory-policy-plan.md:74-225`).

### Prevention checklist

- [ ] Run the exact command block users or automation will copy, not an equivalent fragment.
- [ ] Confirm the enclosing shell returns nonzero when an inner command fails.
- [ ] Use `set -euo pipefail` or explicit status propagation for multi-command blocks.
- [ ] Match canonical artifact syntax, including Markdown punctuation and link forms.
- [ ] Assert that the intended branch executed with coverage counts or required labels.
- [ ] Require each target to be a file with `is_file()`. Do not rely on `exists()` alone.
- [ ] Normalize local paths. Reject targets outside the checkout.
- [ ] Cover staged and unstaged states when the policy applies to both.
- [ ] Mutate each prohibited state. Confirm that the exact command rejects it.
- [ ] Restore each mutation. Rerun the clean success path.
- [ ] Record both the exit status and the observable output in PR evidence.

## Why This Matters

Automation consumes the exit status, not reviewer intent.
A command can print an error and still exit 0.
The command can satisfy continuous integration (CI), a merge gate, or a copied verification recipe.
The command proves nothing.

A parser can also report success without reaching the validation branch.
The two failures have different causes.
Fail-open shell composition masks an inner failure.
Vacuous matches make the inner check ineffective, even when the check exits successfully.

Positive-only verification cannot distinguish a guard that works from a guard that accepts everything.
Mutation probes close that gap.
They show that the guard rejects known-invalid inputs.
PR #225 established both sides.
The final clean command printed `active traceability targets resolve: 68 checked; Markdown destinations: 5; bold references: 8; labels: 25`.
An intentional Python assertion failure exited 1.
A simulated Specification modification exited 1.
Broken reference-style links and links that point outside the checkout exited nonzero ([PR #225](https://github.com/teslamint/entirecontext/pull/225)).

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

The Python process can fail, but the final `git diff` command can succeed. In that case, the whole block returns status 0.

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

A Python assertion stops the block immediately. The shell guard rejects every prohibited Git status.

### Mutation evidence matrix

| Mutation | Required observation |
|---|---|
| Force a Python assertion to fail | Exact block exits nonzero; later commands do not mask it |
| Modify a protected Specification | `M` is reported and the block exits 1 |
| Delete or rename a protected Specification | `D` or `R` is reported and the block exits 1 |
| Break an inline or reference-style Markdown destination | Validator exits nonzero |
| Point a local destination outside the checkout | Validator exits nonzero |
| Restore all mutations | Exact block returns 0 with the expected coverage counts |
