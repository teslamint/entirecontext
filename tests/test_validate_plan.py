"""Executable contracts for repository Plan authoring."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_plan.py"
PLAN_RELATIVE = Path("docs/superpowers/plans/sample-plan.md")
PLAN_OWNER = f"{PLAN_RELATIVE.stem}-{hashlib.sha256(PLAN_RELATIVE.as_posix().encode()).hexdigest()[:12]}"
EVIDENCE = Path("docs/plans/evidence") / PLAN_OWNER / "check.json"


def _run(checkout: Path, operation: str, plan: Path, spec: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            operation,
            "--plan",
            str(plan.relative_to(checkout)),
            "--spec",
            str(spec.relative_to(checkout)),
        ],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _contract(
    tmp_path: Path,
    *,
    disposition_row: str = "| `test_behavior` | retained | `test_behavior` | — |",
    fence_info: str = (f"bash plan-check id=check expected-status=0 evidence={EVIDENCE.as_posix()}"),
    command: str = "set -euo pipefail\nprintf 'verified\\n'",
    extra_plan: str = "",
) -> tuple[Path, Path, Path]:
    spec = tmp_path / "docs/specs/sample-design.md"
    plan = tmp_path / PLAN_RELATIVE
    spec.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(
        """# Sample Design

## Testing

1. `test_behavior`

## Success Criteria

1. Behavior is covered.
""",
        encoding="utf-8",
    )
    plan.write_text(
        f"""# Sample Plan

**Spec:** `docs/specs/sample-design.md`

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
{disposition_row}

## Verification

```{fence_info}
{command}
```
{extra_plan}
""",
        encoding="utf-8",
    )
    return plan, spec, tmp_path / EVIDENCE


def test_validate_accepts_recorded_plan_contract(tmp_path: Path) -> None:
    plan, spec, evidence = _contract(
        tmp_path,
        extra_plan=("\n```bash implementation-only reason=fixture-setup\ntouch implementation-only-ran\n```\n"),
    )

    before_record = _run(tmp_path, "validate", plan, spec)
    record = _run(tmp_path, "record", plan, spec)
    validate = _run(tmp_path, "validate", plan, spec)

    assert before_record.returncode != 0
    assert "missing evidence" in before_record.stderr
    assert record.returncode == 0, record.stderr
    assert validate.returncode == 0, validate.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["actual_status"] == 0
    assert payload["output"] == "verified\n"
    assert payload["command"].endswith("\n")
    assert payload["recorded_at"].endswith("+00:00")
    assert not (tmp_path / "implementation-only-ran").exists()


def test_validate_rejects_missing_spec_test_disposition(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path, disposition_row="")

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "missing Spec test disposition: test_behavior" in result.stderr


def test_validate_rejects_merged_test_without_rationale(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        disposition_row="| `test_behavior` | merged | `test_combined` | — |",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "merged disposition requires rationale: test_behavior" in result.stderr


def test_validate_ignores_headings_inside_testing_fences(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path)
    spec.write_text(
        """# Sample Design

## Testing

```bash
# setup
```

1. `test_behavior`

## Success Criteria

1. Behavior is covered.
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "record", plan, spec)

    assert result.returncode == 0, result.stderr


