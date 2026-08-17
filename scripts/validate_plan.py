#!/usr/bin/env python3
"""Record and validate executable contracts in repository Plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


EVIDENCE_ROOT = Path("docs/plans/evidence")
SHELL_LANGUAGES = {"bash", "sh", "shell"}
CHECK_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REASON_PATTERN = re.compile(r"reason=[a-z0-9]+(?:-[a-z0-9]+)*")
TEST_ID_PATTERN = re.compile(r"`([A-Za-z_][A-Za-z0-9_.-]*(?:::[A-Za-z_][A-Za-z0-9_.-]*)*)`")
FENCE_PATTERN = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
INLINE_CODE_PATTERN = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)(?P<code>.*?)(?<!`)(?P=ticks)(?!`)",
    re.DOTALL,
)
UNSUPPORTED_SHELL_FENCE_PATTERN = re.compile(
    r"^(?:[ \t]+| {0,3}(?:(?:>[ \t]*)|(?:(?:[-+*]|\d{1,9}[.)])[ \t]+))+)"
    r"(?:`{3,}|~{3,})[ \t]*(?:bash|sh|shell)(?:[ \t]|$)",
    re.IGNORECASE,
)
SHELL_COMMANDS = {
    "bash",
    "builtin",
    "command",
    "ec",
    "git",
    "env",
    "make",
    "mypy",
    "exec",
    "npm",
    "npx",
    "pnpm",
    "pytest",
    "python",
    "nohup",
    "python3",
    "ruff",
    "sh",
    "uv",
    "sudo",
    "time",
    "yarn",
}
SHELL_CONTROL_TERMINATORS = {"elif": "then", "if": "then", "until": "do", "while": "do"}
SHELL_COMMAND_SEPARATORS = {"&&", ";", "||", "|"}
BARE_RUNNERS = {"make", "mypy", "pytest", "ruff"}
BARE_RUNNER_PATTERN = re.compile(rf"(?<![A-Za-z0-9_.-])(?:{'|'.join(sorted(BARE_RUNNERS))})(?![A-Za-z0-9_.-])")
EVIDENCE_FIELDS = {
    "schema",
    "plan",
    "spec",
    "check_id",
    "command",
    "expected_status",
    "actual_status",
    "output",
    "recorded_at",
    "plan_sha256",
    "spec_sha256",
    "command_sha256",
    "output_sha256",
    "record_sha256",
}


class ContractError(Exception):
    """A Plan or its evidence violates the repository contract."""


@dataclass(frozen=True)
class PlanCheck:
    """One exact, author-approved Plan verification block."""

    check_id: str
    expected_status: int
    evidence_path: Path
    command: str


@dataclass(frozen=True)
class Contract:
    """Parsed Plan and Specification inputs."""

    root: Path
    plan_path: Path
    spec_path: Path
    plan_text: str
    spec_text: str
    checks: tuple[PlanCheck, ...]

    @property
    def plan_relative(self) -> str:
        return self.plan_path.relative_to(self.root).as_posix()

    @property
    def spec_relative(self) -> str:
        return self.spec_path.relative_to(self.root).as_posix()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_output(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()


def _read_utf8_lf(path: Path, label: str) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {label}: {path}") from exc
    if b"\r" in content:
        raise ContractError(f"{label} must use LF line endings")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label} must be UTF-8") from exc


def _resolve_checkout_file(root: Path, raw_path: str, label: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ContractError(f"{label} path must be repository-relative: {raw_path}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ContractError(f"{label} path escapes checkout: {raw_path}")
    if not resolved.is_file():
        raise ContractError(f"missing {label} file: {raw_path}")
    return resolved


def _expected_evidence_path(plan_relative: str, check_id: str) -> Path:
    plan = Path(plan_relative)
    identity = hashlib.sha256(plan_relative.encode("utf-8")).hexdigest()[:12]
    owner = f"{plan.stem}-{identity}"
    return EVIDENCE_ROOT / owner / f"{check_id}.json"


def _resolve_evidence_path(
    root: Path,
    raw_path: str,
    plan_relative: str,
    check_id: str,
) -> Path:
    candidate = Path(raw_path)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.parts[: len(EVIDENCE_ROOT.parts)] != EVIDENCE_ROOT.parts
        or candidate == EVIDENCE_ROOT
        or candidate.suffix != ".json"
    ):
        raise ContractError(f"evidence must stay under {EVIDENCE_ROOT.as_posix()}: {raw_path}")

    expected = _expected_evidence_path(plan_relative, check_id)
    if candidate != expected:
        raise ContractError(f"evidence path for {check_id} must be {expected.as_posix()}: {raw_path}")

    evidence_root = root / EVIDENCE_ROOT
    absolute = root / candidate
    try:
        if evidence_root.resolve() != evidence_root or absolute.resolve() != absolute:
            raise ContractError(f"evidence must stay under {EVIDENCE_ROOT.as_posix()}: {raw_path}")
    except OSError as exc:
        raise ContractError(f"cannot resolve evidence path for {check_id}: {raw_path}") from exc
    return candidate


def _section(text: str, heading: str) -> str:
    lines = text.split("\n")
    start: int | None = None
    fence_marker: str | None = None
    fence_minimum_length = 0
    fence_info = ""
    heading_pattern = re.compile(rf" {{0,3}}{re.escape(heading)}[ \t]*")

    for index, line in enumerate(lines):
        if fence_marker is not None:
            if (
                re.fullmatch(
                    rf" {{0,3}}{re.escape(fence_marker)}{{{fence_minimum_length},}}[ \t]*",
                    line,
                )
                is not None
            ):
                fence_marker = None
                fence_info = ""
            continue

        opening = FENCE_PATTERN.match(line)
        if opening is not None:
            fence = opening.group("fence")
            fence_marker = fence[0]
            fence_minimum_length = len(fence)
            fence_info = opening.group("info").strip()
            continue

        if start is None:
            if heading_pattern.fullmatch(line) is not None:
                start = index + 1
            continue

        if re.match(r"^ {0,3}#{1,2}[ \t]+", line):
            return "\n".join(lines[start:index])

    if fence_marker is not None:
        raise ContractError(f"unclosed Markdown fence with info string: {fence_info or '<empty>'}")
    if start is None:
        raise ContractError(f"missing required section: {heading}")
    return "\n".join(lines[start:])


def _spec_test_ids(spec_text: str) -> list[str]:
    testing = _section(spec_text, "## Testing")
    identifiers: list[str] = []
    for identifier in TEST_ID_PATTERN.findall(testing):
        if "test" in identifier.casefold() and identifier not in identifiers:
            identifiers.append(identifier)
    if not identifiers:
        raise ContractError("Specification Testing section names no test identifiers")
    return identifiers


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _substantive(value: str) -> bool:
    return value.strip().casefold() not in {"", "-", "—", "n/a", "none"}


def _plan_dispositions(plan_text: str, spec_tests: list[str]) -> None:
    section = _section(plan_text, "## Spec Test Disposition")
    lines = section.split("\n")
    try:
        table_start = next(index for index, line in enumerate(lines) if line.strip().startswith("|"))
    except StopIteration as exc:
        raise ContractError("Spec Test Disposition section contains no table") from exc

    table_lines: list[str] = []
    for line in lines[table_start:]:
        if not line.strip().startswith("|"):
            break
        table_lines.append(line)
    if len(table_lines) < 2:
        raise ContractError("Spec Test Disposition table is incomplete")

    expected_header = ["spec test", "disposition", "plan test(s)", "rationale"]
    if [cell.casefold() for cell in _table_cells(table_lines[0])] != expected_header:
        raise ContractError("Spec Test Disposition table has invalid columns")
    separator = _table_cells(table_lines[1])
    if len(separator) != 4 or any(re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator):
        raise ContractError("Spec Test Disposition table has invalid separator")

    rows: dict[str, tuple[str, list[str], str]] = {}
    for line in table_lines[2:]:
        cells = _table_cells(line)
        if len(cells) != 4:
            raise ContractError(f"Spec Test Disposition row must have four columns: {line}")
        spec_ids = TEST_ID_PATTERN.findall(cells[0])
        if len(spec_ids) != 1:
            raise ContractError(f"Spec Test Disposition row must name one Spec test: {line}")
        spec_id = spec_ids[0]
        if spec_id in rows:
            raise ContractError(f"duplicate Spec test disposition: {spec_id}")
        plan_ids = TEST_ID_PATTERN.findall(cells[2])
        rows[spec_id] = (cells[1].casefold(), plan_ids, cells[3])

    missing = [identifier for identifier in spec_tests if identifier not in rows]
    if missing:
        raise ContractError(f"missing Spec test disposition: {missing[0]}")
    extra = [identifier for identifier in rows if identifier not in spec_tests]
    if extra:
        raise ContractError(f"extra Spec test disposition: {extra[0]}")

    for spec_id in spec_tests:
        disposition, plan_ids, rationale = rows[spec_id]
        if disposition not in {"retained", "merged", "dropped"}:
            raise ContractError(f"invalid disposition for {spec_id}: {disposition}")
        if disposition == "retained" and plan_ids != [spec_id]:
            raise ContractError(f"retained disposition must map to the same test: {spec_id}")
        if disposition == "merged":
            if not plan_ids:
                raise ContractError(f"merged disposition requires a Plan test: {spec_id}")
            if not _substantive(rationale):
                raise ContractError(f"merged disposition requires rationale: {spec_id}")
        if disposition == "dropped":
            if plan_ids:
                raise ContractError(f"dropped disposition must not name a Plan test: {spec_id}")
            if not _substantive(rationale):
                raise ContractError(f"dropped disposition requires rationale: {spec_id}")


def _parse_check_info(
    root: Path,
    plan_relative: str,
    tokens: list[str],
    command: str,
) -> PlanCheck:
    metadata: dict[str, str] = {}
    for token in tokens[2:]:
        key, separator, value = token.partition("=")
        if not separator or not key or not value or key in metadata:
            raise ContractError(f"invalid plan-check metadata: {token}")
        metadata[key] = value
    if set(metadata) != {"id", "expected-status", "evidence"}:
        raise ContractError("plan-check requires exactly id, expected-status, and evidence metadata")

    check_id = metadata["id"]
    if CHECK_ID_PATTERN.fullmatch(check_id) is None:
        raise ContractError(f"invalid plan-check id: {check_id}")
    try:
        expected_status = int(metadata["expected-status"])
    except ValueError as exc:
        raise ContractError(f"invalid expected status for {check_id}: {metadata['expected-status']}") from exc
    if not 0 <= expected_status <= 255:
        raise ContractError(f"invalid expected status for {check_id}: {expected_status}")

    evidence_path = _resolve_evidence_path(root, metadata["evidence"], plan_relative, check_id)
    first_command = next(
        (line.strip(" \t") for line in command.split("\n") if line.strip(" \t")),
        "",
    )
    if first_command != "set -euo pipefail":
        raise ContractError(f"plan-check {check_id} must begin with set -euo pipefail")
    return PlanCheck(check_id, expected_status, evidence_path, command)


def _looks_like_shell_command(value: str, *, imperative: bool) -> bool:
    if BARE_RUNNER_PATTERN.search(value) is not None:
        return True
    if imperative:
        return True
    try:
        lexer = shlex.shlex(value, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False
    if not tokens:
        return False

    path_command = any(
        Path(token).name.casefold().endswith(".sh") or token.startswith(("./", "../")) for token in tokens
    )
    if path_command:
        return True
    if len(tokens) > 1:
        return any(Path(token).name.casefold() in SHELL_COMMANDS for token in tokens)
    return False


def _is_shell_command_at(tokens: Sequence[str], index: int) -> bool:
    while index < len(tokens) and (
        tokens[index] == "!" or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]) is not None
    ):
        index += 1
    if index == len(tokens):
        return False
    if index + 1 < len(tokens) and tokens[index + 1] == "(":
        return False
    token = tokens[index]
    command_name = Path(token).name.casefold()
    return command_name in SHELL_COMMANDS or command_name.endswith(".sh") or token.startswith(("./", "../"))


def _looks_like_shell_fence_command(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return False
    try:
        lexer = shlex.shlex(stripped, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False
    if not tokens:
        return False
    if len(tokens) > 1 and (tokens[1].startswith("=") or tokens[1].endswith("=")):
        return False

    terminator = SHELL_CONTROL_TERMINATORS.get(tokens[0].casefold())
    if terminator is not None:
        try:
            terminator_index = tokens.index(terminator, 1)
        except ValueError:
            return False
        if ";" not in tokens[1:terminator_index]:
            return False
        command_tokens = tokens[1:terminator_index]
    else:
        command_tokens = tokens

    for index in range(len(command_tokens)):
        if index == 0 or command_tokens[index - 1] in SHELL_COMMAND_SEPARATORS:
            if _is_shell_command_at(command_tokens, index):
                return True
    return False


def _reject_inline_shell_commands(lines: list[str]) -> None:
    prose = "\n".join(line for line in lines if not line.startswith(("    ", "\t")))
    for match in INLINE_CODE_PATTERN.finditer(prose):
        value = match.group("code").strip()
        line_start = prose.rfind("\n", 0, match.start()) + 1
        prefix = prose[line_start : match.start()]
        imperative = (
            re.search(
                r"\b(?:run|execute|invoke|call)(?:\s+(?:command|check|test|runner))?"
                r"\s*[:\-–—]?\s*(?:\*\*)?\s*$",
                prefix,
                re.IGNORECASE,
            )
            is not None
        )
        if _looks_like_shell_command(value, imperative=imperative):
            raise ContractError(f"inline shell command must move to a classified fence: {value}")


def _plan_checks(root: Path, plan_relative: str, plan_text: str) -> tuple[PlanCheck, ...]:
    lines = plan_text.split("\n")
    checks: list[PlanCheck] = []
    outside_lines: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    index = 0
    while index < len(lines):
        if UNSUPPORTED_SHELL_FENCE_PATTERN.match(lines[index]) is not None:
            raise ContractError("non-top-level shell fence is unsupported; move it to a top-level classified fence")

        opening = FENCE_PATTERN.match(lines[index])
        if opening is None:
            outside_lines.append(lines[index])
            index += 1
            continue

        fence = opening.group("fence")
        info = opening.group("info").strip()
        marker = fence[0]
        if marker == "`" and "`" in info:
            raise ContractError("backtick fence info string must not contain backticks")
        minimum_length = len(fence)
        content_start = index + 1
        index = content_start
        while index < len(lines):
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(marker)}{{{minimum_length},}}[ \t]*",
                lines[index],
            )
            if closing is not None:
                break
            index += 1
        if index == len(lines):
            raise ContractError(f"unclosed Markdown fence with info string: {info or '<empty>'}")
        content = lines[content_start:index]

        try:
            tokens = shlex.split(info)
        except ValueError as exc:
            raise ContractError(f"invalid fence info string: {info}") from exc
        if tokens and tokens[0].casefold() in SHELL_LANGUAGES:
            if len(tokens) < 2:
                raise ContractError("unclassified shell fence")
            classification = tokens[1]
            if classification == "implementation-only":
                if len(tokens) != 3 or REASON_PATTERN.fullmatch(tokens[2]) is None:
                    raise ContractError("implementation-only requires exactly reason=<lowercase-slug>")
            elif classification == "plan-check":
                command = "\n".join(content) + ("\n" if content else "")
                check = _parse_check_info(root, plan_relative, tokens, command)
                if check.check_id in seen_ids:
                    raise ContractError(f"duplicate plan-check id: {check.check_id}")
                if check.evidence_path in seen_paths:
                    raise ContractError(f"duplicate plan-check evidence path: {check.evidence_path}")
                seen_ids.add(check.check_id)
                seen_paths.add(check.evidence_path)
                checks.append(check)
            else:
                raise ContractError(f"unclassified shell fence: {classification}")
        elif any(_looks_like_shell_fence_command(line) for line in content):
            raise ContractError("unclassified shell fence")
        index += 1

    _reject_inline_shell_commands(outside_lines)
    if not checks:
        raise ContractError("Plan contains no plan-check shell fence")
    return tuple(checks)


def _load_contract(root: Path, plan_arg: str, spec_arg: str) -> Contract:
    plan_path = _resolve_checkout_file(root, plan_arg, "Plan")
    spec_path = _resolve_checkout_file(root, spec_arg, "Specification")
    plan_text = _read_utf8_lf(plan_path, "Plan")
    spec_text = _read_utf8_lf(spec_path, "Specification")
    _plan_dispositions(plan_text, _spec_test_ids(spec_text))
    plan_relative = plan_path.relative_to(root).as_posix()
    checks = _plan_checks(root, plan_relative, plan_text)
    return Contract(root, plan_path, spec_path, plan_text, spec_text, checks)


def _record_sha256(payload: dict[str, Any]) -> str:
    bound = {key: value for key, value in payload.items() if key != "record_sha256"}
    canonical = json.dumps(
        bound,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _sha256(canonical)


def _evidence_payload(contract: Contract, check: PlanCheck, status: int, output: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "plan-check/v1",
        "plan": contract.plan_relative,
        "spec": contract.spec_relative,
        "check_id": check.check_id,
        "command": check.command,
        "expected_status": check.expected_status,
        "actual_status": status,
        "output": output,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": _sha256(contract.plan_text),
        "spec_sha256": _sha256(contract.spec_text),
        "command_sha256": _sha256(check.command),
        "output_sha256": _sha256_output(output),
    }
    payload["record_sha256"] = _record_sha256(payload)
    return payload


def _open_directory(root: Path, relative: Path, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root, flags)
    try:
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise ContractError(f"invalid evidence directory component: {part}")
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
            next_directory = os.open(part, flags | no_follow, dir_fd=current)
            os.close(current)
            current = next_directory
        return current
    except Exception:
        os.close(current)
        raise


def _read_anchored(root: Path, relative: Path) -> bytes:
    directory = _open_directory(root, relative.parent, create=False)
    try:
        descriptor = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ContractError(f"evidence is not a regular file: {relative.as_posix()}")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                return handle.read()
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _reject_duplicate_keys():
    def reject(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON field in evidence: {key}")
            result[key] = value
        return result

    return reject


def _load_evidence(raw: bytes, check_id: str) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON evidence for {check_id}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"evidence must be a JSON object for {check_id}")
    return payload


def _write_evidence(contract: Contract, check: PlanCheck, payload: dict[str, Any]) -> None:
    _resolve_evidence_path(
        contract.root,
        check.evidence_path.as_posix(),
        contract.plan_relative,
        check.check_id,
    )
    try:
        directory = _open_directory(contract.root, check.evidence_path.parent, create=True)
    except OSError as exc:
        raise ContractError(f"unsafe evidence directory for {check.check_id}") from exc
    temporary_name: str | None = None
    try:
        try:
            existing_fd = os.open(
                check.evidence_path.name,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ContractError(f"unsafe existing evidence for {check.check_id}") from exc
        else:
            if not stat.S_ISREG(os.fstat(existing_fd).st_mode):
                os.close(existing_fd)
                raise ContractError(f"unsafe existing evidence for {check.check_id}")
            try:
                with os.fdopen(existing_fd, "rb", closefd=False) as handle:
                    existing = _load_evidence(handle.read(), check.check_id)
            finally:
                os.close(existing_fd)
            if existing.get("plan") != contract.plan_relative or existing.get("check_id") != check.check_id:
                raise ContractError(f"evidence ownership mismatch for {check.check_id}")

        for _ in range(16):
            candidate = f".{check.evidence_path.name}.{secrets.token_hex(12)}.tmp"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        else:
            raise ContractError(f"cannot allocate evidence temporary for {check.check_id}")

        content = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            check.evidence_path.name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        temporary_name = None
        os.fsync(directory)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def _assert_contract_unchanged(contract: Contract) -> None:
    if _read_utf8_lf(contract.plan_path, "Plan") != contract.plan_text:
        raise ContractError("Plan changed while recording evidence")
    if _read_utf8_lf(contract.spec_path, "Specification") != contract.spec_text:
        raise ContractError("Specification changed while recording evidence")


def _record(contract: Contract) -> int:
    mismatches = 0
    for check in contract.checks:
        result = subprocess.run(
            ["/bin/bash", "-c", check.command],
            cwd=contract.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = result.stdout.decode("utf-8", errors="surrogateescape")
        _assert_contract_unchanged(contract)
        payload = _evidence_payload(contract, check, result.returncode, output)
        _write_evidence(contract, check, payload)
        print(f"recorded {check.check_id}: status {result.returncode}; evidence {check.evidence_path.as_posix()}")
        if result.returncode != check.expected_status:
            print(
                f"plan contract error: {check.check_id} expected status {check.expected_status}, "
                f"observed {result.returncode}",
                file=sys.stderr,
            )
            mismatches += 1
    return 1 if mismatches else 0


def _require_string(payload: dict[str, Any], field: str, check_id: str) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise ContractError(f"invalid {field} in evidence for {check_id}")
    return value


def _require_status(payload: dict[str, Any], field: str, check_id: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"invalid {field} in evidence for {check_id}")
    return value


def _validate_timestamp(value: str, check_id: str) -> None:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"invalid recorded_at in evidence for {check_id}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ContractError(f"recorded_at must be timezone-aware for {check_id}")


def _validate_evidence(contract: Contract, check: PlanCheck) -> None:
    _resolve_evidence_path(
        contract.root,
        check.evidence_path.as_posix(),
        contract.plan_relative,
        check.check_id,
    )
    try:
        raw = _read_anchored(contract.root, check.evidence_path)
    except FileNotFoundError as exc:
        raise ContractError(f"missing evidence for {check.check_id}: {check.evidence_path.as_posix()}") from exc
    except OSError as exc:
        raise ContractError(f"unsafe evidence for {check.check_id}") from exc
    payload = _load_evidence(raw, check.check_id)
    if set(payload) != EVIDENCE_FIELDS:
        raise ContractError(f"evidence fields mismatch for {check.check_id}")
    if payload["schema"] != "plan-check/v1":
        raise ContractError(f"unsupported evidence schema for {check.check_id}")

    stored_check_id = _require_string(payload, "check_id", check.check_id)
    if stored_check_id != check.check_id:
        raise ContractError(f"check id mismatch for {check.check_id}")
    stored_command = _require_string(payload, "command", check.check_id)
    if stored_command != check.command:
        raise ContractError(f"command mismatch for {check.check_id}")
    if _require_string(payload, "command_sha256", check.check_id) != _sha256(stored_command):
        raise ContractError(f"command hash mismatch for {check.check_id}")

    output = _require_string(payload, "output", check.check_id)
    if _require_string(payload, "output_sha256", check.check_id) != _sha256_output(output):
        raise ContractError(f"output hash mismatch for {check.check_id}")
    if _require_string(payload, "plan_sha256", check.check_id) != _sha256(contract.plan_text):
        raise ContractError(f"Plan hash mismatch for {check.check_id}")
    if _require_string(payload, "spec_sha256", check.check_id) != _sha256(contract.spec_text):
        raise ContractError(f"Specification hash mismatch for {check.check_id}")

    if _require_string(payload, "plan", check.check_id) != contract.plan_relative:
        raise ContractError(f"Plan path mismatch for {check.check_id}")
    if _require_string(payload, "spec", check.check_id) != contract.spec_relative:
        raise ContractError(f"Specification path mismatch for {check.check_id}")
    expected_status = _require_status(payload, "expected_status", check.check_id)
    if expected_status != check.expected_status:
        raise ContractError(f"expected status declaration mismatch for {check.check_id}")
    actual_status = _require_status(payload, "actual_status", check.check_id)
    if actual_status != check.expected_status:
        raise ContractError(
            f"status mismatch for {check.check_id}: expected {check.expected_status}, observed {actual_status}"
        )
    _validate_timestamp(_require_string(payload, "recorded_at", check.check_id), check.check_id)
    record_hash = _require_string(payload, "record_sha256", check.check_id)
    if record_hash != _record_sha256(payload):
        raise ContractError(f"record hash mismatch for {check.check_id}")


def _validate(contract: Contract) -> int:
    for check in contract.checks:
        _validate_evidence(contract, check)
    print(f"plan contract valid: {len(contract.checks)} check(s), evidence and Spec dispositions verified")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("record", "validate"):
        command = subparsers.add_parser(operation)
        command.add_argument("--plan", required=True)
        command.add_argument("--spec", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path.cwd().resolve()
    try:
        contract = _load_contract(root, args.plan, args.spec)
        if args.operation == "record":
            return _record(contract)
        return _validate(contract)
    except ContractError as exc:
        print(f"plan contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
