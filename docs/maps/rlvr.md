<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 강화학습 기반 에이전트 학습 (RLVR) 맵

검증 가능한 과제 → 환경 · 도구 시뮬레이터 → 보상 설계 → 보상 해킹 감시 → 정책 학습(GRPO 등) → 일반화 · 안전성 평가 — 정답을 확인할 수 있는 과제로 에이전트를 학습

RLVR(검증 가능한 보상의 강화학습)은 정답을 자동으로 확인할 수 있는 과제(조문 번호 조회 결과 · 계산 값 · 쿼리 결과)로 보상을 주고, 모델이 도구를 쓰는 방법 자체를 학습하게 합니다. 사람 선호보다 싸고 명확하지만, 모델은 보상을 올리는 지름길(보상 해킹)을 잘 찾습니다. 이 PC 의 Best-of 실측에서 이미 '보상은 유의하게 올랐는데 품질은 불확실'이 보였습니다. 학습은 GPU 가 필수입니다.

앱의 **맵 → 강화학습 기반 에이전트 학습 (RLVR) 맵**(`/maps/rlvr`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[검증 가능한 과제 설계] → [환경 · 도구 시뮬레이터]
                                      ↓
[보상 설계] → [보상 해킹 감시]
                                      ↓
[정책 학습 (GRPO · PPO)] → [일반화 · 안전성 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| RV1 | [검증 가능한 과제 설계](../stages/rlvr/rv1-tasks/README.md) | 🟡 기초 있음 | 정답을 자동으로 확인할 수 있는 과제(조문 조회 · 계산 · 쿼리 결과)를 모아 학습 과제로 만든다 | [E1 평가 세트](../stages/evalops/e1-sets/README.md) · [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | — |
| RV2 | [환경 · 도구 시뮬레이터](../stages/rlvr/rv2-env/README.md) | ⬜ 예정 | 학습 중 에이전트가 쓸 도구 · 자료 환경을 실제와 같게, 빠르고 재현 가능하게 만든다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) · [IO1 MCP 도구](../stages/interop/io1-tools/README.md) | — |
| RV3 | [보상 설계](../stages/rlvr/rv3-reward/README.md) | 🟡 기초 있음 | 정답 확인 · 근거 일치 · 질문 관련성 · 비용을 합친 보상을 설명 가능하게 설계한다 | [8b 강화학습](../stages/llm/8b-rl/README.md) | — |
| RV4 | [보상 해킹 감시](../stages/rlvr/rv4-hacking/README.md) | 🟡 기초 있음 | 보상은 오르는데 실제 품질 · 사람 판정은 그대로인 경우를 찾아낸다 | [8b 강화학습](../stages/llm/8b-rl/README.md) · [E5 피드백](../stages/evalops/e5-feedback/README.md) | — |
| RV5 | [정책 학습 (GRPO · PPO)](../stages/rlvr/rv5-policy/README.md) | ⬜ 예정 | 같은 과제에 여러 답을 만들어 보상을 비교하며 모델이 더 나은 행동을 하도록 학습한다 | [P4 선호 학습](../stages/posttrain/p4-pref/README.md) | — |
| RV6 | [일반화 · 안전성 평가](../stages/rlvr/rv6-eval/README.md) | ⬜ 예정 | 학습에 없던 유형 · 자료에서도 나아졌는지, 안전성이 나빠지지 않았는지 확인한다 | [P6 후학습 평가](../stages/posttrain/p6-eval/README.md) · [G7 레드팀](../stages/guardrails/g7-redteam/README.md) | — |

## 설계 원칙

- 보상과 품질의 일치를 먼저 잰다 — Best-of 실측: 보상 +0.18(유의), 품질 +6.7(불확실)
- 검증 가능한 과제부터 — 조문 번호 질문은 정답 조문이 있어 번호 조회의 효과(75% → 100%)를 정확히 잴 수 있었다
- 환경은 실제 도구와 같게 — 시뮬레이터에서만 통하는 행동을 배우지 않게
- 일반 능력 · 안전성 회귀를 함께 본다(후학습 평가 · 레드팀)

## 예시

법률 에이전트 학습: 과제 = '질문의 근거 조문을 찾아 인용'(정답 조문 확인 가능) → 환경 = 실제 번호 조회 · 검색 도구 → 보상 = 정답 근거 인용 + 근거 일치 − 질문과 상관없는 문장 − 단계 수 → 보상만 오르고 품질이 그대로인 경우 감시 → GRPO 학습 → 판례 질문(학습에 없던 유형)으로 일반화 확인.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [온디바이스 · 엣지 맵](edge.md)
