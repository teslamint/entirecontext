# Lessons Learned

_Generated from 10 assessed changes._

## 🟢 Expand (increases future options)

### ✅ MCP 입력 정규화와 FTS 오류 처리를 안정화해 에이전트가 검색·결정 도구를 더 예측 가능하게 사용할 수 있게 하므로 future option을 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 루프인 capture -> distill -> retrieve -> intervene 중 retrieve/intervene 품질을 직접 개선한다. 새 제품 표면이나 스키마를 늘리지 않고, agent-facing MCP 도구의 실패 모드를 줄여 decision memory 재사용 가능성을 높인 점에서 v0.5.0의 안정화 방향과도 맞고, 이후 v0.6.0 outcome semantics 작업의 기반을 방해하지 않는다.

**Suggestion:** Keep: MCP 경계에서 scalar repos, '*', list-shaped fields를 관대하게 받아들이는 방향과 FTSQueryError로 쿼리 오류를 명시화한 점. Tidy: 여러 MCP tool에 반복된 `repos is not None and repos != ''` 분기와 normalize 호출을 `runtime`의 단일 helper로 모아 wildcard/empty-list 의미가 다시 갈라지지 않게 하라. Reconsider: `rejected_alternatives`에 dict를 그대로 허용하는 것은 v0.6.1 rejected-alternative normalization과 맞물리므로, 관대한 입력 수용은 유지하되 core 저장 전 구조 검증/정규화 경계를 명확히 두는 것이 좋다.

**Feedback:** agree — MCP input normalization reduces agent-facing failure modes; rejected_alternatives dict-passthrough issue correctly flagged for v0.6.1 normalization

_Assessment: c3efff0c | 2026-04-27T05:09:41.038581+00:00_ 

### ✅ 세션 고정 MCP 검색, PostToolUse 기반 결정 surfacing, 선택 telemetry 보강으로 과거 결정이 실제 편집 순간에 재등장할 가능성을 높여 향후 agent 판단 옵션을 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 루프인 capture -> distill -> retrieve -> intervene 중 retrieve/intervene를 직접 강화하며, 특히 Exploration의 Proactive Decision Injection과 v0.3~v0.4의 retrieval telemetry/selection_id 흐름에 잘 맞는다; 검토한 관련 결정은 v0.6.0 범위 결정(743ebcb2, 77b44176)과 v0.5.0 hardening 결정(4c7893b0, 03ab3e25)이며, 스키마/outcome semantics 확장 없이 surfacing 정확도와 세션 격리를 보강하므로 충돌은 없어 보인다.

**Suggestion:** 유지할 것은 session_id override 격리, read-only 도구 short-circuit, exact-match fast path, selection_id 포함 telemetry다; 다음 tidy는 hook과 MCP에 흩어진 surfacing 정책, fallback 파일 관리, session metadata JSON patch, telemetry 기록을 작은 공유 서비스로 모아 중복과 암묵 상태를 줄이는 것이다; LESSONS.md의 기존 교훈은 '공유 helper로 정책 divergence 방지' 쪽이 적용된다.

**Feedback:** agree — Decision hooks + MCP surfacing directly strengthens retrieve/intervene; session_id isolation and telemetry selection_id are key to loop closure

_Assessment: 69228644 | 2026-04-27T05:09:40.291239+00:00_ 

### ✅ 연결 수명 관리와 릴리스 검증을 정리해 ResourceWarning/누수 위험을 줄이고, 이후 결정 메모리 기능을 더 안전하게 확장할 수 있는 기반 옵션을 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 wedge인 decision-memory loop를 직접 깊게 하지는 않지만, capture/hooks/CLI/MCP 기반의 신뢰성과 배포 안전성을 높여 'strong git grounding for trust, auditability, and rewindability' 및 Done Foundations 운영 안정화에 잘 맞는다.

**Suggestion:** RepoContext/GlobalContext 컨텍스트 매니저와 릴리스 게이트는 유지하되, 반복된 수동 try/finally 연결 정리는 점진적으로 with RepoContext 패턴으로 더 모아라; CLI·hook 조기 return/예외 경로에서 close가 보장되는 회귀 테스트를 보강하면 이 tidy가 더 확실한 옵션 확장으로 남는다.

