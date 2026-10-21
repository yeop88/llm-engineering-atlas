<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 온디바이스 · 엣지 맵

기기별 모델 선택 → 극단적 양자화 · 증류 → 기기 내 검색 → 오프라인 동작 → 서버와 동기화 → 개인정보 국소 처리 — 서버 없이 기기에서 돌리는 흐름

현장 기사용 태블릿 · 매장 키오스크 · 사내망이 끊기는 곳에서는 서버 없이 기기에서 검색 · 답변해야 합니다. 메모리 · 전력 · 업데이트 제약이 서로 맞물리고, 자료가 바뀌면 기기마다 동기화해야 합니다. 이 프로젝트의 양자화 · 증류 실측이 출발점입니다 — 이 PC 자체가 내장 GPU 로 로컬 LLM 을 돌리는 작은 엣지 환경입니다.

앱의 **맵 → 온디바이스 · 엣지 맵**(`/maps/edge`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[기기별 모델 선택] → [극단적 양자화 · 증류] → [기기 내 검색 (작은 색인)]
                                      ↓
[오프라인 동작] → [서버와 동기화 · 업데이트] → [개인정보 국소 처리]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| ED1 | [기기별 모델 선택](../stages/edge/ed1-select/README.md) | ✅ 구현됨 | 기기의 메모리 · 연산 능력에 맞는 임베딩 · LLM 크기를 고르고 품질 손실을 잰다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [1 임베딩](../stages/llm/1-embedding/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |
| ED2 | [극단적 양자화 · 증류](../stages/edge/ed2-compress/README.md) | ✅ 구현됨 | 4비트 이하 · 이진 벡터 · 작은 학생 모델로 줄이고, 손실이 겹치는지 잰다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [7a 지식 증류](../stages/llm/7a-distill/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |
| ED3 | [기기 내 검색 (작은 색인)](../stages/edge/ed3-index/README.md) | ✅ 구현됨 | 필요한 자료만 압축 색인으로 기기에 담아 서버 없이 검색한다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |
| ED4 | [오프라인 동작](../stages/edge/ed4-offline/README.md) | ✅ 구현됨 | 연결이 끊겨도 검색 · 답변이 되고, 할 수 없는 일(사진 진단 등)은 연결될 때로 미룬다 | [S1 캐시](../stages/serving/s1-cache/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |
| ED5 | [서버와 동기화 · 업데이트](../stages/edge/ed5-sync/README.md) | ✅ 구현됨 | 바뀐 자료 · 모델만 기기로 보내고, 기기의 기록 · 피드백은 서버로 모은다 | [D6 증분 갱신](../stages/docintel/d6-meta/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |
| ED6 | [개인정보 국소 처리](../stages/edge/ed6-privacy/README.md) | ✅ 구현됨 | 고객 정보 · 사진 · 음성은 기기 안에서 처리하고 서버로는 가린 결과 · 통계만 보낸다 | [G2 개인정보](../stages/guardrails/g2-pii/README.md) | [온디바이스 · 엣지 — 기기 추천 · 경량화 조합 · 기기용 팩 · 오프라인 · 동기화 · 개인정보 · 실측](../stages/edge/ed3-index/edge.md) |

## 설계 원칙

- 작게 만든 만큼 잰다 — 벡터 int4 는 손실 없이 1/8, binary + 재점수는 1/32 에 −0.4~−0.5, 겹치면 손실 누적
- 모델 작게 vs 읽을 양 줄이기 — 소형 LLM 은 품질 −13 이었고, 시간의 2/3 는 근거 읽기
- QAT 모델을 우선 — Google QAT Q4_0 은 Q8_0 과 같은 품질로 가장 빨랐다
- 기기에 남는 자료는 개인정보 — 국소 처리하고 서버로는 필요한 것만

## 예시

AS 기사 태블릿: 담당 제품군 매뉴얼만 binary + 재점수 색인으로(수십 MB) → 소형 LLM(QAT Q4) 로 오프라인 답변 → 사진 진단은 연결될 때 서버로 → 밤마다 바뀐 매뉴얼만 동기화 → 고객 정보는 기기 안에서만.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
