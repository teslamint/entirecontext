#!/usr/bin/env python3
"""Compute precision from human audit verdicts.

Reads audit_verdicts.jsonl (reviewer output) and computes:
- True positive rate (precision)
- 95% confidence interval (Wilson score interval)
- Breakdown by verdict category

Usage:
    python scripts/experiments/compute_audit_precision.py [--verdicts PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return ((centre - spread) / denom, (centre + spread) / denom)


def compute_precision(verdicts_path: str) -> dict:
    path = Path(verdicts_path)
    if not path.exists():
        print(f"Verdicts file not found: {path}", file=sys.stderr)
        sys.exit(1)

    verdicts = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                verdicts.append(json.loads(line))

    n = len(verdicts)
    if n == 0:
        return {"n": 0, "precision": None, "ci_lower": None, "ci_upper": None}

    counts = {"true_positive": 0, "false_positive": 0, "ambiguous": 0}
    for v in verdicts:
        verdict = v.get("verdict", "").lower()
        if verdict in counts:
            counts[verdict] += 1
        else:
            counts.setdefault(verdict, 0)
            counts[verdict] += 1

    evaluable = counts["true_positive"] + counts["false_positive"]
    if evaluable == 0:
        precision = None
        ci = (None, None)
    else:
        precision = counts["true_positive"] / evaluable
        ci = wilson_ci(precision, evaluable)

    return {
        "n": n,
        "evaluable": evaluable,
        "ambiguous": counts["ambiguous"],
        "true_positive": counts["true_positive"],
        "false_positive": counts["false_positive"],
        "precision": round(precision, 3) if precision is not None else None,
        "ci_95_lower": round(ci[0], 3) if ci[0] is not None else None,
        "ci_95_upper": round(ci[1], 3) if ci[1] is not None else None,
        "gate_pass": precision is not None and precision >= 0.5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute audit precision")
    parser.add_argument(
        "--verdicts",
        default="scripts/experiments/output/audit_verdicts.jsonl",
    )
    args = parser.parse_args()

    result = compute_precision(args.verdicts)
    print(json.dumps(result, indent=2))

    if result["precision"] is not None:
        status = "PASS" if result["gate_pass"] else "FAIL"
        print(f"\nGate: precision={result['precision']:.1%} — {status} (threshold >=50%)")
        if result["ci_95_lower"] and result["ci_95_upper"]:
            print(f"95% CI: [{result['ci_95_lower']:.1%}, {result['ci_95_upper']:.1%}]")
        if 0.4 <= (result["precision"] or 0) <= 0.6:
            print("NOTE: Estimate in 0.4-0.6 range. Consider extending to N=100.")


if __name__ == "__main__":
    main()
