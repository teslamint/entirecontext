"""Intentional verification fixture — DO NOT MERGE.

This file is created solely to verify that the Phase A branch-protection
setup actually blocks a failing PR from merging. It must be removed before
the PR is closed. If this file is still present after PR close, something
went wrong with the verification procedure.
"""


def test_intentionally_fails_to_verify_branch_protection() -> None:
    assert False, "intentional failure — Phase A verification PR, do not merge"
