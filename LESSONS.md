# Lessons Learned

_Generated from 50 assessed changes._

## 🟢 Expand (increases future options)

### ❌ MCP SDK 2.0 마이그레이션이 의도적 stopgap 핀(ADR 0017)을 해소하고, 2.x API 표면과 opentelemetry-api 전이 의존성을 열어 향후 MCP 기능·관찰성 옵션을 확장한다. (097a9837)

**Roadmap alignment:** Hardening Backlog의 등록된 carry-forward 항목을 정확히 완료하며, ADR 0017→0018 승계 체인으로 결정 추적성을 유지한다. Dependabot PR #222가 트리거한 구조적 부채를 해소함으로써 향후 의존성 업데이트 마찰을 제거한다.

**Suggestion:** 유지: MCPServer 임포트 패턴, `<3` 상한 방어 핀, ADR 승계 문서화. 관찰 포인트: opentelemetry-api가 전이 의존성으로 들어왔으므로 v1.0 관찰성 계획 시 활용 여부를 평가할 것. 28개 도구 함수의 데코레이터 패턴(`mcp.tool()(fn)`)은 SDK 2.0에서도 동일하므로 추가 변경 불필요.

**Feedback:** disagree — auto:revised:neutral->expand

_Assessment: 097a9837 | 2026-08-19T02:49:52.943287+00:00_

### ❌ silent-failure-to-observable-error 전환과 stderr 분리가 MCP 통합의 진단 가능성(diagnosability)을 구조적으로 확장한다. (fe167eb5)

**Roadmap alignment:** MCP는 프로덕트 테시스의 핵심 통합 채널(agent frameworks via MCP)이며, `ec mcp serve`가 무음 성공으로 실패를 삼키면 해당 채널 전체가 디버깅 불가능 상태였다. 이 수정은 SDK 2.0 마이그레이션(2ce9805)의 선행 조건을 정리한 것으로, 로드맵의 MCP 의존 경로를 직접 뒷받침한다.

**Suggestion:** stderr 라우팅과 raise-not-return 패턴은 유지할 가치가 있는 구조 개선이다. `mcp>=1.0.0,<2` 핀은 이미 SDK 2.0 마이그레이션(feat(mcp) 2ce9805)으로 대체되었으므로 현재 코드에서 확인 불필요. 향후 MCP 관련 CLI 커맨드를 추가할 때 동일한 stderr-only 원칙을 적용할 것—JSON-RPC stdio 위에서 동작하는 모든 진단 출력은 stdout을 오염시키면 안 된다.

**Feedback:** disagree — auto:revised:neutral->expand

_Assessment: fe167eb5 | 2026-08-19T01:56:50.119156+00:00_

### ✅ docs(retro): record PR #226 ordered reliability backlog (f9c0f284)

**Feedback:** agree — auto:committed

_Assessment: f9c0f284 | 2026-08-17T18:52:20.267583+00:00_

### ✅ feat(decisions): preserve links across committed renames (a5c76b69)

**Feedback:** agree — auto:committed

_Assessment: a5c76b69 | 2026-08-17T03:08:06.864225+00:00_

### ✅ docs(roadmap): refresh measurement gates (deadab45)

**Feedback:** agree — auto:committed

_Assessment: deadab45 | 2026-08-17T03:07:44.015537+00:00_

### ✅ feat(decisions): preserve links across committed renames (dbf3c660)

**Feedback:** agree — The commit intentionally adds the deferred rename-lineage capability while preserving existing query interfaces and hot-path boundaries; expand is the correct roadmap-impact verdict.

_Assessment: dbf3c660 | 2026-08-16T18:05:43.659730+00:00_

## 🟡 Neutral

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (a7e9d326)

**Roadmap alignment:** 코드 변경 없이 현재 상태를 기록하는 체크포인트이므로 로드맵 정렬 판단 불가

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: a7e9d326 | 2026-08-19T11:16:42.321143+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (92ffeb84)

**Roadmap alignment:** 변경 사항이 없으므로 로드맵 정렬 평가 불가. MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태 유지 중

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 92ffeb84 | 2026-08-19T11:15:33.375917+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (b3dca6f5)

**Roadmap alignment:** 변경 사항 없음 — 정렬 판단 불필요

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: b3dca6f5 | 2026-08-19T11:14:42.876889+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (7f8d636a)

**Roadmap alignment:** 변경 사항 없음 — 로드맵 정렬 평가 불필요

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 7f8d636a | 2026-08-19T11:13:54.863890+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (7f8aa99a)

