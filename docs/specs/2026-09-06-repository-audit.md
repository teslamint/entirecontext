# Repository audit corrections

## Scope

Correct reproduced search, export, and guidance removal defects. Preserve unrelated working-tree changes and existing public defaults.
Use EC decision 30f75661 for explicit global cleanup. Preserve repository fault isolation from decision 3cbd031b.
The generated lesson e2be8687 supports sharing duplicated Git signal collection without reversing core dependencies.

## Contracts

- Semantic search applies requested filters before limiting accepted results. CLI target selection and the MCP default turn target reach semantic search, including cross-repository calls.
- Incremental checkpoint export compares instants, including mixed SQLite and ISO timestamps. Equal timestamps remain excluded.
- Export filtering covers session text and checkpoint descriptive values. Preserve JSON structure, identifiers, and explicit filtering opt-out.
- Explicit guidance removal persists nested hook changes while preserving unrelated commands and settings for Claude and Codex.
- Resuming an ended session clears its end timestamp. Summary-generation failures remain contained even before project lookup completes.
- Shared Git signal helpers preserve commands, timeout, result ordering, truncation, and failure behavior across existing callers.

## Measurement

Use existing SQLite fixtures and actual exported JSON files. Search tests store deterministic vectors and replace only query encoding.
Target: every reproduced regression changes from failure to success. Existing module suites remain green.
Target: duplicate diff and recent-commit collectors decrease from two definitions each to one definition each.
Run the full suite, lint, format, type checks, and both package builds. Report missing optional dependencies separately.

## Testing

- `test_semantic_filter_limit`: a matching candidate beyond the former oversampling window remains visible.
- `test_semantic_target`: turn and session requests exclude other source types at each public entry point.
- `test_checkpoint_timestamp`: export later timestamps across formats; exclude earlier and equal instants.
- `test_export_redaction`: redact supported metadata text while preserving valid JSON and the filtering opt-out.
- `test_disable_remove_guidance_preserves_sibling_in_same_group`: remove the EC command from a mixed group for both agents; preserve sibling commands.
- `TestSharedDecisionSignals`: preserve diff and commit collection behavior with real repositories and controlled subprocess failures.
- `test_resume_reopens_ended_session`: resumed sessions become visible to current-session lookup.
- `test_intent_summary_tolerates_lookup_failure`: early database errors do not escape optional summary generation.
