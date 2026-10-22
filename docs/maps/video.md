<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 비디오 이해 맵

영상 수집 → 장면 분할 → 대표 프레임 → 객체 · 행동 추적 → 음성 · 자막 정렬 → 시공간 추론 → 이벤트 색인 → 검색 · 요약 — '처음 일어난 때' 에 답하기

멀티모달 수집은 영상을 프레임 몇 장으로, 옴니채널은 영상 통화의 바뀐 장면을 읽었습니다. 하지만 '이 행동이 처음 일어난 때는?', 'A 가 B 를 집은 장면은?' 은 장면 · 추적 · 소리가 같은 시간축에 있어야 답합니다. 장면 → 추적 → 정렬 → 사건 색인을 쌓아 시간 질문에 근거 구간으로 답합니다.

앱의 **맵 → 비디오 이해 맵**(`/maps/video`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[수집] → [장면 분할] → [대표 프레임]
                    ↓
[추적] → [음성 · 자막 정렬]
                    ↓
[시공간 추론] → [이벤트 색인] → [검색 · 요약]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| VD1 | [영상 수집](../stages/video/vd1-ingest/README.md) | ✅ 구현됨 | 영상 파일 · 스트림을 받고 길이 · 형식 · 소리 트랙을 확인한다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD2 | [장면 분할](../stages/video/vd2-scene/README.md) | ✅ 구현됨 | 컷(샷)과 장면 경계를 찾는다 | [OM3 영상 분석](../stages/omni/om3-video/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD3 | [대표 프레임 선택](../stages/video/vd3-keyframe/README.md) | ✅ 구현됨 | 장면마다 대표 프레임을 골라 비전 모델로 읽는다 | [OM3 영상 분석](../stages/omni/om3-video/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD4 | [객체 · 행동 추적](../stages/video/vd4-track/README.md) | ✅ 구현됨 | 물체 · 사람을 프레임에 걸쳐 따라가고 행동을 붙인다 | [VL3 객체 · 영역](../stages/vision/vl3-detect/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD5 | [음성 · 자막 정렬](../stages/video/vd5-align/README.md) | ✅ 구현됨 | 전사 · 자막 · 화자를 영상 시간축에 맞춘다 | [AU5 시간 구간](../stages/audio/au5-segment/README.md) · [VC1 음성 인식](../stages/voice/vc1-stt/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD6 | [시공간 추론](../stages/video/vd6-reason/README.md) | ✅ 구현됨 | '처음 · 마지막 · 몇 번 · 무엇 다음' 을 색인 위에서 계산한다 | [RS1 생각 예산](../stages/reasoning/rs1-budget/README.md) · [RS3 여러 번 풀기](../stages/reasoning/rs3-sampling/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD7 | [이벤트 색인](../stages/video/vd7-index/README.md) | ✅ 구현됨 | 장면 · 트랙 · 말 · 사건을 시간 · 관계로 색인한다 | [OM3 영상 분석](../stages/omni/om3-video/README.md) · [K5 그래프 DB](../stages/knowledge-graph/k5-graph-db/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |
| VD8 | [검색 · 요약](../stages/video/vd8-search/README.md) | ✅ 구현됨 | 질문에 근거 클립과 함께 답하고 영상을 구간 근거로 요약한다 | [2 RAG](../stages/llm/2-rag/README.md) · [VC7 통화 요약](../stages/voice/vc7-summary/README.md) | [비디오 이해 — 컷 · 추적 · 소리 사건을 한 시간축 색인으로, 처음 · 마지막 · 몇 번 · 무엇 다음을 계산, 합성 영상 평가](../stages/video/vd1-ingest/video.md) |

## 설계 원칙

- 시간축 하나 — 장면 · 추적 · 말 · 소리를 같은 초에
- 다 읽지 않는다 — 장면이 바뀐 곳 · 질문이 가리키는 곳만
- 답은 구간으로 — 근거 클립을 함께

## 예시

회의 녹화 40분 → 장면 37개 · 대표 프레임 37장 → 화자 · 자막 정렬 → '예산 확정' 결정 사건 23:10~24:05 → '결정된 항목과 발언 구간은?' 에 그 구간 클립 · 전사로 답.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
