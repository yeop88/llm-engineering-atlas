<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 추론 모델 · 테스트 시간 연산 맵

생각 예산 → 생각할지 말지 라우팅 → 여러 번 풀고 고르기 → 검증기 · 과정 보상 → 생각 과정 검사 → 추론 증류 — 생각하는 LLM 을 서비스에 쓰는 흐름

추론 모델은 답 전에 긴 '생각'을 써서 어려운 문제의 정확도를 올리지만 토큰 · 지연이 몇 배로 늡니다. 이 PC 처럼 생성이 초당 13 토큰이면 생각 2,000 토큰이 2분 반입니다. 언제 · 얼마나 생각하게 할지, 여러 답 중 무엇을 고를지를 실측으로 정하는 맵입니다. 생각 끄기 설정(LLM_DISABLE_THINKING) · Best-of-N · 검증 가능한 보상(RLVR)이 출발점입니다.

앱의 **맵 → 추론 모델 · 테스트 시간 연산 맵**(`/maps/reasoning`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[생각 예산] → [생각할지 말지 라우팅]
                    ↓
[여러 번 풀고 고르기] → [검증기 · 과정 보상]
                    ↓
[생각 과정 검사] → [추론 증류]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| RS1 | [생각 예산](../stages/reasoning/rs1-budget/README.md) | ✅ 구현됨 | 생각 토큰 상한을 바꿔 가며 정답률 · 지연 · 비용 곡선을 잰다 | [S7 예산](../stages/serving/s7-budget/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |
| RS2 | [생각할지 말지 라우팅](../stages/reasoning/rs2-route/README.md) | ✅ 구현됨 | 질문 난이도를 보고 생각 모드 · 예산을 고른다 | [6 라우팅](../stages/llm/6-routing/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |
| RS3 | [여러 번 풀고 고르기](../stages/reasoning/rs3-sampling/README.md) | ✅ 구현됨 | 같은 질문을 여러 번 풀어 다수결 · 점수로 고른다 | [8b 강화학습](../stages/llm/8b-rl/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |
| RS4 | [검증기 · 과정 보상](../stages/reasoning/rs4-verifier/README.md) | ✅ 구현됨 | 답 · 풀이 단계를 검증기로 채점해 고른다 | [RV3 보상 설계](../stages/rlvr/rv3-reward/README.md) · [MA7 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |
| RS5 | [생각 과정 검사](../stages/reasoning/rs5-trace/README.md) | ✅ 구현됨 | 생각과 답이 맞는지, 생각에 근거 밖 사실 · 개인정보가 없는지 본다 | [G4 출력 검사](../stages/guardrails/g4-output/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |
| RS6 | [추론 증류](../stages/reasoning/rs6-distill/README.md) | ✅ 구현됨 | 큰 추론 모델의 풀이로 작은 모델을 학습해 싸게 생각하게 한다 | [7a 지식 증류](../stages/llm/7a-distill/README.md) · [P3 SFT](../stages/posttrain/p3-sft/README.md) | [추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측](../stages/reasoning/rs1-budget/reasoning.md) |

## 설계 원칙

- 생각은 비용이다 — 정답률이 오르는 구간까지만(이 PC 생성 13 토큰/초)
- 고르기는 검증기가 정확한 만큼만 낫다 — Best-of 실측의 보상-품질 짝 비교
- 쉬운 질문은 생각하지 않는다 — 라우팅 실측처럼 질문 난이도로 나눈다
- 생각 과정도 출력이다 — 근거 밖 사실 · 개인정보 검사 대상

## 예시

법률 질문 '임금 체불이 3개월이면 지연이자는?' → 라우터가 조문 결합 · 계산이 필요하다고 판단 → 생각 예산 1,024 토큰으로 5번 풀기 → 조문 번호 · 계산을 검증기로 확인해 다수결 → 생각 과정의 근거 밖 조문 인용 검사 → 같은 유형은 작은 모델에 증류한 풀이로.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
