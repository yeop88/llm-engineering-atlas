<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# K6 · Text2Cypher (Natural language to graph query)

**상태: ✅ 구현됨** — 질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다

## 원리

LLM 에 그래프 스키마(온톨로지)와 질문을 주고 Cypher 쿼리를 만들게 한 뒤, 그래프 DB 가 실행한 결과로 답합니다. 숫자 · 목록 · 집계는 DB 가 계산하므로 LLM 이 지어낼 여지가 줄어듭니다.

## 왜 하는가

'작년에 가장 많이 제기된 결함 유형은?', '제23조를 인용한 판례는 몇 건?' 같은 집계 · 필터 질문은 문서 조각을 읽는 벡터 RAG 로는 정확히 답하기 어렵습니다. 대신 쿼리가 틀리면(없는 관계 이름 · 잘못된 방향) 결과가 비거나 엉뚱하므로, 생성한 쿼리를 검증하고 실패하면 다시 만드는 절차가 필요합니다.

## 어떻게 (이 앱에서)

- 스키마 설명은 온톨로지에서 자동, 예시 2개, 읽기 쿼리만(실행 전에 EXPLAIN 으로 쿼리 종류 확인 — 키워드 검사는 우회가 쉬움)
- 오류 · 빈 결과면 이유를 알려 다시 씀(최대 2번), 역량 질문 15개로 정확 일치 · 겹침 측정

## 화면

- `/kg/explore#cypher` — **Text2Cypher**: 질문 → Cypher → 결과

## 앞으로 할 일

- 큰 모델과 비교
- 자주 틀리는 유형 예시 보강

## 상세 문서

- [지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측](../k5-graph-db/graphrag.md)
- [지식 그래프 · GraphRAG 맵](../../../maps/knowledge-graph.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [8a 에이전틱 AI](../../llm/8a-agent/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [K5 그래프 DB](../k5-graph-db/README.md) · [전체 맵](../../../maps/knowledge-graph.md) · [K7 그래프 하이브리드 검색](../k7-graph-hybrid/README.md) →