**Feedback:** agree — v0.2.0 release prep: connection lifetime management and release gates reduce ResourceWarning risk and stabilize the deployment foundation

_Assessment: 4fbe6465 | 2026-04-27T05:09:26.385266+00:00_ 

### ✅ 현재 변경 파일, diff, assessment, commit 신호로 관련 결정을 랭킹해 과거 판단이 다음 코드 변경 시점에 재등장할 가능성을 높이므로 미래 선택지를 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 루프인 capture -> distill -> retrieve -> intervene 중 retrieve/intervene를 직접 강화하며, generic memory 확장보다 decision memory wedge에 맞는다; 특히 v0.2의 proactive retrieval 및 이후 v0.4 F3 ranking weight config의 기반이 되는 변화다.

**Suggestion:** candidate-first multi-signal ranking, score_breakdown, 회귀 테스트는 유지하되, decisions.py에 커진 랭킹 휴리스틱과 하드코딩 weight는 별도 ranking 모듈/설정으로 분리하는 것이 좋다; FTS 예외를 광범위하게 삼키는 경로와 fallback recent padding은 관측 가능하게 만들어 랭킹 품질 디버깅 옵션을 남겨라.

**Feedback:** agree — Ranking weight config + multi-signal scoring in decisions.py is the foundation for Proactive Decision Injection; hardcoded weights extracted correctly

_Assessment: fea07b4e | 2026-04-27T05:09:13.716317+00:00_ 

### ✅ 결정 검색, stale/contradicted 필터링, outcome 기록, hook 기반 proactive surfacing, MCP/CLI 표면과 테스트를 추가해 coding-agent decision memory의 재사용 경로를 크게 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 thesis인 capture -> distill -> retrieve -> intervene 중 retrieve/intervene를 강화하며, v0.2.0의 first-class decision model, proactive retrieval, staleness/contradiction handling과 직접 정렬된다. 다만 v0.6.0의 refined/replaced outcome semantics 자체는 아직 구현하지 않는 변경으로 보인다.

**Suggestion:** 유지할 것은 config-gated hook 동작과 selection_id 기반 telemetry, 넓은 회귀 테스트다. 다음 tidy 대상은 hooks/decision_hooks.py와 core/decisions.py에 퍼진 staleness/outcome/surfacing 정책을 작은 공유 policy 함수로 모으고, v0.6 schema v14 전에 outcome truth table을 한 곳에서 검증하게 만드는 것이다.

**Feedback:** agree — Proactive retrieval with multi-signal ranking is core to the retrieve/intervene loop; aligns with v0.3 E4 and Proactive Decision Injection roadmap item

_Assessment: 49c852ae | 2026-04-27T05:09:09.089900+00:00_ 

### ✅ 변경은 decision/rejected-alternative 처리와 CLI/MCP 노출, 회귀 테스트를 보강해 향후 decision memory 품질 개선 옵션을 넓힌다.

**Roadmap alignment:** v0.6.1의 rejected-alternative quality 항목과 강하게 맞고, decision memory wedge에는 부합하지만 v0.6.0의 outcome semantics breaking track 자체를 직접 진전시키지는 않는다.

**Suggestion:** 정규화 로직은 core에 단일 진실로 유지하고 CLI/MCP는 얇게 두어라; 기존 기록을 묵시적으로 변형하거나 rationale을 생성하지 않는지 계속 검증하고, README와 agent template 변경은 현재 실행 가능한 명령만 present tense로 남겨라.

**Feedback:** agree — Lesson guidance + decision search tightens the distill step; rejected-alternative quality direction matches v0.6.1 scope

_Assessment: bd7df7b7 | 2026-04-27T05:08:50.632894+00:00_ 

### ✅ decision 후보 추출, 검토, MCP/CLI 노출, schema v13 기반 후보 테이블을 추가해 raw history에서 검토 가능한 decision memory로 넘어가는 선택지를 크게 넓힌다.

