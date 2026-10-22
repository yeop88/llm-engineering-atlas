<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 생성 이미지 · 비디오 제작 맵

기획 · 스크립트 → 장면 · 샷 분해 → 캐릭터 · 스타일 → 이미지 · 비디오 생성 → 음성 · 음악 → 편집 · 합성 → 품질 검사 → 출처 · 워터마크 — 만드는 것보다 검사 · 출처

이 PC 로는 이미지 · 영상 생성 모델을 제대로 돌릴 수 없습니다. 그래도 생성 미디어 흐름의 대부분은 생성 밖에 있습니다 — 스크립트를 샷으로 나누고, 캐릭터 · 스타일을 고정하고, 결과를 검사하고, 출처를 남기는 일입니다. 이 맵은 그 앞뒤 단계를 설계하고, 생성은 외부 서비스 · 공개 모델을 연결하는 자리로 둡니다.

앱의 **맵 → 생성 이미지 · 비디오 제작 맵**(`/maps/genmedia`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[기획 · 스크립트] → [장면 · 샷] → [캐릭터 · 스타일]
                    ↓
[생성] → [음성 · 음악] → [편집]
                    ↓
[품질 검사] → [출처 · 워터마크]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| GM1 | [기획 · 스크립트](../stages/genmedia/gm1-script/README.md) | 🔬 연구 | 목적 · 대상 · 길이 · 메시지로 스크립트를 쓴다 | [MA6 작성 에이전트](../stages/multi-agent/ma6-report-agent/README.md) | — |
| GM2 | [장면 · 샷 분해](../stages/genmedia/gm2-shots/README.md) | 🔬 연구 | 스크립트를 샷(구도 · 길이 · 카메라)으로 나눈다 | [GM1 기획](../stages/genmedia/gm1-script/README.md) | — |
| GM3 | [캐릭터 · 스타일 정의](../stages/genmedia/gm3-style/README.md) | 🔬 연구 | 캐릭터 · 색 · 글꼴 · 화풍을 고정할 기준을 정한다 | [GM2 샷 분해](../stages/genmedia/gm2-shots/README.md) | — |
| GM4 | [이미지 · 비디오 생성](../stages/genmedia/gm4-generate/README.md) | 🔬 연구 | 외부 서비스 · 공개 모델로 샷을 생성하는 연결 자리 | [GM3 캐릭터 · 스타일](../stages/genmedia/gm3-style/README.md) | — |
| GM5 | [음성 · 음악 생성](../stages/genmedia/gm5-audio/README.md) | 🔬 연구 | 대사 음성 · 배경 음악을 만들고 길이를 샷에 맞춘다 | [VC4 음성 합성](../stages/voice/vc4-tts/README.md) | — |
| GM6 | [편집 · 합성](../stages/genmedia/gm6-edit/README.md) | 🔬 연구 | 샷 · 소리 · 자막을 이어 붙이고 전환을 넣는다 | [GM5 음성 · 음악](../stages/genmedia/gm5-audio/README.md) | — |
| GM7 | [품질 검사](../stages/genmedia/gm7-qa/README.md) | ⬜ 예정 | 프롬프트 준수 · 캐릭터 · 시간 일관성 · 입 모양 · 결함을 잰다 | [VL6 시각 질의응답](../stages/vision/vl6-vqa/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | — |
| GM8 | [출처 · 워터마크 기록](../stages/genmedia/gm8-provenance/README.md) | ⬜ 예정 | 생성 출처 메타 · AI 생성 표시 · 권리 확인을 남긴다 | [PV1 원본](../stages/provenance/pv1-source/README.md) · [RC6 고지 · 이의](../stages/compliance/rc6-notice/README.md) | — |

## 설계 원칙

- 생성보다 검사 — 프롬프트 준수 · 일관성 · 결함을 잰다
- 출처를 남긴다 — 무엇으로 어떻게 만들었는지 · 워터마크
- 권리를 먼저 — 저작권 · 초상권은 기획 단계에서

## 예시

제품 사용 안내 30초 영상 → 스크립트 → 샷 6개 → 캐릭터 · 색 · 글꼴 고정 → 샷별 생성(외부) → 안내 음성 합성 → 편집 → 샷마다 프롬프트 준수 · 캐릭터 일관성 검사 → 생성 출처 메타 · AI 생성 표시.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
