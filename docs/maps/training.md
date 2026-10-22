<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 학습 생애주기 맵

데이터 수집 → 전처리 · 중복 제거 → 사전학습 → 지시 튜닝 → 선호 정렬 → 안전 정렬 → 평가 → 배포 — 후학습 · RLVR · 플라이휠을 한 생애주기로

이 앱은 사전학습을 하지 않습니다. 대신 공개 모델을 받아 지시 튜닝 · 선호 정렬 · 검증 기반 강화학습을 하고, 운영 실패를 다시 학습으로 돌립니다. 그 단계들이 따로 흩어져 있어 '이 모델은 어떤 데이터로 어떤 순서로 만들어졌나'를 한 줄로 볼 수 없었습니다 — 생애주기를 한 맵으로 묶고, 단계마다 데이터 · 누수 · 평가를 이어 둡니다.

앱의 **맵 → 학습 생애주기 맵**(`/maps/training`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[수집] → [전처리 · 중복] → [사전학습]
                    ↓
[지시 튜닝] → [선호 정렬] → [안전 정렬]
                    ↓
[평가] → [배포]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| TL1 | [데이터 수집](../stages/training/tl1-collect/README.md) | ⬜ 예정 | 학습 데이터의 출처(운영 기록 · 합성 · 공개)를 모으고 출처를 남긴다 | [FW1 로그](../stages/flywheel/fw1-logs/README.md) · [P1 합성 데이터](../stages/posttrain/p1-synth/README.md) | — |
| TL2 | [전처리 · 중복 제거](../stages/training/tl2-dedup/README.md) | ⬜ 예정 | 중복 · 저품질 · 평가와 겹치는 예시를 거른다 | [P2 선별](../stages/posttrain/p2-select/README.md) · [D4 정제 · 중복](../stages/docintel/d4-clean/README.md) | — |
| TL3 | [사전학습](../stages/training/tl3-pretrain/README.md) | 🔬 연구 | 사전학습은 하지 않고, 쓰는 공개 모델의 사전학습 정보(데이터 · 토큰 수)를 기록만 한다 | [LN1 모델 계열](../stages/lineage/ln1-family/README.md) | — |
| TL4 | [지시 튜닝](../stages/training/tl4-sft/README.md) | ⬜ 예정 | 지시 · 답 쌍으로 LoRA SFT — 무엇을 배웠고 무엇을 잃었나 | [P3 SFT](../stages/posttrain/p3-sft/README.md) | — |
| TL5 | [선호 정렬](../stages/training/tl5-pref/README.md) | ⬜ 예정 | 선호 쌍(DPO) · 검증 가능한 보상(GRPO)으로 답의 질을 맞춘다 | [P4 선호 학습](../stages/posttrain/p4-pref/README.md) · [RV5 정책 학습](../stages/rlvr/rv5-policy/README.md) | — |
| TL6 | [안전 정렬](../stages/training/tl6-safety/README.md) | ⬜ 예정 | 학습 전후 레드팀 · 거절 균형을 같은 문항으로 확인한다 | [G7 레드팀](../stages/guardrails/g7-redteam/README.md) · [RV4 보상 해킹](../stages/rlvr/rv4-hacking/README.md) | — |
| TL7 | [평가](../stages/training/tl7-eval/README.md) | ⬜ 예정 | 기본 모델 대비 업무 · 일반 · 안전을 짝지은 질문으로 비교한다 | [P6 후학습 평가](../stages/posttrain/p6-eval/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | — |
| TL8 | [배포](../stages/training/tl8-deploy/README.md) | ⬜ 예정 | GGUF 로 내보내 게이트 · 단계적 배포로 운영에 넣는다 | [P7 배포 변환](../stages/posttrain/p7-export/README.md) · [FW7 단계적 배포](../stages/flywheel/fw7-rollout/README.md) | — |

## 설계 원칙

- 사전학습은 하지 않는다 — 공개 모델에서 시작해 무엇을 바꿨는지만 남긴다
- 단계마다 데이터 계보 — 어떤 데이터가 어느 단계에 들어갔나
- 평가 질문은 학습에 섞지 않는다 — 누수 검사가 단계마다

## 예시

공개 Qwen3-0.6B → 상담 기록에서 SFT 데이터 412건(평가 질문과 겹치는 9건 제외) → LoRA SFT → 선호 쌍 DPO → 레드팀 회귀 확인 → 평가 세트로 기본 모델과 비교 → GGUF 로 내보내 llama-server 에.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
