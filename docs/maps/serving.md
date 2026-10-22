<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 서빙 · 추론 최적화 · 비용 맵

캐시 → 근거 길이 관리 → 경량 모델 → 추론 서버 · 배치 · 스트리밍 → KV 캐시 · 추측 디코딩 → 하드웨어 → 비용 · 지연 예산 — 싸고 빠르게 돌리는 흐름

이 PC 실측에서 질문당 시간의 대부분은 근거 약 2,900토큰을 읽는 시간이었고(답 쓰기보다 길다), CPU 리랭커는 질문당 12~48초였습니다. 모델을 작게 하는 것만으로는 부족해서(E2B: 지연 −21%, 품질 −13), 읽을 양 · 캐시 · 디코딩 방식 · 하드웨어를 함께 봐야 합니다.

앱의 **맵 → 서빙 · 추론 최적화 · 비용 맵**(`/maps/serving`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[캐시 (의미 · 프롬프트 · 임베딩)] → [근거 길이 관리] → [경량 모델 (양자화 · 증류)]
                                      ↓
[추론 서버 · 배치 · 스트리밍] → [KV 캐시 · 추측 디코딩] → [하드웨어 배치]
                                      ↓
                         [비용 · 지연 예산]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| S1 | [캐시 (의미 · 프롬프트 · 임베딩)](../stages/serving/s1-cache/README.md) | ✅ 구현됨 | 같거나 비슷한 계산을 다시 하지 않는다 — 임베딩 · LLM 변형 · 프롬프트 · 답변 캐시 | [1 임베딩](../stages/llm/1-embedding/README.md) · [4 검색 향상](../stages/llm/4-search-lab/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S2 | [근거 길이 관리](../stages/serving/s2-context/README.md) | ✅ 구현됨 | LLM 이 읽을 근거의 수 · 길이를 품질을 지키는 범위에서 줄인다 | [2 RAG](../stages/llm/2-rag/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S3 | [경량 모델 (양자화 · 증류)](../stages/serving/s3-light/README.md) | ✅ 구현됨 | 가중치 · 벡터 비트를 낮추고 작은 모델에 지식을 옮겨 메모리 · 지연을 줄인다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [7a 지식 증류](../stages/llm/7a-distill/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S4 | [추론 서버 · 배치 · 스트리밍](../stages/serving/s4-server/README.md) | ✅ 구현됨 | 모델별 서버 · 동시 처리 · 스트리밍으로 대기 시간과 처리량을 맞춘다 | [2 RAG](../stages/llm/2-rag/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S5 | [KV 캐시 · 추측 디코딩](../stages/serving/s5-decode/README.md) | ✅ 구현됨 | KV 캐시 양자화로 긴 문맥 메모리를 줄이고, 추측 디코딩(MTP 등)으로 생성 속도를 올린다 | [7b 양자화](../stages/llm/7b-quant/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S6 | [하드웨어 배치](../stages/serving/s6-hardware/README.md) | ✅ 구현됨 | 어느 모델을 CPU · 내장 GPU · 외장 GPU 에 둘지, 몇 개를 올려 둘지 정한다 | [1 임베딩](../stages/llm/1-embedding/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |
| S7 | [비용 · 지연 예산](../stages/serving/s7-budget/README.md) | ✅ 구현됨 | 질문당 비용 · p95 지연 목표를 정하고 경로 · 모델 · 근거 설정을 그 안에 맞춘다 | [6 라우팅](../stages/llm/6-routing/README.md) · [E4 비용 · 지연](../stages/evalops/e4-cost/README.md) | [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../stages/serving/s4-server/serving.md) |

## 설계 원칙

- 병목부터 잰다 — 읽기(프롬프트 처리)와 쓰기(생성)를 나눠 기록하니 읽기가 2/3 였다
- 캐시는 측정을 망칠 수 있다 — 비교 측정에서는 끄고, 서비스에서는 켠다
- 줄인 만큼 품질을 잰다 — 근거 압축은 지연 −19% 대신 품질 −10(정답 문장을 버림)
- CPU 에서 비싼 단계는 끈다 — 리랭커 단독은 후보가 많을수록 손해, 쓰려면 융합 + 상위 5

## 예시

같은 FAQ 질문이 하루 수백 번: 의미 캐시로 비슷한 질문은 저장한 답을 바로 → 새 질문만 RAG → 짧은 정형 답은 소형 모델, 긴 종합은 큰 모델 → 질문당 비용 · p95 지연을 예산과 비교.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md)