**Roadmap alignment:** 변경 사항이 없으므로 로드맵 정렬 평가 불필요

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 7f8aa99a | 2026-08-19T11:13:23.528721+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (01173974)

**Roadmap alignment:** 변경 사항이 없으므로 로드맵 정렬 평가 대상 아님

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 01173974 | 2026-08-19T11:12:22.277008+00:00_

### ✅ 빈 diff의 자동 체크포인트로, 코드 변경이 없어 미래 옵션에 영향 없음 (55da7bd5)

**Roadmap alignment:** 변경 사항이 없어 로드맵 정렬 평가 불가

**Suggestion:** 변경 사항이 없는 체크포인트입니다. 다음 실질적 변경 시 MCP SDK 2.0 마이그레이션(2ce9805) 이후 안정화 상태와 ROADMAP 미해결 항목을 기준으로 평가하세요.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 55da7bd5 | 2026-08-19T11:11:17.035328+00:00_

### ✅ Release-loop retrospective document that closes the MCP serve silent-failure fix cycle — pure process hygiene that neither expands nor narrows code-level options. (7f8f5874)

**Roadmap alignment:** Directly follows the Retrospective Carry-Forward Rule (AGENTS.md): the retro registered the MCP SDK 2.0 migration in ROADMAP.md before closing, and that carry-forward was subsequently completed in PR #233. The loop discipline is maintained.

**Suggestion:** The retro is clean and well-structured. The three lessons (environmental drift, stdout purity, version-pin policy) are operationally useful but live only in this document — consider promoting lesson #2 (stdout purity for stdio transports) to `docs/solutions/` if MCP transport work recurs, since it's a solved-problem pattern that could save future debugging time. No code tidy needed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 7f8f5874 | 2026-08-19T02:53:51.885944+00:00_

### ✅ ROADMAP carry-forward 항목을 완료 처리하고 ADR 참조를 갱신한 순수 문서 변경으로, 코드 옵션 공간에 직접 영향 없음 (a8151ae4)

**Roadmap alignment:** MCP SDK 2.0 마이그레이션 완료를 ROADMAP에 정확히 반영하며, ADR 0017→0018 승계 참조도 올바르게 연결됨 — carry-forward 정책(retro에서 등록된 deferral은 완료 또는 재등록 필수)을 준수

**Suggestion:** 이 변경 자체는 정리 완료 상태. 후속으로 `mcp>=2.0.0,<3` 핀이 충분히 넓은지 SDK 2.x minor 변경 시 CI가 잡아줄 수 있는지 확인하면 좋겠지만, ROADMAP 업데이트로서는 적절함

**Feedback:** agree — auto:llm-confirmed

_Assessment: a8151ae4 | 2026-08-19T02:49:32.811247+00:00_

### ✅ ADR 0017 documents the MCP extra pin and silent-failure fix decision, preserving diagnostic context for future maintainers without altering code or options. (d0ca0d49)

