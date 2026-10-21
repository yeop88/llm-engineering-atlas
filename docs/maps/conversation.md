<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 대화 · 메모리 맵

대화 맥락 질의 재작성 → 되묻기 → 대화 요약 메모리 → 사용자 · 제품 프로필 → 긴 대화 압축 → 상담원 이관 — 한 번이 아니라 이어지는 상담을 다루는 흐름

지금 답변은 질문 하나 단위입니다. 실제 고객 상담은 '그거 말고 다른 모델은요?' 처럼 앞 대화를 가리키고, 모호하면 되물어야 하고, 길어지면 앞부분을 잊지 않게 요약해야 하며, 안 되면 사람에게 넘겨야 합니다.

앱의 **맵 → 대화 · 메모리 맵**(`/maps/conversation`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[대화 맥락 질의 재작성] → [되묻기 (모호한 질문)] → [대화 요약 메모리]
                                      ↓
[사용자 · 제품 프로필] → [긴 대화 압축]
                                      ↓
                         [상담원 이관 · 인계 요약]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| C1 | [대화 맥락 질의 재작성](../stages/conversation/c1-rewrite/README.md) | ✅ 구현됨 | '그거 말고 다른 모델은요?' 처럼 앞 대화를 가리키는 질문을 혼자 읽혀도 되는 질문으로 바꿔 검색한다 | [4 검색 향상](../stages/llm/4-search-lab/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |
| C2 | [되묻기 (모호한 질문)](../stages/conversation/c2-clarify/README.md) | ✅ 구현됨 | 질문이 모호하거나 정보가 모자라면 답하기 전에 필요한 것을 되묻는다 | [6 라우팅](../stages/llm/6-routing/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |
| C3 | [대화 요약 메모리](../stages/conversation/c3-memory/README.md) | ✅ 구현됨 | 대화가 길어져도 중요한 사실(제품 · 증상 · 이미 해 본 조치)을 요약해 기억한다 | [2 RAG](../stages/llm/2-rag/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |
| C4 | [사용자 · 제품 프로필](../stages/conversation/c4-profile/README.md) | ✅ 구현됨 | 고객의 보유 제품 · 이전 문의 · 선호를 프로필로 두고 검색 · 답변에 쓴다 | [A 의미 응용](../stages/llm/a-apps/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |
| C5 | [긴 대화 압축](../stages/conversation/c5-compress/README.md) | ✅ 구현됨 | 긴 대화 · 긴 근거를 품질을 지키며 줄여 문맥 한도 안에 넣는다 | [2 RAG](../stages/llm/2-rag/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |
| C6 | [상담원 이관 · 인계 요약](../stages/conversation/c6-handoff/README.md) | ✅ 구현됨 | 자동으로 풀 수 없거나 위험한 문의는 대화 요약과 함께 사람에게 넘긴다 | [A 의미 응용](../stages/llm/a-apps/README.md) · [6 라우팅](../stages/llm/6-routing/README.md) | [대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측](../stages/conversation/c1-rewrite/conversation.md) |

## 설계 원칙

- 대화 맥락은 검색 전에 질문으로 풀어 쓴다 — 검색은 앞 대화를 모른다(검색 향상의 질의 재작성을 확장)
- 모르면 되묻는다 — 근거 밖에서 지어내는 것보다 낫다(답 없는 질문 거절이 약했던 법률 실측)
- 요약 · 압축은 품질을 잰다 — 근거 압축은 정답 문장을 버려 품질 −10 이었다
- 개인정보는 메모리에 오래 두지 않는다(보안 · 가드레일 맵)

## 예시

'세탁기 배수가 안 돼요' → '어느 모델인가요?'(되묻기) → '드럼 21kg 이요' → 프로필에 모델 저장 → '필터는 어디 있어요?' 를 '드럼 21kg 세탁기 배수 필터 위치' 로 바꿔 검색 → 해결 안 되면 대화 요약과 함께 상담원에게.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
