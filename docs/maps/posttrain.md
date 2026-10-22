<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 후학습 (Post-training) 맵

합성 데이터 → 선별 · 누수 방지 → SFT → 선호 학습(DPO) → 어댑터 · 병합 → 평가 · 안전성 → 배포 형식 변환 — 우리 데이터로 LLM 자체를 고치는 흐름

프롬프트와 RAG 로 안 되는 것(답 형식 · 거절 습관 · 도메인 말투)은 모델을 고쳐야 합니다. 임베딩 파인튜닝 · 증류는 이 PC 에서 했지만, LLM 후학습은 GPU 가 필요해 지금은 데이터를 만드는 데까지입니다. 이 맵은 데이터 → 학습 → 평가 → 배포의 전체를 정리해 GPU 환경으로 넘어갈 때 그대로 쓰게 합니다.

앱의 **맵 → 후학습 (Post-training) 맵**(`/maps/posttrain`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[합성 데이터 생성] → [선별 · 누수 방지] → [SFT (지도 미세조정)]
                                      ↓
[선호 학습 (DPO 등)] → [어댑터 (LoRA) · 모델 병합]
                                      ↓
        [후학습 평가 · 안전성] → [배포 형식 변환 (GGUF · 양자화)]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| P1 | [합성 데이터 생성](../stages/posttrain/p1-synth/README.md) | ✅ 구현됨 | 큰 모델 · 규칙으로 질문 · 답 · 거절 예시를 만들어 학습 데이터를 늘린다 | [7a 지식 증류](../stages/llm/7a-distill/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P2 | [선별 · 누수 방지](../stages/posttrain/p2-select/README.md) | ✅ 구현됨 | 검증을 통과한 좋은 예시만 남기고, 평가 세트의 근거가 학습에 섞이지 않게 한다 | [5 파인튜닝](../stages/llm/5-finetune/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P3 | [SFT (지도 미세조정)](../stages/posttrain/p3-sft/README.md) | ✅ 구현됨 | 좋은 질문-답 예시로 LLM 을 추가 학습해 답 형식 · 인용 습관 · 도메인 말투를 맞춘다 | [7a 지식 증류](../stages/llm/7a-distill/README.md) · [5 파인튜닝](../stages/llm/5-finetune/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P4 | [선호 학습 (DPO 등)](../stages/posttrain/p4-pref/README.md) | ✅ 구현됨 | 좋은 답 / 나쁜 답 쌍으로 모델이 좋은 쪽을 고르도록 학습한다 | [8b 강화학습](../stages/llm/8b-rl/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P5 | [어댑터 (LoRA) · 모델 병합](../stages/posttrain/p5-adapter/README.md) | ✅ 구현됨 | 분야별 어댑터를 따로 학습해 갈아 끼우거나, 여러 모델을 합쳐 장점을 모은다 | [5 파인튜닝](../stages/llm/5-finetune/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P6 | [후학습 평가 · 안전성](../stages/posttrain/p6-eval/README.md) | ✅ 구현됨 | 학습 전후를 같은 평가 세트 · 같은 조건으로 비교하고, 안전성 회귀가 없는지 본다 | [2 RAG](../stages/llm/2-rag/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) · [G7 레드팀](../stages/guardrails/g7-redteam/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |
| P7 | [배포 형식 변환 (GGUF · 양자화)](../stages/posttrain/p7-export/README.md) | ✅ 구현됨 | 학습한 모델을 GGUF 로 바꾸고 양자화해 llama-server 에 올린다 | [7b 양자화](../stages/llm/7b-quant/README.md) | [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../stages/posttrain/p3-sft/posttrain.md) |

## 설계 원칙

- 검증을 통과한 답만 학습 데이터로 — LLM 증류 데이터는 근거 · 질문 관련성 검증으로 1/3 만 남았다
- 평가 세트의 근거는 학습에서 뺀다(누수 방지 — 여러 근거 모두)
- 보상과 품질이 어긋나는지 먼저 본다 — Best-of 실측에서 보상은 유의하게 올랐지만 품질은 불확실
- 학습 후에도 같은 평가 세트 · 같은 조건으로 비교(평가 · 관측 맵)

## 예시

답 없는 질문 거절이 약함(법률 13개 중 1개): 거절해야 할 질문 + 올바른 거절 답을 합성 → 검증 · 누수 제외 → SFT 또는 DPO(거절 vs 지어낸 답 쌍) → 같은 법률 세트로 거절률 · 품질 비교 → GGUF 로 바꿔 llama-server 에.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