def test_validate_ignores_target_heading_inside_earlier_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path)
    spec.write_text(
        """# Sample Design

## Example

```text
## Testing
1. `test_fake`
```

## Testing

1. `test_behavior`

## Success Criteria

1. Behavior is covered.
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "record", plan, spec)

    assert result.returncode == 0, result.stderr


def test_validate_rejects_unclosed_spec_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path)
    spec.write_text(
        """# Sample Design

## Testing

1. `test_behavior`

```text
# unclosed example

## Success Criteria

1. Behavior is covered.
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "unclosed Markdown fence with info string: text" in result.stderr


def test_validate_rejects_unclassified_shell_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path, fence_info="bash")

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "unclassified shell fence" in result.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n```bash implementation-only\nprintf 'unjustified\\n'\n```\n",
    )
    unjustified = _run(tmp_path, "validate", plan, spec)
    assert unjustified.returncode != 0
    assert "implementation-only requires exactly reason=<lowercase-slug>" in unjustified.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan=("\n1. Verify:\n    ```bash\n    touch nested-fence-ran\n    ```\n"),
    )
    indented = _run(tmp_path, "record", plan, spec)
    assert indented.returncode != 0
    assert "non-top-level shell fence is unsupported" in indented.stderr
    assert not (tmp_path / "nested-fence-ran").exists()

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan=("\n1. Verify:\n \t```shell\n \ttouch mixed-indent-fence-ran\n \t```\n"),
    )
    mixed_indent = _run(tmp_path, "record", plan, spec)
    assert mixed_indent.returncode != 0
    assert "non-top-level shell fence is unsupported" in mixed_indent.stderr
    assert not (tmp_path / "mixed-indent-fence-ran").exists()

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan=("\n> ~~~shell\n> touch blockquote-fence-ran\n> ~~~\n"),
    )
    blockquote = _run(tmp_path, "record", plan, spec)
    assert blockquote.returncode != 0
    assert "non-top-level shell fence is unsupported" in blockquote.stderr
    assert not (tmp_path / "blockquote-fence-ran").exists()

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan=("\n- ~~~shell\n  touch list-fence-ran\n  ~~~\n"),
    )
    list_container = _run(tmp_path, "record", plan, spec)
    assert list_container.returncode != 0
    assert "non-top-level shell fence is unsupported" in list_container.stderr
    assert not (tmp_path / "list-fence-ran").exists()

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan=(
            "\n- Verify:\n"
            "  ~~~shell implementation-only reason=list-continuation\n"
            "  touch continuation-fence-ran\n"
            "  ~~~\n"
        ),
    )
    continuation = _run(tmp_path, "record", plan, spec)
    assert continuation.returncode != 0
    assert "non-top-level shell fence is unsupported" in continuation.stderr
    assert not (tmp_path / "continuation-fence-ran").exists()

    plan, spec, _ = _contract(
        tmp_path,
        fence_info=(f"bash plan-check id=check expected-status=0 evidence={EVIDENCE.as_posix()} `"),
    )
    invalid_info = _run(tmp_path, "record", plan, spec)
    assert invalid_info.returncode != 0
    assert "backtick fence info string must not contain backticks" in invalid_info.stderr


def test_validate_rejects_command_in_untagged_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n```\nuv run pytest tests/test_hidden.py\n```\n",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "unclassified shell fence" in result.stderr


def test_validate_allows_non_shell_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n```python\npython = Path('example')\n```\n",
    )

    result = _run(tmp_path, "record", plan, spec)

    assert result.returncode == 0, result.stderr


def test_validate_rejects_command_in_non_shell_fence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n```text\nuv run pytest tests/test_hidden.py\n```\n",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "unclassified shell fence" in result.stderr


def test_validate_rejects_plan_check_without_fail_closed_prefix(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path, command="printf 'not fail closed\\n'")

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "must begin with set -euo pipefail" in result.stderr


