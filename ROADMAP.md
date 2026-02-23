# EntireContext Roadmap

_Updated against codebase on 2026-02-23 (TDD implementation: code AST-based semantic search)._

## Done
- [x] Futures assessment 기능 (`ec futures assess`)
- [x] Assessment 피드백 루프 (`ec futures feedback`)
- [x] LLM 백엔드 추상화 (`openai/codex/claude/ollama/github`)
- [x] GitHub Action 연동 (PR 트리거, GitHub Models 기반 평가)
- [x] `ec futures lessons` 자동 증류 (수동 생성 + feedback 시 자동 + session end hook 트리거)
- [x] 체크포인트 경량화 (기본은 git ref + diff summary, `--snapshot`일 때만 files snapshot)
- [x] 콘텐츠 필터링 3-layer 시스템 (캡처 차단, 조회 시 redaction, 사후 purge)
- [x] `ec purge session/turn/match` CLI (dry-run 기본, `--execute`로 삭제)
- [x] per-session/global 캡처 토글 (`auto_capture`, `metadata.capture_disabled`)
- [x] MCP 도구로 에이전트 자기 평가 완결 (`ec_assess_create`, `ec_assess`, `ec_lessons`, `ec_feedback`)
- [x] 크로스 레포 futures 트렌드 분석 기반 마련
  - `cross_repo_assessments()` — 레포 전체 assessment 집계 (verdict/since/limit 필터)
  - `cross_repo_assessment_trends()` — 레포별/전체 verdict 분포 및 feedback 통계
  - `ec futures trend` CLI — 크로스 레포 assessment 트렌드 테이블 출력
  - `ec_assess_trends` MCP 도구 — 에이전트용 트렌드 조회 인터페이스
- [x] typed relationships for assessments (`causes`/`fixes`/`contradicts`)
  - `assessment_relationships` 테이블 (DB schema v4, 자기참조 방지 CHECK 제약)
  - `add_assessment_relationship()`, `get_assessment_relationships()`, `remove_assessment_relationship()` in `core/futures.py`
  - `ec futures relate <src> <type> <tgt>` — 관계 생성 (prefix ID 지원, `--note` 옵션)
  - `ec futures relationships <id>` — 관계 목록 (`--direction` outgoing/incoming/both)
  - `ec futures unrelate <src> <type> <tgt>` — 관계 삭제
  - 24 TDD 테스트 (prefix ID, 자기참조 방지, 방향 필드 포함)
- [x] 마크다운 export (세션 요약 → git-friendly 공유)
  - `export_session_markdown()` in `core/export.py` — YAML frontmatter + Markdown 섹션 생성
  - YAML 안전 escaping (`_yaml_scalar`), 멀티라인 blockquote (`_blockquote`), inline 정규화 (`_inline_safe`)
  - `ec session export <id> [--output FILE]` CLI 명령 (prefix ID 지원, 파일 미지정 시 stdout)
  - 48 TDD 테스트 (helper 함수, 코어 로직, CLI 커맨드 포함)
- [x] futures 결과 리포트 템플릿/주기 실행 정리 (팀 공유 가능한 형태)
  - `generate_futures_report()` in `core/report.py` — YAML frontmatter + verdict distribution + per-assessment detail + feedback summary
  - YAML-safe scalar quoting, unknown verdict normalisation, consistent 100% totals
  - `list_assessments()` 에 `since` SQL 필터 파라미터 추가 (LIMIT 전에 적용)
  - `ec futures report [--since DATE] [--limit N] [--output FILE]` CLI 명령
  - 30 TDD 테스트 (core 함수, CLI 명령, 엣지 케이스 포함)

## Now

## Next (1-2 weeks)
- [x] assessment 기반 자동 tidy PR 제안 (룰 기반)
  - `collect_tidy_suggestions()` — narrow verdict + tidy_suggestion 필터 (since/limit 지원)
  - `score_tidy_suggestions()` — agree feedback 보정 점수, 내림차순 정렬
  - `generate_tidy_pr()` in `core/tidy_pr.py` — YAML frontmatter + Markdown PR 초안
  - `ec futures tidy-pr [--since DATE] [--limit N] [--output FILE]` CLI 명령
  - 24 TDD 테스트 (collect/score/generate 코어, CLI 명령 포함)
- [x] 하이브리드 검색 (FTS5 + RRF reranking)
  - `core/hybrid_search.py`: `rrf_fuse()` (Reciprocal Rank Fusion, Cormack 2009), `hybrid_search()`
  - Two-signal fusion: FTS5 relevance rank × recency rank (timestamp DESC) over identical candidate set
  - `_apply_query_redaction` re-uses shared helper from `search.py` (no duplication)
  - File-filter multiplier (10×) compensates for post-SQL Python-side trimming in `_fts_search_turns`
  - `ec search <query> --hybrid [--limit N] [--since DATE] [--file PATH] ...` CLI
  - Cross-repo fallback to FTS5 with explicit warning; mutual-exclusion guard for `--fts/--hybrid/--semantic`
  - 26 TDD 테스트 (rrf_fuse unit, hybrid_search integration, CLI assertions including conn passthrough)

