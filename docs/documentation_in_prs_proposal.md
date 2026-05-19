# Proposal: Integrating Documentation into Feature PRs

## Motivation

The v0.6.0 retrospective noted that a documentation PR was merged 5 days before the release. This creates a risk of documentation drift, where the documentation does not accurately reflect the final state of the code. To ensure that documentation is always up-to-date and accurate, it should be developed and reviewed as an integral part of the feature development process.

## Proposal

I propose the following changes to our development workflow:

1.  **"Definition of Done" includes Documentation:** A feature is not considered "done" until its corresponding documentation is also complete.

2.  **Documentation in Feature PRs:** For any PR that introduces a user-facing change or modifies a core concept, the documentation for that change **must** be included in the same PR.
    *   This includes:
        *   Updates to `README.md` for new CLI commands or options.
        *   Changes to `docs/` for new concepts or architectural changes.
        *   Docstrings and code comments.

3.  **Review Documentation with Code:** Documentation should be reviewed with the same rigor as the code it describes. Reviewers should check for clarity, accuracy, and completeness.

## Benefits

*   **Accuracy:** Documentation is always in sync with the code.
*   **Improved Reviews:** Reviewers have the full context of the change, including how it's intended to be used.
*   **Better Developer Experience:** Developers can rely on the documentation to be correct.

## Next Steps

*   Update the project's `CONTRIBUTING.md` or similar guide to reflect this new policy.
*   Enforce this policy during code reviews.
