<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# DA3 · SQL 생성 (Text-to-SQL)

**상태: ✅ 구현됨** — 질문 · 연결된 스키마 · 지표 정의로 SQL 을 만든다

## 원리

Text-to-SQL 은 자연어 질문을 SQL 로 바꾸는 것입니다. 예시 질문-SQL 쌍과 방언(SQLite · PostgreSQL)을 함께 줍니다.

## 왜 하는가

같은 질문을 여러 SQL 로 쓸 수 있고, 조인 · 날짜 · NULL 처리에서 자주 틀립니다.

## 어떻게 (이 앱에서)

- (기반) Text2Cypher(K6)
- 연결한 스키마 카드(권한 없는 열은 아예 빼고) + 예시 질문-SQL + SQLite 방언 규칙(날짜 글자 비교 · substr · 100.0 *) → SQL 하나
- 연결 없이 전체 스키마를 넣는 방식과 비교

## 화면

- `/analytics/ask#ask` — **SQL 생성**: 연결한 스키마 · 예시 · 방언으로 SQL

## 상세 문서

- [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../da1-schema/analytics.md)
- [데이터 분석 에이전트 · Text-to-SQL 맵](../../../maps/analytics.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [K6 Text2Cypher](../../knowledge-graph/k6-text2cypher/README.md) — 지식 그래프 · GraphRAG 맵 · ✅ 구현됨

---

← [DA2 지표 정의 (의미 계층)](../da2-semantic/README.md) · [전체 맵](../../../maps/analytics.md) · [DA4 실행 검증 · 고치기](../da4-verify/README.md) →
