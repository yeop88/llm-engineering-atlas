<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 실시간 음성 상담 맵

스트리밍 음성 인식 → 말 끊기 · 끼어들기 → 짧은 지연 RAG · 감정 감지 → 스트리밍 음성 합성 → 상담원 보조 · 통화 요약 — 전화 AS 상담

고객 AS 상담 시나리오의 다음 단계는 전화입니다. 음성은 모든 단계가 하나의 지연 예산(사람이 어색하지 않은 응답은 1초 안팎)을 나눠 써야 하고, 고객이 말을 끊거나 감정이 격해지는 상황도 다뤄야 합니다. 이 PC 실측(근거 읽기 수십 초, 생성 13 토큰/초)과는 거리가 멀어, 서빙 · 최적화 맵의 성과가 전제입니다.

앱의 **맵 → 실시간 음성 상담 맵**(`/maps/voice`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[스트리밍 음성 인식] → [말 끊기 · 끼어들기 (턴 관리)]
                                      ↓
[짧은 지연 RAG] · [감정 · 불만 감지]
                                      ↓
[스트리밍 음성 합성] → [상담원 실시간 보조] → [통화 요약 · 후처리]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| VC1 | [스트리밍 음성 인식](../stages/voice/vc1-stt/README.md) | ✅ 구현됨 | 통화 음성을 말하는 도중에 글로 옮겨, 끝나기 전에 처리를 시작한다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC2 | [말 끊기 · 끼어들기 (턴 관리)](../stages/voice/vc2-turn/README.md) | ✅ 구현됨 | 고객이 말을 끊거나 끼어들면 즉시 멈추고 듣고, 말이 끝나면 바로 응답한다 | [C2 되묻기](../stages/conversation/c2-clarify/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC3 | [짧은 지연 RAG](../stages/voice/vc3-fastrag/README.md) | ✅ 구현됨 | 음성에 맞게 1초 안팎으로 근거를 찾고 첫 문장을 낸다 — 캐시 · 짧은 근거 · 스트리밍 | [S1 캐시](../stages/serving/s1-cache/README.md) · [S2 근거 길이](../stages/serving/s2-context/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC4 | [스트리밍 음성 합성](../stages/voice/vc4-tts/README.md) | ✅ 구현됨 | 생성되는 글을 문장 단위로 바로 음성으로 바꿔 들려준다 | [MA8 멀티모달 출력](../stages/multi-agent/ma8-output/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC5 | [감정 · 불만 감지](../stages/voice/vc5-emotion/README.md) | ✅ 구현됨 | 목소리와 말에서 불만 · 격앙을 감지해 말투를 바꾸거나 상담원에게 넘긴다 | [A 의미 응용](../stages/llm/a-apps/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC6 | [상담원 실시간 보조](../stages/voice/vc6-assist/README.md) | ✅ 구현됨 | 자동 응답 대신 상담원 화면에 근거 · 추천 답 · 다음 질문을 실시간으로 띄운다 | [AS3 FAQ 답변](../stages/as-service/as3-faq/README.md) · [C6 상담원 이관](../stages/conversation/c6-handoff/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |
| VC7 | [통화 요약 · 후처리](../stages/voice/vc7-summary/README.md) | ✅ 구현됨 | 통화가 끝나면 요약 · 조치 · 다음 할 일을 정리해 티켓 · 고객 기록에 남긴다 | [C3 대화 메모리](../stages/conversation/c3-memory/README.md) · [AS7 티켓 · 이관](../stages/as-service/as7-ticket/README.md) | [실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약 · 실측](../stages/voice/vc1-stt/voice.md) |

## 설계 원칙

- 지연 예산부터 나눈다 — 인식 · 검색 · 생성 · 합성이 같은 1초를 나눠 쓴다(근거 읽기가 2/3 였던 실측)
- 먼저 말하고 나중에 고친다 — 첫 문장을 빨리 내고 나머지를 스트리밍(첫 글자 시간 기록이 이미 있음)
- 자동 응답이 어려우면 사람을 돕는다 — 상담원 화면에 근거 · 추천 답을 띄우는 것부터
- 음성은 개인정보 — 녹음 · 전사 보관 기간과 마스킹(보안 · 가드레일 맵)

## 예시

고객 전화 '세탁기에서 E4 가 떠요' → 실시간 전사 → 의도 · 모델 파악(프로필) → 캐시된 E4 안내를 0.5초 안에 첫 문장으로 → 고객이 '그건 해 봤어요' 끼어들면 즉시 멈추고 다음 조치로 → 해결 안 되면 통화 요약과 함께 기사 방문 접수.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
