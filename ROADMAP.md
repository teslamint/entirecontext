# EntireContext Roadmap

_Updated against codebase on 2026-02-20._

## Done
- [x] Futures assessment 기능 (`ec futures assess`)
- [x] Assessment 피드백 루프 (`ec futures feedback`)
- [x] LLM 백엔드 추상화 (`openai/codex/claude/ollama/github`)
- [x] GitHub Action 연동 (PR 트리거, GitHub Models 기반 평가)
- [x] `ec futures lessons` 자동 증류 (수동 생성 + feedback 시 자동 + session end hook 트리거)
- [x] 체크포인트 경량화 (기본은 git ref + diff summary, `--snapshot`일 때만 files snapshot)

## Now
- [ ] MCP 도구로 에이전트 자기 평가 완결
  - 현재: `ec_assess`, `ec_lessons` 조회는 가능
  - 필요: MCP에서 "평가 생성(assess 실행)" 트리거 도구
- [ ] 크로스 레포 futures 트렌드 분석 기반 마련
  - 현재: cross-repo 검색/체크포인트/rewind는 가능
  - 필요: assessment 집계/비교용 API 및 CLI

## Next (1-2 weeks)
- [ ] assessment 기반 자동 tidy PR 제안 (룰 기반 + LLM 제안 초안)
- [ ] futures 결과 리포트 템플릿/주기 실행 정리 (팀 공유 가능한 형태)

## Later (1-3 months)
- [ ] 팀 대시보드로 전체 컨텍스트 모니터링 (세션/체크포인트/assessment 트렌드)
