# Tiered Review Policy Proposal
> **Status:** Proposal / historical process note. Current review principles live in `AGENTS.md`; this file records an unadopted tiering idea and is not itself binding policy.

## Motivation

The v0.6.0 retrospective noted an uneven distribution of review effort. PR #120 (a high-risk schema change) received 7 rounds of review which proved valuable, while PR #121 was under-reviewed. This suggests a need for a more structured approach to code review, allocating effort based on the risk and complexity of the changes.

## Proposal

I propose a three-tiered review policy to ensure an appropriate level of scrutiny for all changes.

### Tier 1: High Risk

*   **Examples:** Schema migrations, changes to core ranking logic, modifications to security-sensitive code.
*   **Requirements:** At least **two** reviewers, one of whom must be a human. Can be a mix of AI and human reviewers (e.g., 1 human + 1 AI, or 2 humans + AI).
*   **Rationale:** These changes have the highest potential for causing significant bugs or data loss. Multiple reviewers provide a stronger safety net.

### Tier 2: Medium Risk

*   **Examples:** New features, new CLI commands, significant refactors of existing components.
*   **Requirements:** At least **one** human reviewer and **one** AI reviewer.
*   **Rationale:** These changes introduce new logic and have a moderate risk of introducing bugs. A combination of human and AI review provides a good balance of rigor and speed.

### Tier 3: Low Risk

*   **Examples:** Documentation changes, typo fixes, minor refactors with existing test coverage.
*   **Requirements:** At least **one** reviewer (human or AI).
*   **Rationale:** These changes are unlikely to introduce critical bugs. A single review is sufficient to catch obvious errors.

## Next Steps

*   Discuss and refine the tier definitions and requirements.
*   Integrate this policy into the project's contribution guidelines.
