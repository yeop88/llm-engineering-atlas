<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 오디오 이해 맵

음원 입력 → 음성 · 음악 · 환경음 분리 → 화자 · 언어 → 이벤트 인식 → 시간 구간 → 의미 표현 → 검색 · 요약 — 말 이외의 소리까지

음성 상담 맵은 말을 글로 바꾸는 데 집중했습니다. 하지만 '세탁기에서 덜컹거리는 소리가 나요' 는 소리 자체가 증거이고, 회의 녹음은 누가 언제 말했는지가 중요합니다. 음성 · 음악 · 환경음을 나누고, 화자 · 언어 · 소리 사건을 시간 구간으로 색인해 검색 · 요약까지 잇습니다.

앱의 **맵 → 오디오 이해 맵**(`/maps/audio`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[음원] → [분리] → [화자 · 언어]
                    ↓
[이벤트] → [시간 구간]
                    ↓
[의미 표현] → [검색 · 요약]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| AU1 | [음원 입력](../stages/audio/au1-input/README.md) | ⬜ 예정 | 녹음 · 통화 · 영상 소리를 같은 표본률 · 형식으로 맞춘다 | [VC1 음성 인식](../stages/voice/vc1-stt/README.md) | — |
| AU2 | [음성 · 음악 · 환경음 분리](../stages/audio/au2-separate/README.md) | ⬜ 예정 | 구간마다 음성 · 음악 · 환경음 · 침묵을 나눈다 | [AU1 음원 입력](../stages/audio/au1-input/README.md) | — |
| AU3 | [화자 · 언어 탐지](../stages/audio/au3-speaker/README.md) | ⬜ 예정 | 누가 말했는지(화자 분리)와 어떤 언어인지를 구간마다 붙인다 | [VC5 감정 감지](../stages/voice/vc5-emotion/README.md) | — |
| AU4 | [이벤트 인식](../stages/audio/au4-event/README.md) | 🔬 연구 | 기계 이상음 · 경고음 · 박수 같은 소리 사건을 알아본다 | [AS4 사진 진단](../stages/as-service/as4-photo/README.md) | — |
| AU5 | [시간 구간 추출](../stages/audio/au5-segment/README.md) | ⬜ 예정 | 사건 · 발화를 시작 · 끝 시각으로 색인한다 | [OM3 영상 분석](../stages/omni/om3-video/README.md) | — |
| AU6 | [의미 표현](../stages/audio/au6-semantic/README.md) | 🔬 연구 | 구간을 글 · 임베딩으로 바꿔 검색할 수 있게 한다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | — |
| AU7 | [검색 · 요약](../stages/audio/au7-search/README.md) | ⬜ 예정 | 회의 · 통화를 구간 근거와 함께 찾고 요약한다 | [VC7 통화 요약](../stages/voice/vc7-summary/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | — |

## 설계 원칙

- 소리도 근거다 — 말 이외의 소리를 사건으로 남긴다
- 시간 구간이 단위다 — 누가 · 무엇이 · 언제부터 언제까지
- 작은 모델로 먼저 거른다 — 비싼 모델은 고른 구간에만

## 예시

세탁기 소리 녹음 40초 → 음성 · 환경음 분리 → 12~19초 '덜컹 반복(탈수 불균형 의심)' 사건 → 고객 말 '탈수할 때만 그래요' 구간과 정렬 → 'UE 탈수 불균형' 매뉴얼 근거로 답.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
