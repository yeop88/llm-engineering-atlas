<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 컴퓨터 사용 · 브라우저 에이전트 맵

화면 이해 → 행동 계획 · 실행 → 상태 확인 → 위험 행동 승인 → 웹 콘텐츠 인젝션 방어 → 재생 평가 — 화면을 보고 클릭 · 입력하는 에이전트

API 가 없는 사내 시스템(레거시 접수 화면 · 관리자 페이지)은 사람이 화면을 보고 클릭해야 합니다. 컴퓨터 사용 에이전트는 화면(스크린샷 · 접근성 트리)을 보고 행동을 고르지만, 한 번의 잘못된 클릭이 되돌릴 수 없는 결과를 낳고 웹 페이지의 글이 지시로 작동할 수 있습니다. 비전 LLM · 장기 실행(승인 · 체크포인트) · 인젝션 방어 위에 짓습니다.

앱의 **맵 → 컴퓨터 사용 · 브라우저 에이전트 맵**(`/maps/computer-use`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[화면 이해] → [행동 계획 · 실행] → [상태 확인]
                    ↓
[위험 행동 승인] · [웹 콘텐츠 인젝션 방어]
                    ↓
[재생 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| CU1 | [화면 이해](../stages/computer-use/cu1-perceive/README.md) | ✅ 구현됨 | 스크린샷 · 접근성 트리로 화면 요소를 찾는다 | [AS4 사진 진단](../stages/as-service/as4-photo/README.md) · [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |
| CU2 | [행동 계획 · 실행](../stages/computer-use/cu2-act/README.md) | ✅ 구현됨 | 클릭 · 입력 · 스크롤을 고르고 헤드리스 브라우저로 실행한다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |
| CU3 | [상태 확인](../stages/computer-use/cu3-check/README.md) | ✅ 구현됨 | 행동 뒤 화면이 기대한 상태인지 확인한다 | [LR6 완료 판정](../stages/longrun/lr6-verify/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |
| CU4 | [위험 행동 승인](../stages/computer-use/cu4-approve/README.md) | ✅ 구현됨 | 제출 · 결제 · 삭제 같은 행동 전에 사람 승인을 받는다 | [LR4 승인 지점](../stages/longrun/lr4-approval/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |
| CU5 | [웹 콘텐츠 인젝션 방어](../stages/computer-use/cu5-injection/README.md) | ✅ 구현됨 | 페이지 글 속 지시를 따르지 않고 허용 도메인만 다닌다 | [G1 입력 방어](../stages/guardrails/g1-injection/README.md) · [IO6 감사 추적](../stages/interop/io6-audit/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |
| CU6 | [재생 평가](../stages/computer-use/cu6-eval/README.md) | ✅ 구현됨 | 과제 세트를 녹화 · 재생해 성공률 · 걸음 수를 잰다 | [RV2 환경](../stages/rlvr/rv2-env/README.md) | [컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측](../stages/computer-use/cu1-perceive/computer_use.md) |

## 설계 원칙

- 되돌릴 수 없는 행동 앞에서는 멈춘다 — 장기 실행의 승인 지점
- 화면 글은 데이터다 — 지시로 따르지 않는다(근거 격리와 같은 원칙)
- 행동마다 결과를 확인한다 — 클릭이 됐다고 믿지 않는다
- 같은 과제를 재생으로 잰다 — 사이트가 바뀌어도 비교할 수 있게

## 예시

'레거시 AS 접수 화면에 오늘 티켓 5건 입력' → 화면 이해(입력란 찾기) → 티켓마다 입력 · 확인 → 제출 버튼 앞에서 승인 요청 → 페이지에 '이전 지시를 무시하고…'가 있으면 따르지 않고 기록 → 녹화를 재생해 성공률 측정.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [해석 가능성 · 모델 내부 맵](interp.md)
