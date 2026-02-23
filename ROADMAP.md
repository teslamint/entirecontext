# EntireContext Roadmap

_Updated against codebase on 2026-02-23 (TDD implementation: typed assessment relationships)._

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

## Now

## Next (1-2 weeks)
- [ ] assessment 기반 자동 tidy PR 제안 (룰 기반 + LLM 제안 초안)
- [ ] futures 결과 리포트 템플릿/주기 실행 정리 (팀 공유 가능한 형태)
- [ ] 하이브리드 검색 (FTS5 + semantic embeddings + RRF reranking)

## Later (1-3 months)
- [ ] 팀 대시보드로 전체 컨텍스트 모니터링 (세션/체크포인트/assessment 트렌드)
- [ ] 비동기 assessment 워커 (캡처 차단 없는 백그라운드 분석)
- [ ] knowledge graph 레이어 (git entities → nodes, relations → edges)
- [ ] memory consolidation/decay (오래된 turn 압축 전략)
- [ ] 마크다운 export (세션 요약 → git-friendly 공유)

## Exploration
- [ ] 코드 AST 기반 semantic search
- [ ] spreading activation (관련 turn 연쇄 탐색)
- [ ] multi-agent 세션 그래프

## References
- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