**Roadmap alignment:** Directly supports the MCP SDK 2.0 migration carry-forward registered in ROADMAP by recording the rationale for the <2 pin and the deferred migration — the migration has since shipped (ADR 0018 / PR #233), so this ADR now serves as historical context.

**Suggestion:** No action needed — the ADR is well-structured and already superseded by ADR 0018. Keep it as-is for decision traceability; do not remove superseded ADRs since they document the reasoning chain that led to the current state.

**Feedback:** agree — auto:llm-confirmed

_Assessment: d0ca0d49 | 2026-08-19T02:43:51.115153+00:00_

### ✅ MCP extra pin과 silent-failure fix 결정을 ADR로 기록해 의사결정 추적성을 확보하되, 코드나 아키텍처 변경 없이 문서만 추가한 커밋이므로 옵션 공간에 실질적 변화 없음. (506e2fac)

**Roadmap alignment:** ROADMAP에 MCP SDK 2.0 마이그레이션이 별도 항목으로 이미 등재되어 있고, 이 ADR은 해당 마이그레이션 전까지의 pin 근거와 silent-failure 수정 근거를 기록한 것으로 로드맵과 정합. ADR 0017이 superseded by ADR 0018(SDK 2.0 마이그레이션)로 이어지는 연쇄가 이미 완료된 상태.

**Suggestion:** ADR 자체는 올바르게 구조화되어 있고 EC Decision ID를 참조해 추적 가능. 별도 조치 불필요. 다만 ADR 0017 Status가 'accepted'로 남아 있는데, SDK 2.0 마이그레이션(ADR 0018)이 완료되어 pin 자체가 해제된 이상 Status를 'superseded (by ADR-0018)'로 갱신하면 문서 정합성이 더 명확해진다.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 506e2fac | 2026-08-19T02:43:20.608513+00:00_

### ✅ fix(plans): Close Markdown contract bypasses (9797be7e)

**Feedback:** agree — auto:committed

_Assessment: 9797be7e | 2026-08-17T17:19:53.979030+00:00_

### ✅ fix(plans): Close parser review bypasses (5fd8c53f)

**Feedback:** agree — auto:committed

_Assessment: 5fd8c53f | 2026-08-17T08:42:29.969262+00:00_

### ✅ fix(plans): Scan specification sections fence-aware (7b269cf5)

**Feedback:** agree — auto:committed

_Assessment: 7b269cf5 | 2026-08-17T06:17:12.150297+00:00_

### ✅ fix(plans): Reject commands in non-shell fences (2bf8e662)

**Feedback:** agree — auto:committed

_Assessment: 2bf8e662 | 2026-08-17T06:11:33.309683+00:00_

### ✅ fix(plans): Close executable contract review gaps (802fe693)

**Feedback:** agree — auto:committed

_Assessment: 802fe693 | 2026-08-17T06:05:33.624391+00:00_

### ✅ fix(plans): Close executable contract review gaps (4e316974)

**Feedback:** agree — auto:committed

_Assessment: 4e316974 | 2026-08-17T06:01:54.022370+00:00_

### ✅ style(futures): apply canonical formatting (a1f67188)

**Feedback:** agree — Neutral is correct: this commit only applies CI-required formatting.

_Assessment: a1f67188 | 2026-08-17T04:22:07.497891+00:00_

### ✅ fix(decisions): preserve explicit state during automation (9d55f63c)

**Feedback:** agree — Neutral is correct: this commit hardens two existing automated persistence paths without expanding product scope.

_Assessment: 9d55f63c | 2026-08-17T04:18:10.309071+00:00_

### ✅ Auto-assessed checkpoint (4fbe0eaf)

**Feedback:** agree — auto:committed

_Assessment: 4fbe0eaf | 2026-08-17T04:17:09.183139+00:00_

### ✅ Auto-assessed checkpoint (3d0aaf91)

**Feedback:** agree — auto:committed

_Assessment: 3d0aaf91 | 2026-08-17T04:17:02.575721+00:00_

### ✅ docs(adr): align policy with ordered stack (ae9ce2fe)

**Feedback:** agree — auto:committed

_Assessment: ae9ce2fe | 2026-08-17T02:23:38.930136+00:00_

### ✅ docs(adr): restore sequential numbering (fd87ae97)

**Feedback:** agree — Neutral is correct: the follow-up only restores the ADR sequence required by docs/adr/README.md without changing the applied branch-protection policy.

_Assessment: fd87ae97 | 2026-08-17T02:19:42.810757+00:00_

### ✅ docs(roadmap): close review-thread merge race (8797fc0e)

**Feedback:** agree — Neutral is correct: the commits document an explicitly authorized GitHub branch-protection policy and close the process backlog item without changing product runtime behavior.

_Assessment: 8797fc0e | 2026-08-17T02:18:37.970315+00:00_

### ✅ Auto-assessed checkpoint (3988434d)

**Feedback:** agree — auto:committed

_Assessment: 3988434d | 2026-08-16T17:54:48.721062+00:00_

### ✅ Auto-assessed checkpoint (777aa5e7)

**Feedback:** agree — auto:committed

_Assessment: 777aa5e7 | 2026-08-16T17:49:07.660253+00:00_

### ✅ docs(roadmap): refresh measurement gates (7aebe58d)

**Feedback:** agree — auto:committed

_Assessment: 7aebe58d | 2026-08-16T17:12:05.298730+00:00_

### ✅ docs(roadmap): refresh measurement gates (5d845fe0)

**Feedback:** agree — The final commit preserves the corrected telemetry math and accurately describes both closure paths; neutral docs-only verdict is correct.

_Assessment: 5d845fe0 | 2026-08-16T17:10:29.034854+00:00_

### ✅ docs(roadmap): refresh measurement gates (a5ccdbaa)

**Feedback:** agree — The amended roadmap content corrects the fixed-denominator versus growing-denominator session arithmetic without changing product behavior.

_Assessment: a5ccdbaa | 2026-08-16T17:10:14.708217+00:00_

### ✅ docs(roadmap): refresh measurement gates (53fccc6f)

**Feedback:** agree — Docs-only telemetry reconciliation accurately records current measured maturity and denominators, closes only the achieved lesson-reuse trend, and keeps the event-based applied-context target open without synthetic data.

_Assessment: 53fccc6f | 2026-08-16T17:09:45.855652+00:00_

### ✅ fix(futures): balance verdict enrichment candidates (40e58cff)

**Feedback:** agree — Commit is a corrective measurement-selection change: it removes neutral-only sampling bias and outcome overwrite risk without adding product scope, so the neutral rule verdict is accurate.

_Assessment: 40e58cff | 2026-08-16T17:07:06.675206+00:00_

### ✅ Auto-assessed checkpoint (b9d7320e)

**Feedback:** agree — auto:committed

_Assessment: b9d7320e | 2026-08-16T17:03:47.895493+00:00_

### ✅ Auto-assessed checkpoint (53c688e0)

**Feedback:** agree — auto:committed

_Assessment: 53c688e0 | 2026-08-16T16:59:54.994880+00:00_

### ✅ Auto-assessed checkpoint (3385e836)

**Feedback:** agree — auto:committed

_Assessment: 3385e836 | 2026-08-16T16:51:06.620600+00:00_

### ✅ Auto-assessed checkpoint (abc0fb69)

**Feedback:** agree — auto:committed

_Assessment: abc0fb69 | 2026-08-16T16:50:40.261071+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (fd3a051a)

**Roadmap alignment:** Roadmap alignment cannot be established without changed files, behavior, or references to a roadmap item, specification, plan, or decision.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and the governing roadmap, specification, plan, or decision reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: fd3a051a | 2026-08-16T16:47:15.707578+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (b413ee8c)

**Roadmap alignment:** Alignment cannot be established without changed files or a concrete diff linking the checkpoint to a roadmap item, specification, plan, or decision.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and the governing roadmap, specification, plan, or decision reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: b413ee8c | 2026-08-16T16:45:41.463986+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a material expansion or narrowing of future software design options. (8e1dd569)

**Roadmap alignment:** Alignment cannot be established without changed-file or behavioral evidence connecting the checkpoint to a ROADMAP item, specification, plan, or decision.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and the governing roadmap, specification, plan, or decision reference before reassessing reversibility, coupling, and future option value.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 8e1dd569 | 2026-08-16T16:45:40.609000+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (d1a9797e)

**Roadmap alignment:** Alignment with the project roadmap cannot be established without changed files, behavior, or a concrete roadmap reference.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and the relevant roadmap, specification, or decision reference so the next assessment can evaluate reversibility, coupling, and option value.

**Feedback:** agree — auto:llm-confirmed

_Assessment: d1a9797e | 2026-08-16T16:45:21.958774+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a material expansion or narrowing of future software design options. (bca80421)

**Roadmap alignment:** Alignment cannot be established without changed files, a concrete diff summary, or a reference to the governing roadmap item, specification, plan, or decision.

**Suggestion:** Keep the neutral verdict, but attach the concrete diff and its governing roadmap or decision reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: bca80421 | 2026-08-16T16:44:46.501138+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (bfcb0ca8)

**Roadmap alignment:** Alignment cannot be established without a concrete diff or references to the governing roadmap item, specification, plan, or decision.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and governing roadmap reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: bfcb0ca8 | 2026-08-16T16:44:22.424469+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (81fee0f9)

**Roadmap alignment:** Alignment cannot be established without a concrete diff and its governing roadmap, specification, plan, or decision reference.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and governing roadmap reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 81fee0f9 | 2026-08-16T16:44:14.457252+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (a1acc816)

**Roadmap alignment:** Alignment cannot be established without changed files or a concrete diff linking the checkpoint to ROADMAP.md, a specification, plan, or governing decision.

**Suggestion:** Keep the neutral verdict, but attach a concrete diff summary and the governing roadmap, specification, plan, or decision reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: a1acc816 | 2026-08-16T16:44:00.804691+00:00_

### ✅ No diff evidence was provided, so this checkpoint does not demonstrate a change that materially expands or narrows future software design options. (11dcaf43)

**Roadmap alignment:** Alignment cannot be established without a concrete diff summary and a governing roadmap, specification, plan, or decision reference.

**Suggestion:** Keep the neutral verdict, but attach the changed files and behavioral diff plus the relevant roadmap or decision reference so reversibility, coupling, and future option value can be assessed.

**Feedback:** agree — auto:llm-confirmed

_Assessment: 11dcaf43 | 2026-08-16T16:43:57.075002+00:00_

