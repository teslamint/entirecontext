# Agent Memory Landscape

_Surveyed 2026-02-23 from [GitHub topics/agent-memory](https://github.com/topics/agent-memory). 20 projects reviewed, 7 analyzed in depth._

## Core Projects

### 1. memU — 9.9k stars

**Repo:** [NevaMind-AI/memU](https://github.com/NevaMind-AI/memU)

**Core approach:** Dual-process architecture — main agent + separate memory bot observing interactions in parallel. Three-layer model: Resource (raw data) → Item (extracted facts) → Category (auto-organized topics).

**Unique features:**
- Proactive intelligence: learns and anticipates without explicit commands
- Concurrent monitoring: memory bot works while agent handles queries (no bottleneck)
- Cost reduction via intelligent caching vs. full conversation replay
- Multi-provider deployment (OpenRouter, DashScope, custom endpoints)

**EntireContext application:**
- Proactive checkpoint generation at detected milestones
- Cross-session pattern detection for recurring debugging/architecture decisions
- Background synthesis: compute assessments without blocking capture

---

### 2. MemOS — 5.8k stars

**Repo:** [MemTensor/MemOS](https://github.com/MemTensor/MemOS)

**Core approach:** Unified memory OS with graph-based storage. Memory cubes as composable, isolated knowledge bases. Async scheduling with Neo4j (graph) + Qdrant (vector).

**Unique features:**
- Inspectable graph vs. opaque vector search
- Natural-language feedback loops for memory refinement
- 43.7% higher accuracy vs. OpenAI memory, 35.2% token reduction
- Multi-modal support: text, images, tool traces, personas

**EntireContext application:**
- Structured memory graphs linking entities/decisions across codebase
- Natural-language refinement UI for auto-assessments
- Pluggable backends: SQLite (current) → Neo4j option for richer semantics

---

### 3. ACE (Agentic Context Engine) — 1.9k stars

**Repo:** [kayba-ai/agentic-context-engine](https://github.com/kayba-ai/agentic-context-engine)

**Core approach:** Self-improving agent via execution feedback, no fine-tuning. "Skillbook" evolves dynamically. Recursive Reflector: sandboxed code execution analyzing traces iteratively.

**Unique features:**
- 20-35% performance gains on complex tasks via learned patterns
- 49% token reduction in browser automation
- Failure-driven learning: failures inform avoidance patterns
- In-context learning only — no external training needed

**EntireContext application:**
- Automated performance analysis: token usage, completion times → optimization insights
- Skillbook concept: extract patterns from successful debugging/refactoring sessions
- Context-aware summarization: identify which context preserves maximum value

---

### 4. mcp-memory-service — 1.4k stars

**Repo:** [doobidoo/mcp-memory-service](https://github.com/doobidoo/mcp-memory-service)

**Core approach:** Persistent memory with hybrid BM25 + vector search. Local ONNX embeddings (MiniLM-L6-v2). SQLite-vec backend + knowledge graph with 6 typed relationship edges.

**Unique features:**
- 5ms retrieval without cloud roundtrips
- Autonomous consolidation: decay algorithms + semantic clustering compress old memories
- Multi-agent coordination via X-Agent-ID header
- 6 typed relationships: causes, fixes, contradicts, etc.
- Security hardened (CVE-2024-23342, CWE-209 patched)

**EntireContext application:**
- Hybrid search: BM25 for turn content + embeddings for session matching
- Memory consolidation strategies: compress old turns preserving signal
- Typed relationships: causality, conflict, dependency edges for assessments
- Agent scoping headers for MCP server multi-tenant scenarios

---

### 5. shodh-memory — 98 stars

**Repo:** [varun29ankuS/shodh-memory](https://github.com/varun29ankuS/shodh-memory)

**Core approach:** Neuroscience-inspired three-tier cognitive model: Working (100 items) → Session (500MB) → Long-Term (RocksDB). Hebbian learning, activation decay, spreading activation.

**Unique features:**
- ~17MB single binary, fully offline (no cloud dependencies)
- Spreading activation through knowledge graphs
- Semantic retrieval (34-58ms), tag-based (~1ms)
- Memory replay during maintenance cycles
- Entity extraction via TinyBERT NER

**EntireContext application:**
- Knowledge graph layer: git entities (commits, files, functions) as nodes
- Spreading activation: retrieve related turns via transitive git relationships
- Activation decay: weight recent vs. historical context by session age
- Entity extraction: code entities (function names, variables) for tag-based retrieval

---

### 6. memsearch — 584 stars

**Repo:** [zilliztech/memsearch](https://github.com/zilliztech/memsearch)

**Core approach:** Markdown-first — vector store is derived index, rebuildable anytime. SHA-256 deduplication, live file watcher, hybrid BM25 + dense vectors + reciprocal rank fusion.

**Unique features:**
- Git-friendly, vendor-neutral: data in markdown, not proprietary DB
- No API lock-in; local embedding options
- Background watching keeps indices current
- Ready-made Claude Code plugin

**EntireContext application:**
- Markdown export: summarize sessions/assessments to human-readable, git-friendly format
- Live reindexing: detect SQLite changes via triggers, re-embed changed turns
- Reciprocal Rank Fusion: merge FTS + semantic results using RRF
- Multi-backend embeddings: local sentence-transformers default, remote optional

---

### 7. cursor10x-mcp — 76 stars

**Repo:** [aiurda/cursor10x-mcp](https://github.com/aiurda/cursor10x-mcp)

**Core approach:** Four-component design: MCP Server, Turso DB, Memory Subsystems (STM/LTM/Episodic/Semantic), Vector Embeddings. Four memory types with distinct retrieval strategies.

**Unique features:**
- Code relationship detection: indexes functions/classes/variables across languages
- Temporal context preservation with causal chains
- Unified conversation init/end tools
- Episodic memory maintaining causal relationships between events

**EntireContext application:**
- Code-aware semantic search via AST extraction (functions, classes, imports)
- Causal turn chains: track data flow across turns
- MCP resource browsing: expose sessions/checkpoints/assessments as read-only MCP resources
- Episodic indexing: model turn sequences as causal chains

---

## Other Notable Projects

| Project | Stars | Key Idea |
|---------|-------|----------|
| [MiroFish](https://github.com/666ghj/MiroFish) | 4.2k | Multi-agent swarm simulation engine |
| [EverMemOS](https://github.com/EverMind-AI/EverMemOS) | 2.2k | Long-term memory OS across LLMs/platforms |
| [semantica](https://github.com/Hawksight-AI/semantica) | 703 | Semantic layers for decision intelligence |
| [honcho](https://github.com/plastic-labs/honcho) | 365 | Peer-centric entity memory; FastAPI + pgvector; async "deriver" |
| [AgentChat](https://github.com/Shy2593666979/AgentChat) | 362 | LLM agent communication platform with integrated memory |
| [eion](https://github.com/eiondb/eion) | 143 | Go-based shared memory for multi-agent; PostgreSQL + Neo4j; 8 MCP tools |
| [lucid-memory](https://github.com/JasonDocton/lucid-memory) | 116 | Local persistent memory for AI agents (TypeScript) |
| [Squirrel](https://github.com/hakoniwaa/Squirrel) | 92 | Minimal Rust binary; AI-delegated storage; git hooks |
| [nowledge-mem](https://github.com/nowledge-co/nowledge-mem) | 84 | Lightweight memory/context manager |

Curated lists: [Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory) (379), [Awesome-Agent-Memory](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory) (238), [Awesome-Efficient-Agents](https://github.com/yxf203/Awesome-Efficient-Agents) (174), [Awesome-GraphMemory](https://github.com/DEEP-PolyU/Awesome-GraphMemory) (142).

---

## Cross-Project Themes

1. **Knowledge Graph Integration** (MemOS, mcp-memory-service, eion, shodh-memory) — Beyond flat sequences → typed relationships, entity extraction, causality tracking.

2. **Hybrid Search** (mcp-memory-service, memsearch, shodh-memory) — BM25 keyword + dense vector semantic + reciprocal rank fusion for reranking.

3. **Async/Background Processing** (memU, MemOS, honcho, ACE) — Don't block capture; workers compute assessments, consolidate, synthesize in the background.

4. **Memory Consolidation/Decay** (memU, mcp-memory-service, MemOS, shodh-memory) — Compress old memories via decay algorithms, semantic clustering, summarization.

5. **Multi-Agent Coordination** (honcho, eion, mcp-memory-service, memsearch) — Cross-agent visibility with proper scoping/permissions; team-level patterns.

6. **MCP as Standard Interface** (eion, Squirrel, mcp-memory-service, cursor10x-mcp) — Position systems as MCP servers for framework agnosticism.

7. **Temporal/Evolution Tracking** (MemOS, eion, honcho, ACE, shodh-memory) — How memories and patterns evolve over time; when decisions changed.

---

## EntireContext Differentiators

What EntireContext does uniquely vs. these projects:

1. **Git-anchored time-travel** — Memories bound to commits, branches, diffs; rewind to any git state
2. **Checkpoint isolation** — Explicit snapshots vs. continuous streams
3. **Claude Code hooks native integration** — Direct stdin/stdout pipeline, not generic MCP only
4. **Per-repo + global hybrid storage** — Natural hierarchy without separate "cubes" or "workspaces"

---

## Roadmap Candidates by Tier

### Tier 1 — High ROI, Fast Adoption
- Hybrid search (FTS5 + semantic embeddings + RRF reranking)
- Typed relationships for assessments (causes, fixes, contradicts)
- MCP tool standardization (consistent memory/knowledge interface)

### Tier 2 — Medium Effort
- Async assessment workers (background analysis without blocking capture)
- Memory consolidation/decay (compress old turns preserving signal)
- Multi-provider LLM support (OpenAI, Gemini for analysis tasks)
- Markdown export (session summaries → git-friendly sharing)

### Tier 3 — High Effort, High Value
- Knowledge graph layer (git entities → nodes, relations → edges)
- Temporal entity tracking (agent skill/pattern evolution)
- Natural-language feedback UI for refining auto-assessments
- PostgreSQL backend option for scale beyond single SQLite

### Tier 4 — Long-Term Exploration
- Code AST-based semantic search
- Spreading activation (chained turn retrieval via git relationships)
- Multi-agent session graphs
- Interactive visualization dashboard
