<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 추론 최적화 맵

워크로드 측정 → 미리 채우기 · 생성 분리 → 양자화 → KV 캐시 관리 → 연속 배칭 → 앞부분 캐시 → 추측 디코딩 → 병렬화 → 품질 회귀 — 기준선부터 카나리까지 한 순서로

서빙 · 큰 모델 · 압축 맵에 최적화 기법이 흩어져 있습니다. 실무에서는 기법보다 순서가 중요합니다 — 기준선을 재고, 메모리 압력을 줄이고, 배칭 · 캐시를 손보고, 추측 디코딩을 시도하고, 품질을 확인한 뒤 카나리로 넓힙니다. 이 맵은 기존 기법을 그 순서로 묶고, 단계마다 p95 지연 · 성공 작업당 비용 · 품질 통과율을 같은 표로 남깁니다.

앱의 **맵 → 추론 최적화 맵**(`/maps/inference`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[워크로드 측정] → [미리 채우기 · 생성 분리] → [양자화]
                    ↓
[KV 관리] → [연속 배칭] → [앞부분 캐시]
                    ↓
[추측 디코딩] → [병렬화] → [품질 회귀]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| IF1 | [워크로드 측정](../stages/inference/if1-measure/README.md) | ✅ 구현됨 | 실제 요청의 프롬프트 · 답 길이 · 동시 수 · 지연 분포를 잰다 | [E4 비용 · 지연](../stages/evalops/e4-cost/README.md) · [E3 트레이싱](../stages/evalops/e3-tracing/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF2 | [미리 채우기 · 생성 분리](../stages/inference/if2-split/README.md) | ✅ 구현됨 | 미리 채우기(연산 한계)와 생성(대역폭 한계)을 따로 재고 따로 다룬다 | [S4 추론 서버](../stages/serving/s4-server/README.md) · [BM1 메모리 계획](../stages/bigmodel/bm1-plan/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF3 | [양자화](../stages/inference/if3-quant/README.md) | ✅ 구현됨 | 가중치 비트를 모델 · 장치마다 품질과 함께 고른다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [BM6 극저비트](../stages/bigmodel/bm6-lowbit/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF4 | [KV 캐시 관리](../stages/inference/if4-kv/README.md) | ✅ 구현됨 | KV 형식 · 블록 · 자르기를 워크로드에 맞춰 고른다 | [KC5 KV 양자화](../stages/compress/kc5-kvquant/README.md) · [BM4 페이지 KV](../stages/bigmodel/bm4-paged/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF5 | [연속 배칭](../stages/inference/if5-batch/README.md) | ✅ 구현됨 | 슬롯 수 · 배칭 방식으로 처리량과 꼬리 지연을 맞춘다 | [BM5 연속 배칭](../stages/bigmodel/bm5-batch/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF6 | [앞부분 캐시](../stages/inference/if6-prefix/README.md) | ✅ 구현됨 | 같은 시스템 프롬프트 · 근거의 미리 채우기를 다시 쓴다 | [CX4 프롬프트 캐시](../stages/context/cx4-cache/README.md) · [BM4 페이지 KV](../stages/bigmodel/bm4-paged/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF7 | [추측 디코딩](../stages/inference/if7-spec/README.md) | ✅ 구현됨 | 작은 초안 모델이 미리 쓰고 큰 모델이 확인한다 | [S5 디코딩 최적화](../stages/serving/s5-decode/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF8 | [병렬화](../stages/inference/if8-parallel/README.md) | ✅ 구현됨 | 텐서 · 파이프라인 · 전문가 병렬과 CPU-GPU 혼합을 고른다 | [BM7 여러 기기](../stages/bigmodel/bm7-dist/README.md) · [BM3 혼합 · 오프로드](../stages/bigmodel/bm3-offload/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |
| IF9 | [품질 회귀 · 카나리](../stages/inference/if9-regress/README.md) | ✅ 구현됨 | 최적화마다 품질 회귀를 확인하고 일부 트래픽부터 넓힌다 | [E2 회귀 평가](../stages/evalops/e2-offline/README.md) · [FW7 단계적 배포](../stages/flywheel/fw7-rollout/README.md) | [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../stages/inference/if1-measure/inference.md) |

## 설계 원칙

- 기준선 없이 최적화하지 않는다 — 워크로드부터 잰다
- 평균보다 p95 · 성공 작업당 비용 · 품질 통과율
- 형식은 정답이 없다 — 모델 · 장치 · 맥락 · 동시 수마다 다시 잰다
- 품질 회귀를 확인한 뒤 카나리로 넓힌다

## 예시

상담 워크로드: 프롬프트 1,800 · 답 300 토큰, 동시 4 → 기준선 p95 9.8초 → KV q8_0 로 메모리 절반 → 슬롯 4 · 연속 배칭으로 처리량 2.1배 → 시스템 프롬프트 앞부분 캐시로 미리 채우기 40% 감소 → 추측 디코딩은 이 모델에서 이득 없음 → 품질 회귀 통과 후 10% 카나리.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
