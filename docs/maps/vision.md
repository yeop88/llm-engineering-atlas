<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 이미지 · Vision-Language 맵

이미지 입력 → 전처리 → 객체 · 영역 → OCR → 관계 추론 → 시각 질의응답 → 근거 영역 표시 — VLM 하나에 다 맡기지 않고 탐지 · OCR · 규칙을 나눠서

사진 진단(AS4)은 비전 LLM 이 표시창 코드를 읽게 했고, 비전 리랭킹(MA4)은 사진 근거를 고르게 했습니다. 그러나 VLM 하나에 탐지 · 읽기 · 판단을 모두 맡기면 틀렸을 때 어디가 틀렸는지 모릅니다. 탐지 · OCR · 관계 · 규칙을 나누고, 답이 이미지의 어느 영역에 기대는지 표시합니다.

앱의 **맵 → 이미지 · Vision-Language 맵**(`/maps/vision`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[이미지] → [전처리] → [객체 · 영역]
                    ↓
[OCR] → [관계 추론]
                    ↓
[시각 질의응답] → [근거 영역]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| VL1 | [이미지 입력](../stages/vision/vl1-input/README.md) | ✅ 구현됨 | 사진 · 스크린샷 · 스캔을 받고 크기 · 형식 · 개인정보를 확인한다 | [AS4 사진 진단](../stages/as-service/as4-photo/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL2 | [전처리](../stages/vision/vl2-prep/README.md) | ✅ 구현됨 | 기울기 · 밝기 · 반사 · 잘라내기로 읽기 좋게 만든다 | [D2 파싱](../stages/docintel/d2-parse/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL3 | [객체 · 영역 인식](../stages/vision/vl3-detect/README.md) | ✅ 구현됨 | 관심 물체 · 영역(표시창 · 버튼 · 부품)의 위치를 찾는다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL4 | [OCR](../stages/vision/vl4-ocr/README.md) | ✅ 구현됨 | 영역 안의 글자 · 코드를 읽고 알려진 목록에 맞춘다 | [D2 파싱](../stages/docintel/d2-parse/README.md) · [AS4 사진 진단](../stages/as-service/as4-photo/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL5 | [관계 추론](../stages/vision/vl5-relation/README.md) | ✅ 구현됨 | 물체 사이의 관계(꺾임 · 연결 · 위치)를 판단한다 | [K3 추출](../stages/knowledge-graph/k3-extract/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL6 | [시각 질의응답](../stages/vision/vl6-vqa/README.md) | ✅ 구현됨 | 사진 + 질문 + 매뉴얼 근거로 답한다 | [MA2 멀티모달 RAG](../stages/multi-agent/ma2-rag/README.md) · [MA4 검색 에이전트](../stages/multi-agent/ma4-retrieval-agent/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |
| VL7 | [근거 영역 표시](../stages/vision/vl7-ground/README.md) | ✅ 구현됨 | 답의 각 주장이 이미지의 어느 영역에 기대는지 표시한다 | [PV7 인용](../stages/provenance/pv7-cite/README.md) | [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../stages/vision/vl1-input/vision.md) |

## 설계 원칙

- VLM 하나에 다 맡기지 않는다 — 탐지 · OCR · 규칙 엔진을 나눈다
- 답은 영역에 기댄다 — 이미지의 어디를 보고 답했나
- 읽은 것은 알려진 것에 맞춘다 — 코드 · 모델명은 목록으로 보정

## 예시

세탁기 표시창 사진 → 기울기 보정 · 반사 줄이기 → 표시창 영역 탐지 → OCR 'OE' (알려진 코드에 맞춤) → '배수 호스 꺾임' 은 사진의 호스 영역 → 답에 표시창 · 호스 두 영역 표시.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