**Roadmap alignment:** 로드맵의 핵심 루프인 capture -> distill -> retrieve -> intervene 중 distill 품질을 강화하며, v0.2.0의 first-class decision model과 v0.3.0 E3 extraction validation/noise gate 방향에 잘 맞는다. 다만 diff 규모와 schema/CLI/MCP/fixture/테스트 동시 확장은 v0.5.0의 'zero new product features, zero schema changes' 안정화 기조와는 맞지 않고, v0.6.1 rejected-alternative 정규화 범위와도 일부 겹칠 가능성이 있다.

**Suggestion:** Keep the decision-candidate pipeline and broad regression tests because they expand the product wedge. Tidy first by separating schema/migration, extraction scoring, candidate confirmation, and CLI/MCP surface into independently reviewable steps; verify the extraction path does not create a second incompatible outcome or supersession mechanism before v0.6.0. Reconsider whether fixture generation belongs in committed scripts or test-only utilities, and ensure CLAUDE.md generated-doc changes come from AGENTS.md rather than direct edits.

**Feedback:** agree — Decision extraction + schema v13 — valid EXPAND; FTS triggers and schema migration are foundational for decision memory depth

_Assessment: 134621fa | 2026-04-27T05:07:55.149737+00:00_ 

### ✅ This change expands future options by adding both manual and hook-based checkpoint creation with shared git helpers while keeping heavier snapshot capture optional and reversible.

**Roadmap alignment:** It aligns well with the roadmap’s capture automation direction (hook/trigger-based flow for futures/lessons) and partially advances the upcoming lightweight-checkpoint goal by defaulting to git-ref metadata unless `--snapshot` is explicitly requested.

**Suggestion:** Keep the new `core/git_utils.py` extraction, but tidy next by unifying CLI and session-end checkpoint logic behind one shared checkpoint service (including diff-base selection and metadata merge behavior) so future trigger types can be added without duplicating policy or silently diverging.

_Assessment: 84288d4f | 2026-02-20T10:48:16.009213+00:00_ 

### ✅ Introducing a pluggable LLM backend with a CLI `--backend` option increases reversibility and execution options for futures assessment, though IDE-specific files add minor portability drag.

**Roadmap alignment:** Strongly aligned with `Now` (futures assessment delivery) and creates a useful foundation for `Next` items like GitHub Action triggers and MCP-based self-evaluation by decoupling assessment from a single provider.

**Suggestion:** Keep the `core.llm` abstraction and `--backend` wiring, but tidy by isolating/removing committed `.idea` project-specific files and adding backend capability checks plus a small contract test for `get_backend(...).complete(...)` to prevent silent runtime divergence across providers.

_Assessment: dd6184a2 | 2026-02-20T08:51:22.221135+00:00_ 

## 🟡 Neutral

### ✅ 릴리스 커밋의 closing reference를 기준으로 GitHub 이슈를 자동 종료해 운영 마찰은 줄이지만, 결정 메모리 루프 자체의 선택지를 크게 넓히거나 좁히지는 않는다.

**Roadmap alignment:** v0.6.0의 outcome semantics나 decision-memory wedge와 직접 연결되지는 않으며, v0.5.0 이후의 운영 안정화 성격에 가까운 주변 자동화다; 검토한 기존 결정들은 v0.6.0 범위 축소와 v0.5.0 hardening 원칙이었고, 이 변경은 그 방향을 위반하지는 않지만 핵심 로드맵을 전진시키지도 않는다.

**Suggestion:** 스크립트가 .github/scripts에 격리되고 파서 테스트가 있는 점은 유지하되, 자동 close가 태그 커밋 메시지 형식에 강하게 의존하므로 dry-run/로그 가시성, idempotent 재실행, 네트워크 오류 처리, 실제 release workflow에서의 권한 검증을 추가해 릴리스 자동화가 조용히 잘못된 이슈 상태를 만들 가능성을 줄이는 것이 좋다.

**Feedback:** agree — Release scripts + CI harden the deployment pipeline; enabling trust and auditability for the git-grounded memory model

_Assessment: e5d01a13 | 2026-04-27T05:09:05.329211+00:00_ 

