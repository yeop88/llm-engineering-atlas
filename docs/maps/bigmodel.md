<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 적은 메모리로 큰 모델 돌리기 맵

메모리 계획 → 층 단위 스트리밍 → CPU-GPU 혼합 · 전문가 오프로드 → 페이지 KV 캐시 → 연속 배칭 → 극저비트 → 여러 기기 나눠 돌리기 — 메모리보다 큰 모델을 돌리는 흐름

이 PC 는 RAM 28GB · 공유 메모리 내장 GPU 입니다. 30B 넘는 모델이나 큰 MoE 는 그대로는 올라가지 않습니다. 층을 디스크에서 하나씩 불러 돌리거나, 자주 쓰는 부분만 GPU 에 두고 나머지(MoE 전문가)는 CPU 에서 돌리거나, KV 캐시를 페이지로 나눠 여러 요청이 메모리를 나눠 쓰게 하면 적은 메모리로 큰 모델을 돌릴 수 있습니다 — 대신 속도를 냅니다. 무엇을 얼마나 내주는지 잽니다.

앱의 **맵 → 적은 메모리로 큰 모델 돌리기 맵**(`/maps/bigmodel`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[메모리 계획] → [층 단위 스트리밍]
                    ↓
[CPU-GPU 혼합 · 전문가 오프로드] → [극저비트]
                    ↓
[페이지 KV 캐시] → [연속 배칭] → [여러 기기 나눠 돌리기]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| BM1 | [메모리 계획](../stages/bigmodel/bm1-plan/README.md) | ⬜ 예정 | 가중치 · KV · 활성값을 계산해 GPU · CPU · 디스크 어디에 둘지 정한다 | [ED1 모델 선택](../stages/edge/ed1-select/README.md) · [S6 하드웨어](../stages/serving/s6-hardware/README.md) | — |
| BM2 | [층 단위 스트리밍](../stages/bigmodel/bm2-layer/README.md) | ⬜ 예정 | 층을 디스크에서 하나씩 불러 돌리고 버려 메모리보다 큰 모델을 돌린다 | [BM1 메모리 계획](../stages/bigmodel/bm1-plan/README.md) | — |
| BM3 | [CPU-GPU 혼합 · 전문가 오프로드](../stages/bigmodel/bm3-offload/README.md) | ⬜ 예정 | 자주 쓰는 층은 GPU, MoE 전문가처럼 드물게 쓰는 부분은 CPU 에 둔다 | [S4 추론 서버](../stages/serving/s4-server/README.md) · [BM1 메모리 계획](../stages/bigmodel/bm1-plan/README.md) | — |
| BM4 | [페이지 KV 캐시](../stages/bigmodel/bm4-paged/README.md) | ⬜ 예정 | KV 캐시를 작은 블록으로 나눠 요청끼리 나눠 쓰고 같은 앞부분은 공유한다 | [KC5 KV 양자화](../stages/compress/kc5-kvquant/README.md) | — |
| BM5 | [연속 배칭](../stages/bigmodel/bm5-batch/README.md) | ⬜ 예정 | 끝난 요청 자리에 바로 새 요청을 넣어 GPU 를 쉬지 않게 한다 | [BM4 페이지 KV](../stages/bigmodel/bm4-paged/README.md) · [S4 추론 서버](../stages/serving/s4-server/README.md) | — |
| BM6 | [극저비트](../stages/bigmodel/bm6-lowbit/README.md) | ⬜ 예정 | 2비트 이하 · 1.58비트 가중치로 메모리를 줄이고 품질 손실을 잰다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [ED2 극단 경량화](../stages/edge/ed2-compress/README.md) | — |
| BM7 | [여러 기기 나눠 돌리기](../stages/bigmodel/bm7-dist/README.md) | ⬜ 예정 | 층(파이프라인)이나 텐서를 여러 기기에 나눠 한 기기에 안 들어가는 모델을 돌린다 | [BM3 혼합 · 오프로드](../stages/bigmodel/bm3-offload/README.md) | — |

## 설계 원칙

- 먼저 계산한다 — 가중치 · KV · 활성값을 더해 어디에 둘지 정한다
- 메모리를 줄인 만큼 속도를 낸다 — 디스크 · CPU 로 보낸 몫을 토큰/초로 잰다
- 자주 쓰는 것만 빠른 곳에 — MoE 는 매번 쓰는 층 · 전문가가 일부다
- KV 는 요청끼리 나눠 쓴다 — 미리 다 잡으면 메모리가 남는데도 못 받는다

## 예시

MoE 30B Q4(17GB) 를 RAM 28GB · 내장 GPU 에 → 계획: 어텐션 · 공용 층은 GPU, 전문가 층은 CPU → 같은 질문으로 토큰/초 · 품질 · 최대 메모리 비교 → 동시 요청 4개는 KV 를 페이지로 나눠 맥락 합 32K 까지 → 그래도 넘으면 층 단위로 디스크에서 불러 느리지만 돌림.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md)
