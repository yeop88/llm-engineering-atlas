<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# Transformer · MoE 구조 맵

토큰화 → 임베딩 → 어텐션 → FFN · 전문가 → 라우팅 → 출력 헤드 — 밀집 · MoE · 슬라이딩 창 · 선형 어텐션 · 상태 공간이 메모리 · 연산에 미치는 영향

같은 크기의 모델도 구조에 따라 메모리 · 속도 · 긴 맥락 비용이 다릅니다. 슬라이딩 창 · 선형 어텐션 층은 KV 를 줄이고, MoE 는 토큰마다 읽는 가중치를 줄입니다. 작은 공개 모델을 직접 열어 층마다 무엇이 얼마나 드는지 재고, 'MoE 는 언제 메모리보다 연산을 줄여 주는가'에 숫자로 답합니다.

앱의 **맵 → Transformer · MoE 구조 맵**(`/maps/architecture`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[토큰화] → [임베딩] → [어텐션]
                    ↓
[FFN · 전문가] → [라우팅] → [출력 헤드]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| TA1 | [토큰화](../stages/architecture/ta1-tokenize/README.md) | ⬜ 예정 | 글을 토큰으로 — 구조 맵에서는 토큰 수가 모든 비용의 단위 | [TK2 토큰 분할](../stages/tokenizer/tk2-split/README.md) | — |
| TA2 | [임베딩 · 층별 임베딩](../stages/architecture/ta2-embed/README.md) | ⬜ 예정 | 어휘 × 차원 표, 출력과 같이 쓰는지, 층별 임베딩이 있는지를 본다 | [IP1 임베딩 공간](../stages/interp/ip1-space/README.md) | — |
| TA3 | [어텐션 종류](../stages/architecture/ta3-attention/README.md) | ⬜ 예정 | 전체 · GQA · 슬라이딩 창 · 선형 어텐션 · 상태 공간 층의 KV 와 연산을 비교한다 | [BM1 메모리 계획](../stages/bigmodel/bm1-plan/README.md) · [KC3 주의 싱크](../stages/compress/kc3-sink/README.md) | — |
| TA4 | [FFN · 전문가](../stages/architecture/ta4-ffn/README.md) | ⬜ 예정 | 밀집 FFN 과 MoE 전문가(공용 전문가 포함)의 크기 · 쓰는 몫을 비교한다 | [BM3 혼합 · 오프로드](../stages/bigmodel/bm3-offload/README.md) | — |
| TA5 | [전문가 라우팅](../stages/architecture/ta5-routing/README.md) | ⬜ 예정 | 라우터가 토큰마다 전문가를 고르는 방식과 쓰임 치우침을 잰다 | [TA4 FFN · 전문가](../stages/architecture/ta4-ffn/README.md) | — |
| TA6 | [출력 헤드](../stages/architecture/ta6-head/README.md) | ⬜ 예정 | 마지막 정규화 · 출력층 · 로짓 처리(소프트캡 등)가 비용 · 신호에 주는 영향 | [IP6 내부 환각 탐지](../stages/interp/ip6-hallu/README.md) | — |

## 설계 원칙

- 구조는 비용으로 본다 — 층마다 메모리 · 읽는 바이트 · 연산
- MoE 는 메모리를 줄이지 않는다 — 읽는 양을 줄인다
- 어텐션 종류가 긴 맥락 비용을 정한다 — KV 를 층마다 센다

## 예시

gemma-4-E4B 42층 = 전체 어텐션 4 · 슬라이딩 창 20 · KV 공유 18 → 32K 맥락 KV 가 '층 수 × 맥락' 어림의 1/8 → Qwen3-30B-A3B 는 30B 를 다 올리지만 토큰마다 3B 만 읽어 CPU 에서도 23 토큰/초 어림.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
