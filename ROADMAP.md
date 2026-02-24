# EntireContext Roadmap

_Updated against codebase on 2026-02-24._

## Now

- [ ] **PostCommit hook → checkpoint 생성** (P0, spec §10 #1)
  - `hooks/handler.py`: `PostCommit` dispatcher 엔트리 추가 → active session 있으면 checkpoint 생성
  - `core/checkpoint.py`: hook context에서 호출 가능하도록 진입점 확인
  - 영향 파일: `hooks/handler.py`, `core/checkpoint.py`
  - 테스트: active session 시 checkpoint 생성 확인, session 없을 때 no-op 확인

## Next (1-2 weeks)

- [ ] **pre-push config 게이팅** (P1, spec §10 #2)
  - `.git/hooks/pre-push`가 항상 `ec sync` 호출 → config 키(`sync.auto_sync_on_push` 등)로 게이팅
  - 영향 파일: `hooks/handler.py` (또는 pre-push hook script), config schema
  - 테스트: config disabled → sync 미실행, config enabled → sync 실행

- [ ] **`--no-filter` 런타임 연결** (P1, spec §10 #3)
  - CLI에서 `--no-filter` 수용하지만 exporter 경로에 미전달 → filtering bypass 실제 적용
  - 영향 파일: `cli/sync_cmds.py`, `core/export.py`, `core/security.py`
  - 테스트: 동일 입력에서 기본=redacted, `--no-filter`=unredacted 출력 검증

- [ ] **MCP hybrid search 지원** — `ec_search` 도구의 `search_type`에 `"hybrid"` 옵션 추가
- [ ] **MCP AST search 도구** — `ec_ast_search` 도구 노출 (symbol_type, file_path 필터)
- [ ] **MCP knowledge graph 도구** — `ec_graph` 도구 노출 (session/since 필터)
- [ ] **MCP dashboard 도구** — `ec_dashboard` 도구 노출 (since/limit 필터)
- [ ] **MCP spreading activation 도구** — `ec_activate` 도구 노출 (turn/session/hops 파라미터)

## Later (1-3 months)

- [ ] **Sync merge/retry 정책 정비** (P2, spec §10 #4)
  - `sync/merge.py`에 merge helpers 존재하지만 `sync/engine.py`에서 미사용
  - 선택지: app-level merge/retry 루프 구현 또는 docs/README에 정책 축소 명문화
  - 영향 파일: `sync/engine.py`, `sync/merge.py`, docs
  - 테스트: 선택한 정책의 구현/문서 일관성 검증

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
- [x] typed relationships for assessments (`causes`/`fixes`/`contradicts`)
- [x] 마크다운 export (세션 요약 → git-friendly 공유)
- [x] futures 결과 리포트 템플릿/주기 실행 정리 (팀 공유 가능한 형태)
- [x] assessment 기반 자동 tidy PR 제안 (룰 기반)
- [x] 하이브리드 검색 (FTS5 + RRF reranking)
- [x] 팀 대시보드로 전체 컨텍스트 모니터링 (세션/체크포인트/assessment 트렌드)
- [x] 비동기 assessment 워커 (캡처 차단 없는 백그라운드 분석)
- [x] knowledge graph 레이어 (git entities → nodes, relations → edges)
- [x] memory consolidation/decay (오래된 turn 압축 전략)
- [x] 코드 AST 기반 semantic search
- [x] spreading activation (관련 turn 연쇄 탐색)
- [x] multi-agent 세션 그래프

## Exploration

- **Proactive checkpoint** — 코드 변경 패턴 기반 자동 체크포인트 시점 결정
- **NL feedback loop** — 자연어 피드백으로 assessment 품질 자동 개선
- **Pluggable graph backend** — SQLite knowledge graph → Neo4j 등 외부 그래프 DB 선택적 교체

## References
- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
