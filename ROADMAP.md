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

- [ ] **세션별 요약 — 사용자 의도 도출** (P1)
  - 현재 `_populate_session_summary()`는 첫 3개 turn의 `assistant_summary` 단순 결합 (max 500자)
  - 세션 종료 시 LLM으로 전체 turn 분석 → 사용자 의도(intent) 추출하여 `session_summary` 갱신
  - 기존 LLM 백엔드 추상화(`openai/codex/claude/ollama/github`) 활용
  - 영향 파일: `hooks/session_lifecycle.py` (`_populate_session_summary`), `core/session.py`
  - config 키: `capture.intent_summary` (opt-in)
  - 테스트: LLM 호출 mock → intent 포함 summary 갱신 확인, config disabled → 기존 동작 유지

- [ ] **코드 변경 없는 세션 자동 정리** (P2)
  - 세션 종료 시 `files_touched`, `git_commit_hash`, checkpoint 유무 검사
  - 코드 변경 없으면 자동 consolidate (메타데이터 보존, content 파일 삭제)
  - 영향 파일: `hooks/session_lifecycle.py` (`on_session_end`), `core/purge.py` 또는 `core/consolidation.py`
  - config 키: `capture.auto_cleanup_no_changes` (default: false)
  - 안전장치: ended session만 대상, active session 보호
  - 테스트: 변경 없는 세션 → content 파일 삭제 확인, 변경 있는 세션 → 미삭제 확인, active session → no-op 확인

- [ ] **세션 종료 시 자동 임베딩 인덱싱** (P1)
  - 현재: `ec index embed` 수동 실행 필요
  - 목표: 세션 종료 hook → async_worker로 턴 데이터 자동 임베딩 + FTS 인덱스 갱신
  - `hooks/session_lifecycle.py` → 인덱싱 이벤트 발행
  - `core/async_worker.py` → 임베딩 태스크 처리
  - config 키: `index.auto_embed` (default: true)
  - 참고: "Grep Is Dead" (QMD hybrid search) — BM25+semantic 자동화가 검색 품질 핵심

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
- **Temporal/meta query** — "지난 주에 뭐 했지?", "실행 안 한 아이디어" 같은 자연어 시간/메타 쿼리 지원

## References
- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
