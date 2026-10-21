<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 서비스 시나리오: 고객 AS 상담 맵

접수(텍스트 · 사진 · 음성) → 의도 · 긴급도 분류 → FAQ · 매뉴얼 답변 · 오류 사진 진단 → 조치 안내 → 검증 → 티켓 · 상담원 이관 → 피드백 — 기술 맵들을 실제 업무로 묶은 흐름

기술 맵이 아니라 업무 흐름 맵입니다. 고객 AS 상담 하나를 처음부터 끝까지 그리고, 단계마다 앞의 기술 맵에서 어느 단계를 쓰는지(기반 단계) 연결합니다. 같은 형식으로 '법률 질의 응대', '사내 규정 문의' 시나리오도 만들 수 있습니다.

앱의 **맵 → 서비스 시나리오: 고객 AS 상담 맵**(`/maps/as-service`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[문의 접수 (텍스트 · 사진 · 음성)] → [의도 · 긴급도 분류]
                    ↓                         ↓
       [FAQ · 매뉴얼 답변]          [오류 사진 진단]
                    └────────── ↓ ──────────┘
             [수리 · 조치 안내] → [품질 검증]
                                      ↓
        [접수 티켓 · 상담원 이관] → [피드백 · 개선]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| AS1 | [문의 접수 (텍스트 · 사진 · 음성)](../stages/as-service/as1-intake/README.md) | ✅ 구현됨 | 채팅 · 사진 · 음성 문의를 한 형식으로 받아 대화로 이어 간다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) · [C1 맥락 재작성](../stages/conversation/c1-rewrite/README.md) | [AS 상담 흐름](../stages/as-service/as1-intake/console.md) |
| AS2 | [의도 · 긴급도 분류](../stages/as-service/as2-triage/README.md) | ✅ 구현됨 | 문의 유형(고장 · 사용법 · 배송 · 환불)과 긴급도(안전 관련)를 나눠 처리 경로를 정한다 | [A 의미 응용](../stages/llm/a-apps/README.md) · [6 라우팅](../stages/llm/6-routing/README.md) | [분류 · 사진 진단 실측](../stages/as-service/as2-triage/eval.md) |
| AS3 | [FAQ · 매뉴얼 답변](../stages/as-service/as3-faq/README.md) | ✅ 구현됨 | 매뉴얼 · FAQ 에서 근거를 찾아 인용하며 답한다 — 쉬운 문의는 RAG 한 번 | [2 RAG](../stages/llm/2-rag/README.md) · [S1 캐시](../stages/serving/s1-cache/README.md) | [AS 상담 흐름](../stages/as-service/as1-intake/console.md) |
| AS4 | [오류 사진 진단](../stages/as-service/as4-photo/README.md) | ✅ 구현됨 | 오류 화면 · 부품 사진에서 오류 코드 · 증상을 읽고 매뉴얼의 해당 항목을 찾는다 | [MA2 멀티모달 RAG](../stages/multi-agent/ma2-rag/README.md) · [M 멀티모달](../stages/llm/m-multimodal/README.md) | [분류 · 사진 진단 실측](../stages/as-service/as2-triage/eval.md) |
| AS5 | [수리 · 조치 안내](../stages/as-service/as5-guide/README.md) | ✅ 구현됨 | 고객이 따라 할 수 있는 단계별 조치를 쓰고, 그림 · 음성으로도 낸다 | [MA6 작성 에이전트](../stages/multi-agent/ma6-report-agent/README.md) · [MA8 멀티모달 출력](../stages/multi-agent/ma8-output/README.md) | [AS 상담 흐름](../stages/as-service/as1-intake/console.md) |
| AS6 | [품질 검증](../stages/as-service/as6-verify/README.md) | ✅ 구현됨 | 안내가 매뉴얼과 맞는지 · 질문에 답하는지 · 안전 정책을 지키는지 확인한다 | [MA7 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) · [G4 출력 검사](../stages/guardrails/g4-output/README.md) | [AS 상담 흐름](../stages/as-service/as1-intake/console.md) |
| AS7 | [접수 티켓 · 상담원 이관](../stages/as-service/as7-ticket/README.md) | ✅ 구현됨 | 해결되지 않으면 방문 · 수리 접수 티켓을 만들고 대화 요약과 함께 상담원에게 넘긴다 | [C6 상담원 이관](../stages/conversation/c6-handoff/README.md) · [MA3 오케스트레이터](../stages/multi-agent/ma3-orchestrator/README.md) | [티켓 · 상담원 이관 · 지표](../stages/as-service/as7-ticket/tickets.md) |
| AS8 | [피드백 · 개선](../stages/as-service/as8-feedback/README.md) | ✅ 구현됨 | 해결 여부 · 만족도를 받아 실패 사례를 평가 세트 · 매뉴얼 보강으로 되돌린다 | [E5 피드백](../stages/evalops/e5-feedback/README.md) · [E8 개선 루프](../stages/evalops/e8-loop/README.md) | [티켓 · 상담원 이관 · 지표](../stages/as-service/as7-ticket/tickets.md) |

## 설계 원칙

- 단계마다 쓸 기술을 골라 쓴다 — 쉬운 FAQ 는 RAG 한 번, 사진 진단 · 복합 문의만 에이전트
- 답 전에 질문에 맞는지 · 매뉴얼과 맞는지 검증 — 근거에 있어도 질문과 상관없으면 틀린 답
- 안전 관련(감전 · 화재 · 가스)은 분류 즉시 사람에게 — 자동 답변 대상이 아니다
- 피드백을 평가 세트로 되돌린다(평가 · 관측 맵)

## 예시

고객: 사진(오류 코드 'E4' 화면) + '물이 안 빠져요' → 의도: 배수 고장, 긴급도: 보통 → 사진에서 E4 확인 · 매뉴얼의 E4 항목 검색 → '배수 필터 청소 3단계' 안내 + 그림 → 검증 통과 → 해결 여부 질문 → 미해결이면 티켓 생성 · 상담원 이관.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
