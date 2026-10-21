<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 장기 실행 에이전트 · 업무 자동화 맵

목표 분해 · 계획 → 실행 · 재계획 → 상태 저장 · 체크포인트 → 사람 승인 → 실패 복구 · 되돌리기 → 결과 검증 → 권한 · 비용 상한 — 며칠짜리 업무를 맡기는 흐름

질문 하나에 답하는 에이전트와 달리, 업무 자동화 에이전트는 며칠에 걸친 작업(자료 수집 → 분석 → 보고서 → 승인 → 발송)을 맡습니다. 상태를 저장해 중단돼도 이어 가고, 되돌릴 수 없는 행동 전에는 사람 승인을 받고, 끝났는지 스스로 판정해야 합니다. 질의응답보다 체크포인트 · 멱등성(같은 작업을 두 번 해도 결과가 같게) · 승인 흐름이 핵심입니다.

앱의 **맵 → 장기 실행 에이전트 · 업무 자동화 맵**(`/maps/longrun`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[목표 분해 · 계획] → [실행 · 재계획]
                                      ↓
[상태 저장 · 체크포인트] → [실패 복구 · 되돌리기]
                                      ↓
[사람 승인 지점] → [결과 검증 · 완료 판정] → [권한 · 비용 상한]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| LR1 | [목표 분해 · 계획](../stages/longrun/lr1-goal/README.md) | ✅ 구현됨 | 큰 목표를 하위 작업 · 의존 관계 · 완료 조건이 있는 계획으로 나눈다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR2 | [실행 · 재계획](../stages/longrun/lr2-replan/README.md) | ✅ 구현됨 | 계획대로 실행하다 막히면 상황을 보고 계획을 고친다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR3 | [상태 저장 · 체크포인트](../stages/longrun/lr3-state/README.md) | ✅ 구현됨 | 작업마다 상태 · 중간 결과를 저장해 서버가 재시작돼도 마지막 체크포인트부터 이어 간다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR4 | [사람 승인 지점](../stages/longrun/lr4-approval/README.md) | ✅ 구현됨 | 되돌릴 수 없는 행동(발송 · 결제 · 삭제) 전에 사람의 승인을 받고, 기다리는 동안 상태를 유지한다 | [LR1 목표 분해](../stages/longrun/lr1-goal/README.md) · [G5 감사 로그](../stages/guardrails/g5-audit/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR5 | [실패 복구 · 되돌리기](../stages/longrun/lr5-recovery/README.md) | ✅ 구현됨 | 실패한 작업을 재시도 · 대체 · 되돌리기 중에서 고르고, 이미 한 행동의 부작용을 정리한다 | [IO4 장기 작업](../stages/interop/io4-longtask/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR6 | [결과 검증 · 완료 판정](../stages/longrun/lr6-verify/README.md) | ✅ 구현됨 | 작업 결과를 완료 조건 · 근거 · 형식으로 검사해 '정말 끝났는지' 판정한다 | [2 RAG](../stages/llm/2-rag/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |
| LR7 | [권한 · 비용 상한](../stages/longrun/lr7-limits/README.md) | ✅ 구현됨 | 작업이 쓸 수 있는 권한 · 자료 · 비용 · 기간을 미리 정하고 넘으면 멈춘다 | [IO5 호출 상한](../stages/interop/io5-limits/README.md) · [G3 권한별 검색](../stages/guardrails/g3-acl/README.md) | [장기 실행 업무 — 계획 · 체크포인트 · 승인 · 복구 · 완료 판정 · 실측](../stages/longrun/lr1-goal/longrun.md) |

## 설계 원칙

- 되돌릴 수 없는 행동은 승인 후에 — 발송 · 결제 · 삭제는 계획과 실행 사이에 사람이 있다
- 중단은 정상이다 — 서버 재시작으로 끊긴 작업을 '중단됨'으로 표시하는 작업 기록처럼, 모든 단계는 이어 하기를 전제로
- 같은 작업을 두 번 해도 안전하게 — 재시도 때 메일이 두 번 가지 않도록 작업 id 로 중복을 막는다
- 완료 판정은 검증으로 — '다 했다'는 에이전트의 말이 아니라 결과 검사(근거 일치 · 형식 · 체크리스트)로

## 예시

'다음 주 월요일까지 지난 분기 AS 문의 동향 보고서': 계획(데이터 수집 → 분류 집계 → 차트 → 초안) → 단계마다 체크포인트 → 초안 완성 후 팀장 승인 대기 → 수정 요청 반영 → 승인되면 발송 · 기록. 중간에 서버가 재시작돼도 마지막 체크포인트부터.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
