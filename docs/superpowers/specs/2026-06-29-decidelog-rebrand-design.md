# Decidelog — Rebrand & Positioning Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand EntireContext to Decidelog and reposition the project as the decision memory layer for agent-assisted development, with clear differentiation from the crowded agent-memory market.

**Architecture:** Same `capture→distill→retrieve→intervene→outcome` loop. The rebrand changes identity, naming, and packaging — not the core architecture. One new schema addition (`decided_by`) enhances the decision model with decision-maker attribution.

**Tech Stack:** Python 3.12+, uv, SQLite (WAL mode), Typer CLI (`dl`), MCP server

## Global Constraints

- All changes land in a single v1.0 release (no gradual migration)
- No backward compatibility with `ec` CLI or `entirecontext` PyPI package (alpha status)
- Existing data must be migratable via `dl migrate` command
- `decided_by` field defaults to `"collaborative"` for existing records (safe default)
- No new external dependencies
- All existing tests must pass after rename (adjusted imports)

---

## 1. Rebrand Identity

### 1.1 Name Change

| Item | Current | New |
|------|---------|-----|
| Project name | EntireContext | Decidelog |
| PyPI package | `entirecontext` | `decidelog` |
| CLI command | `ec` | `dl` |
| MCP tool prefix | `ec_*` | `dl_*` |
| MCP server name | `entirecontext` | `decidelog` |
| GitHub repo | `entirecontext` | `decidelog` |

### 1.2 Path Changes

| Item | Current | New |
|------|---------|-----|
| Per-repo DB dir | `.entirecontext/` | `.decidelog/` |
| Global config/state | `~/.entirecontext/` | `~/.decidelog/` |
| Config files | `.entirecontext/config.toml` | `.decidelog/config.toml` |
| DB file | `.entirecontext/db/local.db` | `.decidelog/db/local.db` |
| Global DB | `~/.entirecontext/db/ec.db` | `~/.decidelog/db/dl.db` |

### 1.3 Migration Command

`dl migrate` scans for `.entirecontext/` directories and moves them to `.decidelog/`, updating internal path references in the SQLite database. One-time operation per repo.

### 1.4 Description & Tagline

- **One-liner:** "Decision memory for agent-assisted development"
- **Tagline:** "Remember why, not just what"
- **Full description:** "Decidelog records engineering decisions — who made them, why, what alternatives were rejected — and tracks their outcomes over time. Git-anchored, agent-agnostic, self-improving."

## 2. Positioning

### 2.1 Value Proposition

Decidelog is the **decision memory layer** that sits beneath agent-native memory systems (Claude auto-memory, Codex session history, etc.) and above the git history.

- Agent auto-memory = preferences, patterns, corrections ("use `uv run pytest` not `pytest`")
- Decidelog = decisions, rationale, alternatives, outcomes ("chose SQLite over Redis because X; 3 months later: decision held, no perf issues")
- Git history = what changed, when, by whom

Decidelog fills the gap: **why** things were decided, not just **what** changed or **how** to do things.

### 2.2 Competitive Differentiation

| Capability | Decidelog | Mem0/OpenMemory | Claude Auto-Memory | Zep |
|------------|-----------|-----------------|---------------------|-----|
| Memory target | Decisions + alternatives + rationale | Facts / preferences | Patterns / corrections | Conversation summaries |
| Outcome tracking | 5 types (accepted/ignored/contradicted/refined/replaced) + quality score | None | None | None |
| Temporal model | Git-anchored time-travel (rewind, blame, TQL planned) | None | Session-scoped | Decay only |
| Self-improvement | outcome→ranking→extraction feedback loop | Auto-extraction only | Dreaming consolidation | Auto-summarization |
| Decision-maker attribution | `decided_by` (human/agent/collaborative) | None | None | None |
| Agent compatibility | Claude/Codex/Gemini/any MCP client | MCP | Claude only | LangChain/MCP |
| Storage | Local SQLite (WAL) + git-anchored | Cloud or local | Cloud (Anthropic) | Cloud or self-hosted |

### 2.3 Relationship with Built-in Agent Memory

Decidelog is a **complement and infrastructure layer**, not a replacement:

1. Agent auto-memory handles the "how" (workflow preferences, tool usage patterns)
2. Decidelog handles the "why" (engineering decisions, their context, their outcomes)
3. Git history handles the "what" and "when"

Integration path: CLAUDE.md / AGENTS.md references `dl` commands so agents naturally leverage decision memory during their sessions.

## 3. Decision Attribution (`decided_by`)

### 3.1 Schema Addition

New column on `decisions` table:

```sql
decided_by TEXT NOT NULL DEFAULT 'collaborative'
  CHECK (decided_by IN ('human', 'agent', 'collaborative'))
```

- **human**: Human explicitly made the decision; agent executed
- **agent**: Agent autonomously decided; human approved/ignored post-hoc
- **collaborative**: Decision emerged from human-agent dialogue (most common)

