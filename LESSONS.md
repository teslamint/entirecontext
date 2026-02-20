# Lessons Learned

_Generated from 2 assessed changes._

## 🟢 Expand (increases future options)

### ✅ This change expands future options by adding both manual and hook-based checkpoint creation with shared git helpers while keeping heavier snapshot capture optional and reversible.

**Roadmap alignment:** It aligns well with the roadmap’s capture automation direction (hook/trigger-based flow for futures/lessons) and partially advances the upcoming lightweight-checkpoint goal by defaulting to git-ref metadata unless `--snapshot` is explicitly requested.

**Suggestion:** Keep the new `core/git_utils.py` extraction, but tidy next by unifying CLI and session-end checkpoint logic behind one shared checkpoint service (including diff-base selection and metadata merge behavior) so future trigger types can be added without duplicating policy or silently diverging.

_Assessment: 84288d4f | 2026-02-20T10:48:16.009213+00:00_ 

### ✅ Introducing a pluggable LLM backend with a CLI `--backend` option increases reversibility and execution options for futures assessment, though IDE-specific files add minor portability drag.

**Roadmap alignment:** Strongly aligned with `Now` (futures assessment delivery) and creates a useful foundation for `Next` items like GitHub Action triggers and MCP-based self-evaluation by decoupling assessment from a single provider.

**Suggestion:** Keep the `core.llm` abstraction and `--backend` wiring, but tidy by isolating/removing committed `.idea` project-specific files and adding backend capability checks plus a small contract test for `get_backend(...).complete(...)` to prevent silent runtime divergence across providers.

_Assessment: dd6184a2 | 2026-02-20T08:51:22.221135+00:00_ 