def test_validate_rejects_inline_verification_command(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n1. Run `uv run pytest tests/test_hidden.py` and call it complete.\n",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "inline shell command must move to a classified fence" in result.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n1. Run: ``pytest`` and call it complete.\n",
    )
    double_backtick = _run(tmp_path, "validate", plan, spec)
    assert double_backtick.returncode != 0
    assert "inline shell command must move to a classified fence" in double_backtick.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n1. **Run:** `pytest` and call it complete.\n",
    )
    bare = _run(tmp_path, "validate", plan, spec)
    assert bare.returncode != 0
    assert "inline shell command must move to a classified fence" in bare.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n1. Run: `pytest;` and call it complete.\n",
    )
    shell_separator = _run(tmp_path, "validate", plan, spec)
    assert shell_separator.returncode != 0
    assert "inline shell command must move to a classified fence" in shell_separator.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\n1. Run: ``pytest>/tmp/hidden`` and call it complete.\n",
    )
    redirected = _run(tmp_path, "validate", plan, spec)
    assert redirected.returncode != 0
    assert "inline shell command must move to a classified fence" in redirected.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\nVerification: `>/tmp/result pytest`.\n",
    )
    leading_redirect = _run(tmp_path, "validate", plan, spec)
    assert leading_redirect.returncode != 0
    assert "inline shell command must move to a classified fence" in leading_redirect.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\nVerification: ``! pytest``.\n",
    )
    negated = _run(tmp_path, "validate", plan, spec)
    assert negated.returncode != 0
    assert "inline shell command must move to a classified fence" in negated.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan="\nVerification: `2>&1 git status`.\n",
    )
    fd_redirect = _run(tmp_path, "validate", plan, spec)
    assert fd_redirect.returncode != 0
    assert "inline shell command must move to a classified fence" in fd_redirect.stderr

    plan, spec, _ = _contract(
        tmp_path,
        extra_plan='\nRun: ``git status "`` and call it complete.\n',
    )
    malformed = _run(tmp_path, "validate", plan, spec)
    assert malformed.returncode != 0
    assert "inline shell command must move to a classified fence" in malformed.stderr


def test_validate_rejects_non_lf_plan_commands(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path)
    plan.write_bytes(plan.read_bytes().replace(b"\n", b"\r\n"))

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "Plan must use LF line endings" in result.stderr

    plan, spec, _ = _contract(
        tmp_path,
        command="\u2028set -euo pipefail\nprintf 'not normalized\\n'",
    )
    unicode_separator = _run(tmp_path, "record", plan, spec)
    assert unicode_separator.returncode != 0
    assert "must begin with set -euo pipefail" in unicode_separator.stderr


def test_validate_rejects_stale_command_evidence(tmp_path: Path) -> None:
    plan, spec, _ = _contract(tmp_path)
    assert _run(tmp_path, "record", plan, spec).returncode == 0
    side_effect = tmp_path / "must-not-exist"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("printf 'verified\\n'", f"touch {side_effect}"),
        encoding="utf-8",
    )

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "command mismatch for check" in result.stderr
    assert not side_effect.exists(), "validate must not execute a changed Plan command"


def test_validate_rejects_tampered_output_evidence(tmp_path: Path) -> None:
    plan, spec, evidence = _contract(
        tmp_path,
        command="set -euo pipefail\nprintf '\\377'",
    )
    assert _run(tmp_path, "record", plan, spec).returncode == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["output"].encode("utf-8", errors="surrogateescape") == b"\xff"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["output"] += "tampered\n"
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    result = _run(tmp_path, "validate", plan, spec)
    assert result.returncode != 0
    assert "output hash mismatch for check" in result.stderr


