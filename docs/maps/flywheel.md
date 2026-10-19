<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 데이터 플라이휠 맵

서비스 로그 → 실패 분류 → 사람 검토 → 평가 · 학습 데이터 → 재학습 → 게이트 → 단계적 배포 → 다시 로그 — 평가 · 후학습 · 서빙 · 가드레일을 하나의 순환으로

평가 · 관측 맵과 후학습 맵이 한 방향의 흐름이라면, 플라이휠은 그것을 순환으로 묶습니다. 서비스에서 실패가 나오면 자동으로 분류되고, 사람이 가장 가치 있는 사례부터 검토해, 평가 세트와 학습 데이터가 되고, 재학습한 모델은 같은 조건의 게이트를 통과해야 일부 사용자부터 배포됩니다. 순환이라 한 단계를 바꾸면 다른 단계의 지표가 움직입니다 — 그래서 한 번에 하나씩 바꾸고 기록합니다.

앱의 **맵 → 데이터 플라이휠 맵**(`/maps/flywheel`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[서비스 로그] → [실패 자동 분류] → [사람 검토 우선순위]
        ↑                                   ↓
[단계적 배포 · 롤백] ← [회귀 · 안전성 게이트] ← [재학습 · 재색인] ← [평가 세트 · 학습 데이터]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 |
|---|---|---|---|---|
| FW1 | [서비스 로그 수집](../stages/flywheel/fw1-fw-logs/README.md) | 🟡 기초 있음 | 질문 · 단계 · 근거 · 답변 · 검증 결과 · 피드백을 요청마다 남겨 순환의 원료로 쓴다 | [E3 트레이싱](../stages/evalops/e3-ev-tracing/README.md) |
| FW2 | [실패 자동 분류](../stages/flywheel/fw2-fw-triage/README.md) | ⬜ 예정 | 실패를 검색 실패 · 인용 실패 · 질문과 상관없는 답 · 거절 실패 · 형식 오류로 자동 분류한다 | [E8 개선 루프](../stages/evalops/e8-ev-loop/README.md) · [MA7 검증 에이전트](../stages/agents/ma7-critic-agent/README.md) |
| FW3 | [사람 검토 우선순위](../stages/flywheel/fw3-fw-review/README.md) | 🟡 기초 있음 | 사람의 검토 시간을 가장 배울 것이 많은 사례(자동 판정이 애매한 것 · 새 유형)에 먼저 쓴다 | [E5 피드백](../stages/evalops/e5-ev-feedback/README.md) |
| FW4 | [평가 세트 · 학습 데이터로 변환](../stages/flywheel/fw4-fw-assets/README.md) | 🟡 기초 있음 | 검토한 사례를 평가 세트(재발 방지)와 학습 데이터(교정)로 나눠 보내고, 둘이 섞이지 않게 한다 | [E1 평가 세트](../stages/evalops/e1-ev-sets/README.md) · [P2 선별](../stages/posttrain/p2-pt-select/README.md) |
| FW5 | [재학습 · 재색인](../stages/flywheel/fw5-fw-retrain/README.md) | 🟡 기초 있음 | 고칠 곳에 따라 임베딩 재학습 · 재색인 · 프롬프트 · LLM 후학습 중 가장 싼 것부터 한다 | [5 파인튜닝](../stages/5-finetune/README.md) · [P3 SFT](../stages/posttrain/p3-pt-sft/README.md) |
| FW6 | [회귀 · 안전성 게이트](../stages/flywheel/fw6-fw-gate/README.md) | ⬜ 예정 | 새 버전은 고정 회귀 세트 · 레드팀 세트를 같은 조건으로 통과해야 배포 후보가 된다 | [E2 회귀 평가](../stages/evalops/e2-ev-offline/README.md) · [G7 레드팀](../stages/guardrails/g7-gr-redteam/README.md) |
| FW7 | [단계적 배포 · 롤백](../stages/flywheel/fw7-fw-rollout/README.md) | ⬜ 예정 | 게이트를 통과한 버전을 일부 사용자부터 내보내고, 지표가 나빠지면 즉시 이전 버전으로 되돌린다 | [E7 A/B 실험](../stages/evalops/e7-ev-ab/README.md) |

## 설계 원칙

- 평가 세트와 학습 데이터를 섞지 않는다 — 누수 방지(여러 근거 모두 제외)를 순환 전체에 적용
- 피드백은 편향된다 — 불만이 있는 사용자만 누르므로 실패 분류 · 무작위 표본 검토로 보정
- 게이트는 같은 조건으로 — 프롬프트 캐시 · 세트 버전 · 시드를 맞춘 회귀 평가만 통과 기준으로
- 한 번에 하나씩 바꾼다 — 순환에서는 모델 · 청킹 · 프롬프트를 같이 바꾸면 무엇이 효과였는지 알 수 없다
- 적은 라벨로 결론 내지 않는다 — 학습 라우터는 '어려움' 라벨 5개로 지연 −25% 였지만 기준값 하나 차이로 품질이 흔들렸다

## 예시

법률 서비스에서 '답 없는 질문을 지어내 답함'이 반복 → 실패 분류가 '거절 실패'로 묶음 → 검토 화면에 우선 표시 → 사람이 확인한 20건을 평가 세트(재발 방지)와 DPO 쌍(거절 vs 지어낸 답)으로 → 재학습 → 법률 회귀 세트 · 레드팀 게이트 통과 → 10% 사용자에게 배포 → 거절률 · 만족도 확인 후 전체로.

---

다른 맵: [LLM 시스템 엔지니어링 맵](../map.md) · [지식 그래프 · GraphRAG 맵](../kg-map.md) · [멀티에이전트 · 멀티모달 맵](../agents-map.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
