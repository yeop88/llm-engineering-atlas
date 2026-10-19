# 지식 그래프 · GraphRAG 맵

두 번째 맵입니다(세 번째는 [멀티에이전트 · 멀티모달 맵](multi-agent.md)). [LLM 시스템 엔지니어링 맵](llm.md)이 문서를 조각(청크)으로 나눠 벡터로 찾고 답하는 흐름이라면, 이 맵은 문서 속 **개념과 관계를 구조(그래프)로 저장**하고 LLM 과 결합(GraphRAG)해, 벡터 RAG 가 약한 **다단계 추론 · 정확한 집계 · 전체 요약** 질문에 답하는 흐름입니다.

앱의 **맵 → 지식 그래프 · GraphRAG 맵**(`/maps/knowledge-graph`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. 화면 문구와 단계별 README 는 단계 레지스트리(`app/stages/registry/`)에서 만들어집니다. **지금은 모든 단계가 '예정'** 이고, 진행할 때 테스트 화면이 생깁니다.

## 전체 흐름

```
① 구축 (탑다운 + 바텀업)
[K1 요구사항 정의] → [K2 온톨로지 설계] → [K3 데이터 추출 (ETL · LLM)] → [K4 지식 융합 · 정제]
                                               ↓
② 저장                               [K5 그래프 DB (Neo4j · Cypher · 벡터 인덱스)]
                                               ↓
③ 활용 (GraphRAG)  → 정확한 집계 · 필터:     [K6 Text2Cypher]
                   → 연결된 맥락(다단계):    [K7 그래프 하이브리드 검색]
                   → 전체 주제 · 추세:       [K8 글로벌 커뮤니티 요약]
                                               ↓
LLM 맵과 만나는 곳: 1단계 검색은 2 RAG 검색 그대로, 답변은 같은 근거 인용 · 근거 일치 · 질문 관련성 검증,
                   벡터 RAG / GraphRAG 선택은 6 라우팅의 갈래
```

## 단계

<!-- 단계 표: scripts/gen_docs.py 가 레지스트리로 채웁니다. 이 표시 사이는 고치지 마세요. -->
| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| K1 | [요구사항 정의](../stages/knowledge-graph/k1-requirements/README.md) | ⬜ 예정 | 지식 그래프가 답해야 할 업무 질문 10~15개로 그래프의 범위를 정한다 | — | — |
| K2 | [온톨로지 설계](../stages/knowledge-graph/k2-ontology/README.md) | ⬜ 예정 | 도메인의 개념(클래스) · 속성 · 관계와 그 규칙을 기계가 읽는 스키마로 정의한다 | — | — |
| K3 | [데이터 추출](../stages/knowledge-graph/k3-extract/README.md) | ⬜ 예정 | 정형 데이터는 스키마 매핑으로, 비정형 문서는 LLM 으로 [주어-관계-목적어] 트리플을 뽑는다 | [2 RAG](../stages/llm/2-rag/README.md) | — |
| K4 | [지식 융합 · 정제](../stages/knowledge-graph/k4-fusion/README.md) | ⬜ 예정 | 다른 이름의 같은 개체를 하나로 묶고(개체 정규화) 중복 · 충돌을 정리해 그래프를 완성한다 | [2 RAG](../stages/llm/2-rag/README.md) · [A 의미 응용](../stages/llm/a-apps/README.md) | — |
| K5 | [그래프 DB](../stages/knowledge-graph/k5-graph-db/README.md) | ⬜ 예정 | 노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다 | [2 RAG](../stages/llm/2-rag/README.md) | — |
| K6 | [Text2Cypher](../stages/knowledge-graph/k6-text2cypher/README.md) | ⬜ 예정 | 질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | — |
| K7 | [그래프 하이브리드 검색](../stages/knowledge-graph/k7-graph-hybrid/README.md) | ⬜ 예정 | 벡터 검색으로 찾은 청크에서 연결된 개체 · 관계(서브그래프)를 함께 가져와 답변 맥락을 넓힌다 | [2 RAG](../stages/llm/2-rag/README.md) · [3 리랭킹](../stages/llm/3-rerank/README.md) | [LLM 맵 · 2 RAG 검색](../stages/llm/2-rag/rag.md) |
| K8 | [글로벌 커뮤니티 요약](../stages/knowledge-graph/k8-community-summary/README.md) | ⬜ 예정 | 그래프를 계층적 커뮤니티로 나눠 미리 요약해 두고, 전체 주제 · 추세 질문은 요약들을 모아 답한다 | [A 의미 응용](../stages/llm/a-apps/README.md) | — |
<!-- /단계 표 -->

## 1. 구축 — 지식 그래프 만들기와 온톨로지

구축은 **탑다운**(스키마 먼저: 무엇에 답할지 정하고 설계도를 그림)과 **바텀업**(데이터 먼저: 문서에서 뽑아 보며 설계를 고침)을 섞습니다.

| 단계 | 하는 일 | 왜 |
|---|---|---|
| [K1 요구사항 정의](../stages/knowledge-graph/k1-requirements/README.md) | 그래프가 답해야 할 업무 질문(역량 질문) 10~15개와 기대 답 | 범위가 없으면 개념 · 관계가 끝없이 늘고 이름이 제각각인, 쿼리할 수 없는 그래프가 됨. 완성 후 검수 기준 |
| [K2 온톨로지 설계](../stages/knowledge-graph/k2-ontology/README.md) | 클래스(개념) · 속성 · 관계와 규칙. W3C 표준 RDF · OWL · SHACL, 속성 그래프에선 레이블 · 관계 타입 · 제약 조건 | 추출 · 융합이 같은 설계도를 따르고, 검증 규칙으로 잘못된 관계를 저장 전에 거름. 원칙: 명확성 · 정합성 · 확장성 |
| [K3 데이터 추출](../stages/knowledge-graph/k3-extract/README.md) | 정형(RDB · CSV)은 스키마 매핑, 비정형(문서)은 LLM 으로 개체명 인식 · 관계 추출 → [주어-관계-목적어] | 매핑이 추출보다 정확 · 저렴하니 먼저, LLM 은 나머지에만. 근거 문장을 남겨 출처를 댈 수 있게 |
| [K4 지식 융합 · 정제](../stages/knowledge-graph/k4-fusion/README.md) | 같은 대상의 다른 이름('미국' · 'USA' · 'United States')을 한 노드로, 중복 · 충돌 정리 | 갈라진 노드는 다단계 탐색을 끊고 집계를 틀리게 함 — 연결이 곧 답 |

## 2. 저장 — 그래프 DB (Neo4j)

[K5 그래프 DB](../stages/knowledge-graph/k5-graph-db/README.md): 데이터를 표가 아니라 **노드와 관계**로 저장합니다.

- **JOIN 없는 다단계 탐색**: Neo4j 는 노드가 이웃의 위치를 직접 가리켜(Index-free Adjacency), 관계를 여러 번 건너는 질의를 표 JOIN 없이 이웃을 따라가며 처리합니다. 관계형 DB 는 단계마다 JOIN 이 늘어 느려지고 쓰기 어렵습니다.
- **Cypher**: 그래프 패턴을 그림처럼 쓰는 질의 언어입니다.

  ```cypher
  // 김철수가 근무하는 회사의 파트너사
  MATCH (p:Person {name: "김철수"})-[:WORKS_AT]->(c:Company)-[:PARTNER_WITH]->(partner:Company)
  RETURN partner.name
  ```

- **벡터 인덱스 내장**: 노드 속성의 임베딩을 같은 DB 에서 찾을 수 있어, '비슷한 글 찾기'와 '연결 따라가기'를 한 질의로 합칠 수 있습니다. LangChain · LlamaIndex 등 AI 프레임워크와의 연동 자료도 가장 많습니다.

## 3. 활용 — GraphRAG

벡터 RAG 는 질문과 비슷한 조각만 가져오므로, 문맥 전체를 관통하는 종합 질문이나 여러 문서를 잇는 다단계 질문에 약합니다. GraphRAG 는 그래프와 결합해 이를 보완하며, 세 가지 방식이 있습니다.

| 방식 | 동작 | 맞는 질문 | 주의 |
|---|---|---|---|
| [K6 Text2Cypher](../stages/knowledge-graph/k6-text2cypher/README.md) | LLM 이 질문을 Cypher 로 바꾸고 그래프 DB 가 실행 | 정확한 집계 · 필터("작년에 가장 많은 결함 유형은?") | DB 가 계산하니 숫자를 지어낼 여지가 줄지만, 쿼리가 틀리면 결과가 비거나 엉뚱함 → 스키마 검증 · 재시도 · 읽기 전용 |
| [K7 그래프 하이브리드 검색](../stages/knowledge-graph/k7-graph-hybrid/README.md) | 벡터로 비슷한 청크를 찾고, 연결된 개체 · 관계(서브그래프)를 함께 가져옴 | 연결된 맥락이 필요한 질문 | 확장 범위(몇 단계까지)에 따라 근거가 길어짐 — 질문 관련성 검증과 함께 |
| [K8 글로벌 커뮤니티 요약](../stages/knowledge-graph/k8-community-summary/README.md) | 그래프를 계층적 커뮤니티로 나눠 미리 요약, 질문엔 요약들을 모아 답(Microsoft GraphRAG 방식) | 전체 주제 · 추세 | 요약을 미리 만드는 비용(LLM 호출 = 커뮤니티 수), 자료가 바뀌면 다시 |

## 이 프로젝트에 적용하는 순서 (계획)

첫 도메인은 이미 있는 **법률 공개 자료**(법령 6 · 대법원 판례 164, [데이터 처리 기록](../guides/data-processing.md))입니다.

1. **K1** 법률 역량 질문 15개 — 판례-조문 인용, 쟁점별 집계, 법령 간 위임 관계. 벡터 RAG 로 어려운 질문(여러 문서 · 집계 · 전체 요약)을 표시합니다. 법률 재측정에서 여러 문서 질문의 검색 nDCG 가 37 로 가장 낮았습니다.
2. **K2** 법률 온톨로지 v1 — 법령 · 조문 · 항 · 판례 · 쟁점 · 당사자 유형 / 인용 · 속함 · 위임 근거 · 다룸.
3. **K3 정형 먼저** — 판례 메타데이터의 참조조문으로 '판례 -인용→ 조문'을 LLM 없이 바로. 그다음 판결요지에서 LLM 트리플 추출.
4. **K4** 조문 번호 정규화는 기존 파서(`app/stages/rag/legal.py`) 재사용.
5. **K5** Neo4j 를 docker compose 프로필로 추가, 그래프 저장소 인터페이스.
6. **K6~K8** 각각 역량 질문 · 여러 문서 질문 · 전체 요약 질문으로 벡터 RAG 와 짝지어 비교 — LLM 맵의 연결 비교에 경로로 넣습니다.

각 단계는 LLM 맵과 같은 원칙을 따릅니다: 사람 판정으로 자동 판정을 보정하고, 실측(날짜 · 자료 · 설정 · 해석 · 한계)을 단계 문서에 남기며, 답변은 질문과 관련된 근거로만 합니다.

---

다른 맵: [문서 색인의 맵 목록](../README.md#맵)