## Later (1-3 months)
- [ ] 팀 대시보드로 전체 컨텍스트 모니터링 (세션/체크포인트/assessment 트렌드)
- [x] 비동기 assessment 워커 (캡처 차단 없는 백그라운드 분석)
  - `core/async_worker.py`: `launch_worker()`, `stop_worker()`, `is_worker_running()`, `worker_status()`
  - PID file at `.entirecontext/worker.pid`; `start_new_session=True` detaches worker from parent TTY
  - `stop_worker()` returns `"killed"` / `"stale"` / `"none"` — accurate status distinguishes SIGTERM-sent from stale-cleanup
  - `PermissionError` propagates from `stop_worker` so caller knows signal was blocked
  - `ec futures worker-status` / `worker-stop` / `worker-launch [--diff TEXT]` CLI commands
  - 33 TDD 테스트 (PID file, process checks, launch, stop, status, CLI commands)
- [x] knowledge graph 레이어 (git entities → nodes, relations → edges)
  - `core/knowledge_graph.py`: `build_knowledge_graph()`, `get_graph_stats()`
  - 6 node types: `session`, `turn`, `commit`, `file`, `agent`, `checkpoint` — all derived from existing DB tables (no new subprocess calls)
  - 6 edge relations: `contains`, `committed_via`, `touched`, `ran_session`, `anchors_commit`, `has_checkpoint`
  - Edge deduplication via set; `since` (inclusive) and `session_id` filters; `limit` on turns
  - `ec graph [--session ID] [--since DATE] [--limit N]` CLI — Rich tables for nodes/edges by type
  - 34 TDD 테스트 (node types, edge types, deduplication, filters, stats, CLI)
- [x] memory consolidation/decay (오래된 turn 압축 전략)
  - `core/consolidation.py`: `find_turns_for_consolidation()`, `consolidate_turn_content()`, `consolidate_old_turns()`
  - DB schema v5: `turns.consolidated_at TEXT` column + index; idempotent migration via callable check
  - path-traversal protection (`_safe_content_path`), DB-first atomic ordering, per-turn OSError isolation
  - `ec session consolidate [--before DATE] [--session ID] [--limit N] [--execute]` (dry-run by default)
  - 28 TDD 테스트 (find, single-turn consolidation, batch, CLI)

## Exploration
- [x] 코드 AST 기반 semantic search
  - `core/ast_index.py`: `extract_ast_symbols()`, `index_file_ast()`, `get_ast_symbols_for_file()`, `search_ast_symbols()`
  - Python `ast` module parsing: functions, classes, methods (async included), nested classes (recursive)
  - Full-qualified names (`ClassName.method`), docstrings, decorator names (module-qualified), line ranges
  - Schema v6: `ast_symbols` table + `fts_ast_symbols` FTS5 virtual table + 3 sync triggers
  - `search_ast_symbols()` uses FTS5 JOIN with `symbol_type` and `file_path` filters; phrase-quoted queries
  - `ec ast-search <query> [--type function|class|method] [--file PATH] [--limit N]` CLI
  - 46 TDD 테스트 (extract, index, search, filter, nested class, async method, CLI)
- [x] spreading activation (관련 turn 연쇄 탐색)
  - `core/activation.py`: `spread_activation()` — BFS graph traversal through shared `files_touched`/`git_commit_hash` edges
  - Jaccard similarity weighting for file overlap, fixed 1.0 weight for commit sharing, per-hop decay
  - Atomic BFS: `visited` merges only after full frontier pass (prevents same-hop neighbour underscoring)
  - `NOT IN ()` guard for empty `exclude_ids` (avoids SQLite syntax error)
  - `ec session activate [--turn ID] [--session ID] [--hops N] [--limit N]` CLI
  - 20 TDD 테스트 (core traversal, multi-hop, limit, CLI assertions including conn passthrough)
- [x] multi-agent 세션 그래프
  - `core/agent_graph.py`: `create_agent()`, `get_agent()`, `get_agent_sessions()`, `get_session_agent_chain()`, `build_agent_graph()`
  - BFS downward traversal through `agents.parent_agent_id` edges; depth-limited with cycle guard
  - `get_agent()` supports exact + prefix lookup with LIKE wildcard escaping
  - `get_session_agent_chain()` walks agent ancestry leaf→root for a given session
  - `build_agent_graph()` returns `{nodes, edges}` with `session_count` per node; seeds by `root_agent_id` or `session_id`
  - `ec session graph [--agent ID] [--session ID] [--depth N]` CLI — Rich Tree display (iterative BFS)
  - 39 TDD 테스트 (create/get/sessions/chain/graph core, CLI assertions, wildcard-escape edge cases)

## References
- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
