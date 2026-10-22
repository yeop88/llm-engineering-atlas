<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 모델 라우팅 · 비용 최적화 맵

요청 분류 → 위험도 판정 → 품질 요구 → 지연 · 예산 → 모델 후보 → 모델 선택 → 실패 시 승격 → 비용 · 품질 기록 — 점수 = 품질 · 근거 · 지연 · 비용 · 신뢰성

LLM 맵의 라우팅(6)은 빠른 경로 · 느린 경로 둘을 골랐고, 추론 맵은 생각 여부를, 서빙 맵은 예산 안의 설정을 골랐습니다. 실제 서비스는 그보다 많은 갈래 — 소형 · 대형 · 추론 · VLM · 음성 · 로컬 · RAG · GraphRAG · 사람 승인 — 를 요청마다 골라야 합니다. 위험도 · 품질 요구 · 지연 · 예산을 한 점수로 계산하고, 실패하면 승격하며, 고른 이유를 기록합니다.

앱의 **맵 → 모델 라우팅 · 비용 최적화 맵**(`/maps/routing`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[요청 분류] → [위험도] → [품질 요구]
                    ↓
[지연 · 예산] → [후보] → [선택]
                    ↓
[실패 시 승격] → [비용 · 품질 기록]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| MR1 | [요청 분류](../stages/routing/mr1-classify/README.md) | ✅ 구현됨 | 모달리티 · 작업 유형(요약 · 추론 · 이미지 · 음성 · 관계 · 코드)을 판정한다 | [6 라우팅](../stages/llm/6-routing/README.md) · [RS2 생각 라우팅](../stages/reasoning/rs2-route/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR2 | [위험도 판정](../stages/routing/mr2-risk/README.md) | ✅ 구현됨 | 법률 · 의료 · 금전 · 외부 행동 같은 고위험을 먼저 가른다 | [RC2 위험 등급](../stages/compliance/rc2-risk/README.md) · [G1 입력 방어](../stages/guardrails/g1-injection/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR3 | [품질 요구 계산](../stages/routing/mr3-quality/README.md) | ✅ 구현됨 | 작업 유형 · 위험도로 필요한 품질 수준을 정한다 | [E1 평가 세트](../stages/evalops/e1-sets/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR4 | [지연 · 예산 계산](../stages/routing/mr4-budget/README.md) | ✅ 구현됨 | 채널의 지연 예산과 테넌트 예산 안에서 쓸 수 있는 몫을 계산한다 | [S7 예산](../stages/serving/s7-budget/README.md) · [PF7 비용 배분](../stages/platform/pf7-chargeback/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR5 | [모델 후보 생성](../stages/routing/mr5-candidates/README.md) | ✅ 구현됨 | 모달리티 · 품질 · 지연을 만족하는 모델 · 경로 후보를 만든다 | [LN5 모달리티](../stages/lineage/ln5-modality/README.md) · [ED1 모델 선택](../stages/edge/ed1-select/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR6 | [모델 선택](../stages/routing/mr6-select/README.md) | ✅ 구현됨 | 점수(품질 · 근거 · 지연 · 비용 · 신뢰성 가중합)로 고른다 | [6 라우팅](../stages/llm/6-routing/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR7 | [실패 시 승격](../stages/routing/mr7-escalate/README.md) | ✅ 구현됨 | 검증에 떨어지거나 실패하면 다음 모델 · 사람으로 올린다 | [PF6 장애 대응](../stages/platform/pf6-resilience/README.md) · [AS6 검증](../stages/as-service/as6-verify/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |
| MR8 | [비용 · 품질 기록](../stages/routing/mr8-log/README.md) | ✅ 구현됨 | 고른 이유 · 비용 · 품질을 남겨 라우터를 다시 채점한다 | [E3 트레이싱](../stages/evalops/e3-tracing/README.md) · [E8 개선 루프](../stages/evalops/e8-loop/README.md) | [모델 라우팅 · 비용 최적화 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점 · 실측](../stages/routing/mr1-classify/model_routing.md) |

## 설계 원칙

- 점수로 고른다 — 품질 0.35 · 근거 0.20 · 지연 0.15 · 비용 0.15 · 신뢰성 0.15(기본, 바꿀 수 있음)
- 위험이 먼저 — 고위험은 비용과 상관없이 고성능 + 사람 승인
- 실패하면 올린다 — 검증에 떨어진 답은 다음 모델로
- 고른 이유를 남긴다 — 나중에 라우터를 채점하려고

## 예시

'계약서 3개 조항 비교해서 위험한 것 골라 줘' → 분류: 깊은 추론 · 문서 → 위험: 중(법률) → 품질 요구 높음 · 지연 10초 → 후보: 추론 모델 + RAG / 대형 + RAG → 점수로 추론 + RAG → 인용 검증 통과 → 비용 · 품질 기록. 실패했다면 대형 + 사람 검토로 승격.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [합성 데이터 맵](synthetic.md)
