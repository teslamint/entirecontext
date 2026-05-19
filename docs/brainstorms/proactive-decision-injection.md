# Proactive Decision Injection

_Draft brainstorm. Created 2026-04-27. Milestone: v0.7.0. Confidence: 92%._

## Intent

Flip `surface_on_user_prompt` default from `false` to `true` and deliver top-k relevant decisions synchronously into `additionalContext` via the `UserPromptSubmit` hook without requiring agents to call any MCP tool.

The current F4 implementation (v0.4.0) writes a Markdown file via a detached `launch_worker` subprocess — agents discover that file only if they probe the filesystem or are told to. Proactive injection converts AGENTS.md opt-in policy into default behavior: every relevant decision appears in `additionalContext` at the moment the user prompt arrives, zero agent-side tooling required.

User-visible outcomes:

- Agents receive top-k relevant decisions in every `additionalContext` payload without any explicit retrieval step.
- A Context Budget Optimizer gates token volume so injection does not crowd out prompt content.
- Session operators can tune injection with `[decisions.injection]` config without modifying the hook.

## Scope

### In

- New `[decisions.injection]` config subsection with keys: `top_k` (default 5), `max_tokens` (default 800), `min_confidence` (default 0.4), `inject_on_user_prompt` (default `true`).
- Context Budget Optimizer: trims ranked decisions list to fit within `max_tokens`, respects `min_confidence` floor.
- Synchronous `rank_related_decisions` call path within `UserPromptSubmit` handler; async `launch_worker` fallback if synchronous path exceeds budget.
- `additionalContext` assembly using existing Markdown render path from `decision_prompt_surfacing.py`.
- Config gate so operators can disable injection without touching hook wiring.
- Unit tests for budget optimizer trim logic and `min_confidence` filtering.
- Integration test verifying `additionalContext` payload is non-empty when matching decisions exist.

### Out

- MCP tool call injection (separate surface; not `additionalContext`).
- Semantic embedding computation at inject time (must use pre-computed embeddings only).
- Any change to the F4 tmp-file path or detached-subprocess redaction model.
- Changing `UserPromptSubmit` return schema beyond populating `additionalContext`.

## Synchronous vs Async Path Contract

| Condition | Path | Fallback |
|---|---|---|
| `rank_related_decisions` completes within hook budget | Synchronous; result injected into `additionalContext` directly | — |
| `rank_related_decisions` exceeds budget (timeout or heavy DB) | Returns empty `additionalContext`; launches `launch_worker` for file-based fallback | F4 async path |
| `inject_on_user_prompt = false` | Hook exits immediately, no ranking called | — |

The budget boundary must be empirically measured in `tests/test_hooks_performance.py` before the default flip ships.

## Proposed Action Items

### v0.7.0 Core

[ ] Measure synchronous `rank_related_decisions` p95 latency under realistic repo sizes (100, 500, 1000 decisions) and determine whether a synchronous path is safe within the `UserPromptSubmit` budget.

[ ] Add `[decisions.injection]` config subsection: `inject_on_user_prompt`, `top_k`, `max_tokens`, `min_confidence`. Default `inject_on_user_prompt = true`.

[ ] Implement Context Budget Optimizer in `hooks/decision_prompt_surfacing.py`: rank → trim to `max_tokens` → filter below `min_confidence` → serialize to Markdown block.

[ ] Wire synchronous injection path in `hooks/handler.py:on_user_prompt_submit`: call optimizer, populate `additionalContext`, skip if result is empty.

[ ] Add async fallback: if synchronous path raises or times out, fall through to existing `launch_worker` file-based path.

[ ] Add unit tests for optimizer trim (exact token boundary), `min_confidence` cutoff, and empty-result path.

[ ] Add integration test asserting `additionalContext` is non-empty when matching decisions exist and `inject_on_user_prompt = true`.

[ ] Update CLAUDE.md AGENTS.md decision surfacing section to reflect new default behavior.

[ ] Update CHANGELOG and ROADMAP.

## Risks

- Hook budget: `UserPromptSubmit` has an implicit latency expectation. If synchronous ranking blocks for >1s, injection degrades the interactive experience. Empirical measurement is required before the default flip.
- Token crowding: injecting 800 tokens of decisions reduces available context for the user prompt. The `max_tokens` cap must be validated against typical prompt sizes.
- Cold-start noise: repos with few decisions will inject low-confidence candidates unless `min_confidence` is tuned conservatively.
- Async fallback confusion: if synchronous path fails silently and the async path writes a file, agents may receive the same decisions twice (once in `additionalContext` if retried, once in the file).
- Default flip is a breaking behavior change: operators who rely on opt-in surfacing will need to set `inject_on_user_prompt = false` explicitly.

## Review Questions

- Is synchronous `rank_related_decisions` within `UserPromptSubmit` budget for repos with 500+ decisions, or is the async worker always required?
- What is the right `max_tokens` default — 800 tokens leaves enough headroom for most prompts, but should this be a percentage of model context rather than a fixed count?
- Should the Context Budget Optimizer prefer higher-confidence decisions when trimming, or respect the original ranking order?
- If the synchronous path succeeds but returns zero decisions above `min_confidence`, should the async worker still launch to write the file-based artifact?
- How should the `additionalContext` Markdown block be labeled so agents can distinguish it from user-provided context?