### 3.2 Recording Paths

| Path | Default `decided_by` | Override |
|------|---------------------|----------|
| `dl decision create` (CLI) | `human` | `--decided-by agent\|collaborative` |
| `dl_decision_create` (MCP) | `collaborative` | `decided_by` parameter |
| Auto-extraction (SessionEnd) | Inferred from turn context | N/A |
| `dl decision candidate confirm` | Inherited from candidate | Overridable |

### 3.3 Inference Logic (Auto-extraction)

When extracting decisions from session turns:
- Decision text found primarily in user messages → `human`
- Decision text found primarily in assistant messages without prior user directive → `agent`
- Decision emerged from back-and-forth dialogue → `collaborative`

Inference is best-effort; `collaborative` is the safe fallback.

### 3.4 Dashboard / Analytics

- `dl dashboard` shows decision-maker distribution (human / agent / collaborative)
- Outcome comparison: "agent decisions accepted rate" vs "human decisions accepted rate"
- Maturity dimension: agent autonomy level tracking (future)

## 4. v1.0 Transition Plan

### 4.1 Prerequisites (Complete Before Rebrand)

- [ ] Current ROADMAP v1.0 gate met: `capture→distill→retrieve→intervene→outcome` loop completes autonomously
- [ ] `auto_extract` default true with production verification
- [ ] Schema version 15 migration tested (v14 → v15 with `decided_by` + path changes)

### 4.2 v1.0 Release Checklist

- [ ] Rename Python package: `entirecontext` → `decidelog` (pyproject.toml, src/ directory)
- [ ] Rename CLI entry point: `ec` → `dl`
- [ ] Rename all MCP tools: `ec_*` → `dl_*`
- [ ] Update all import paths: `entirecontext.*` → `decidelog.*`
- [ ] Update all path constants: `.entirecontext/` → `.decidelog/`
- [ ] Add `dl migrate` command for data migration
- [ ] Add `decided_by` column to `decisions` table (schema v15)
- [ ] Update README, CLAUDE.md, AGENTS.md with new identity
- [ ] Update GitHub repo name and description
- [ ] Publish `decidelog` to PyPI
- [ ] Tag v1.0.0

### 4.3 What Does NOT Change

- Core architecture (`capture→distill→retrieve→intervene→outcome`)
- Database schema (except `decided_by` addition and path references)
- Hook system (Claude Code hooks integration)
- Config TOML format and sections
- Test structure and fixtures (adjusted imports only)
- Git-anchored temporal model

## 5. Post-v1.0 Roadmap Direction

### 5.1 Retroactive Archaeology (Cold Start Solution)

`dl archaeologize` — extract decision corpus from existing git history:
- Parse `git log --patch` for decision-indicating patterns
- Extract PR descriptions and review comments for rationale
- Generate `source:inferred` decisions with `decided_by:collaborative` default
- Eliminates the largest adoption barrier (empty database on first use)

Existing brainstorm: `docs/brainstorms/retroactive-git-archaeology.md`

### 5.2 Decision Packs + Team

Reusable decision bundles by domain:
- `dl pack create testing` — bundle testing-related decisions for reuse
- `dl pack apply <pack-name>` — apply a decision pack to a new repo
- Team sharing: export/import packs across repos and team members
- v1.x track: team-scoped decision visibility (surfacing only, no enforcement)

### 5.3 Other Exploration Items (Unchanged)

These remain in the exploration backlog with adjusted naming:
- Temporal Query Language (TQL): `dl query --at <ref>`
- Decision-Annotated Git Blame: `dl blame <file>`
- Alive Session Memory (Rolling WAL Capture)
- Pre-Compaction Session Snapshot

## 6. Non-Goals (Reinforced)

- NOT a generic knowledge management system or RAG platform
- NOT policy enforcement / governance / ACL
- NOT agent behavior analysis / monitoring
- NOT code generation or change suggestion
- NOT agent-to-agent communication layer
- NOT a replacement for Claude auto-memory or Codex session history

## 7. Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Name confusion with OneContext | Zero | No search result overlap on "decidelog" |
| PyPI package available | Yes | `pip install decidelog` works |
| Cold start time (with archaeology) | < 5 min for typical repo | Time from `dl init` + `dl archaeologize` to first surfaced decision |
| Decision-maker attribution accuracy | > 80% | Manual audit of auto-extracted `decided_by` values |
| Existing user migration | < 2 min | Time to run `dl migrate` on a typical repo |

## References

- [Agent Memory Landscape Research](../../research/agent-memory-landscape.md)
- [Product Roadmap Ideation](../../ideation/2026-04-27-product-roadmap-ideation.md)
- [Retroactive Git Archaeology Brainstorm](../../brainstorms/retroactive-git-archaeology.md)
- [Project Direction Interview (2026-06-02)](memory: project-direction-2026-06-02)