def test_validate_rejects_evidence_path_escape(tmp_path: Path) -> None:
    plan, spec, _ = _contract(
        tmp_path,
        fence_info="bash plan-check id=check expected-status=0 evidence=docs/plans/evidence/../../escape.json",
    )
    traversal = _run(tmp_path, "record", plan, spec)
    assert traversal.returncode != 0
    assert "evidence must stay under docs/plans/evidence" in traversal.stderr
    assert not (tmp_path / "docs/escape.json").exists()

    foreign_evidence = tmp_path / "docs/plans/evidence/other-plan/check.json"
    foreign_evidence.parent.mkdir(parents=True)
    foreign_evidence.write_text("foreign", encoding="utf-8")
    plan, spec, _ = _contract(
        tmp_path,
        fence_info="bash plan-check id=check expected-status=0 evidence=docs/plans/evidence/other-plan/check.json",
    )
    unowned = _run(tmp_path, "record", plan, spec)
    assert unowned.returncode != 0
    assert "evidence path for check must be" in unowned.stderr
    assert foreign_evidence.read_text(encoding="utf-8") == "foreign"

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    owner_link = tmp_path / EVIDENCE.parent
    owner_link.parent.mkdir(parents=True, exist_ok=True)
    owner_link.symlink_to(outside, target_is_directory=True)
    plan, spec, _ = _contract(tmp_path)
    symlink_escape = _run(tmp_path, "record", plan, spec)
    assert symlink_escape.returncode != 0
    assert "evidence must stay under docs/plans/evidence" in symlink_escape.stderr
    assert not (outside / "check.json").exists()
    owner_link.unlink()

    outside_file = outside / "predictable-temp-target"
    outside_file.write_text("sentinel", encoding="utf-8")
    evidence_path = tmp_path / EVIDENCE
    evidence_path.parent.mkdir(parents=True)
    evidence_path.with_suffix(".json.tmp").symlink_to(outside_file)
    plan, spec, _ = _contract(tmp_path)
    secure_write = _run(tmp_path, "record", plan, spec)
    assert secure_write.returncode == 0, secure_write.stderr
    assert outside_file.read_text(encoding="utf-8") == "sentinel"
    assert evidence_path.is_file()
    assert not evidence_path.is_symlink()

    owner_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    owner_payload["plan"] = "docs/superpowers/plans/other-plan.md"
    evidence_path.write_text(json.dumps(owner_payload), encoding="utf-8")
    owner_mismatch = _run(tmp_path, "record", plan, spec)
    assert owner_mismatch.returncode != 0
    assert "evidence ownership mismatch" in owner_mismatch.stderr

    evidence_path.unlink()
    os.mkfifo(evidence_path)
    fifo_validate = _run(tmp_path, "validate", plan, spec)
    fifo_record = _run(tmp_path, "record", plan, spec)
    assert fifo_validate.returncode != 0
    assert "evidence is not a regular file" in fifo_validate.stderr
    assert fifo_record.returncode != 0
    assert "unsafe existing evidence" in fifo_record.stderr


def test_record_propagates_masked_failure(tmp_path: Path) -> None:
    plan, spec, evidence = _contract(
        tmp_path,
        command="set -euo pipefail\nfalse\nprintf 'masked\\n'",
    )

    result = _run(tmp_path, "record", plan, spec)

    assert result.returncode != 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["actual_status"] != 0
    assert "masked" not in payload["output"]
    assert "expected status 0, observed 1" in result.stderr


def test_validate_rejects_status_mismatch(tmp_path: Path) -> None:
    plan, spec, evidence = _contract(tmp_path)
    assert _run(tmp_path, "record", plan, spec).returncode == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["actual_status"] = 1
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    result = _run(tmp_path, "validate", plan, spec)

    assert result.returncode != 0
    assert "status mismatch for check: expected 0, observed 1" in result.stderr

    assert _run(tmp_path, "record", plan, spec).returncode == 0
    evidence_text = evidence.read_text(encoding="utf-8")
    evidence.write_text(
        evidence_text.replace(
            '"actual_status": 0,',
            '"actual_status": 0,\n  "actual_status": 0,',
            1,
        ),
        encoding="utf-8",
    )
    duplicate = _run(tmp_path, "validate", plan, spec)
    assert duplicate.returncode != 0
    assert "duplicate JSON field in evidence: actual_status" in duplicate.stderr
    evidence.unlink()

    plan, spec, evidence = _contract(
        tmp_path,
        command="set -euo pipefail\nfalse",
    )
    assert _run(tmp_path, "record", plan, spec).returncode != 0
    failed_payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert failed_payload["actual_status"] == 1
    failed_payload["actual_status"] = 0
    evidence.write_text(json.dumps(failed_payload), encoding="utf-8")
    hidden_failure = _run(tmp_path, "validate", plan, spec)
    assert hidden_failure.returncode != 0
    assert "record hash mismatch for check" in hidden_failure.stderr
