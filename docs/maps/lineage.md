<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 기반 모델 계보 맵

모델 계열 → 세대 → 파라미터 · MoE 구조 → 컨텍스트 길이 → 입력 · 출력 모달리티 → 라이선스 · 배포 조건 — 어떤 모델이 어떤 기능 · 환경에 맞나

모델 이름만으로는 무엇을 할 수 있는지 모릅니다. 같은 계열도 세대마다 컨텍스트 · 모달리티 · 라이선스가 다르고, 같은 크기도 밀집 · MoE 에 따라 메모리와 속도가 다릅니다. 모델 카드 · 설정 파일 · GGUF 머리말에서 사실을 뽑아 계보로 잇고, 이 PC · 이 업무에 맞는 모델을 고르게 합니다.

앱의 **맵 → 기반 모델 계보 맵**(`/maps/lineage`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[모델 계열] → [세대] → [파라미터 · MoE]
                    ↓
[컨텍스트 길이] → [모달리티] → [라이선스 · 배포]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| LN1 | [모델 계열](../stages/lineage/ln1-family/README.md) | ✅ 구현됨 | 모델을 계열(만든 곳 · 구조 흐름)로 묶는다 | [1 임베딩](../stages/llm/1-embedding/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |
| LN2 | [모델 세대](../stages/lineage/ln2-generation/README.md) | ✅ 구현됨 | 같은 계열 안의 세대 차이(무엇이 바뀌었나)를 잇는다 | [LN1 모델 계열](../stages/lineage/ln1-family/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |
| LN3 | [파라미터 · MoE 구조](../stages/lineage/ln3-params/README.md) | ✅ 구현됨 | 전체 · 활성 파라미터, 밀집 · MoE, 층 · 차원을 설정 파일에서 읽는다 | [BM1 메모리 계획](../stages/bigmodel/bm1-plan/README.md) · [IP1 임베딩 공간](../stages/interp/ip1-space/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |
| LN4 | [컨텍스트 길이](../stages/lineage/ln4-context/README.md) | ✅ 구현됨 | 학습 · 확장 맥락 길이와 실제로 쓸 수 있는 길이를 나눠 적는다 | [CX2 긴 맥락 vs RAG](../stages/context/cx2-long/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |
| LN5 | [입력 · 출력 모달리티](../stages/lineage/ln5-modality/README.md) | ✅ 구현됨 | 글 · 이미지 · 소리 · 영상 입력과 출력을 모델별로 적는다 | [M 멀티모달](../stages/llm/m-multimodal/README.md) · [VC1 음성 인식](../stages/voice/vc1-stt/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |
| LN6 | [라이선스 · 배포 조건](../stages/lineage/ln6-license/README.md) | ✅ 구현됨 | 라이선스 · 사용 제한 · 재배포 조건을 모델 카드에서 확인해 남긴다 | [G6 라이선스](../stages/guardrails/g6-license/README.md) | [기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드 · 계열 · 세대 · 구조 · 맥락 · 모달리티 · 라이선스 확인 · 실측](../stages/lineage/ln1-family/lineage.md) |

## 설계 원칙

- 모델 이름보다 설정 파일 — 카드의 말보다 config · GGUF 머리말의 숫자
- 계보로 잇는다 — 앞 세대와 무엇이 바뀌었나
- 할 수 있는 것과 써도 되는 것을 따로 — 성능과 라이선스

## 예시

'Qwen3-30B-A3B' → 계열 Qwen · 3세대 · MoE 128 전문가 중 8 · 30.5B(활성 3.3B) · 맥락 32K(확장 128K) · 글만 · Apache-2.0 → 이 PC 에서는 전문가 CPU 배치로 돌릴 수 있음(BM1).

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
