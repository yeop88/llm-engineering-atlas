<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# K5 · 그래프 DB (Graph database (Neo4j · FalkorDB))

**상태: ✅ 구현됨** — 노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다

## 원리

그래프 DB 는 데이터를 표가 아니라 노드(Node)와 관계(Relationship)로 저장합니다. Neo4j 는 노드가 이웃의 위치를 직접 가리키는 방식(Index-free Adjacency)이라, 관계를 여러 번 건너는 질의(Multi-hop)를 표 JOIN 없이 이웃을 따라가며 처리합니다. 질의 언어 Cypher 는 `(판례)-[:인용]->(조문)` 처럼 그래프 패턴을 그림처럼 씁니다. 노드 속성에 임베딩을 넣고 벡터 인덱스로 찾을 수도 있습니다.

## 왜 하는가

관계형 DB 에서 '판례 → 인용 조문 → 그 조문을 위임한 시행령 → 그 시행령을 인용한 다른 판례' 같은 질의는 JOIN 이 단계마다 늘어 느려지고 쓰기도 어렵습니다. 벡터 인덱스가 같은 DB 에 있으면 '비슷한 글 찾기'와 '연결 따라가기'를 한 질의로 합칠 수 있어 GraphRAG(K7)에 맞습니다.

## 어떻게 (이 앱에서)

- 내장 그래프 저장소(앱 DB 의 노드 · 관계 표, 마이그레이션 0012)가 원본 — 서버 없이도 이웃 확장 · 커뮤니티가 돈다
- Neo4j(docker compose --profile neo4j, 5.26 LTS)로 통째로 옮겨 Cypher 실행, 같은 자료를 다시 적재해도 개체 · 관계가 늘지 않음
- 두 번째 엔진 FalkorDB(Redis 모듈, OpenCypher)에도 같은 그래프를 옮겨 같은 역량 질문으로 방언 · 속도 · 무게를 비교

## 화면

- `/kg/explore` — **그래프 탐색 · Cypher**: 노드 · 이웃 탐색, Cypher 엔진(Neo4j · FalkorDB) · Text2Cypher, 역량 질문

## 앞으로 할 일

- ArangoDB 등 다른 그래프 DB 어댑터(보류)

## 상세 문서

- [지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측](graphrag.md)
- [지식 그래프 · GraphRAG 맵](../../../maps/knowledge-graph.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [2 RAG 검색](../../llm/2-rag/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [K4 지식 융합 · 정제](../k4-fusion/README.md) · [전체 맵](../../../maps/knowledge-graph.md) · [K6 Text2Cypher](../k6-text2cypher/README.md) →
