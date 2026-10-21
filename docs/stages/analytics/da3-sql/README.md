<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# DA3 · SQL 생성 (Text-to-SQL)

**상태: ⬜ 예정** — 질문 · 연결된 스키마 · 지표 정의로 SQL 을 만든다

## 원리

Text-to-SQL 은 자연어 질문을 SQL 로 바꾸는 것입니다. 예시 질문-SQL 쌍과 방언(SQLite · PostgreSQL)을 함께 줍니다.

## 왜 하는가

같은 질문을 여러 SQL 로 쓸 수 있고, 조인 · 날짜 · NULL 처리에서 자주 틀립니다.

## 어떻게 (이 앱에서)

- (기반) Text2Cypher(K6)
- (예정) 스키마 · 예시 · 방언 프롬프트 · 생성 정확도

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/da_sql` 에서 볼 수 있습니다.

## 앞으로 할 일

- 스키마 · 예시 · 방언 프롬프트 · 생성 정확도

## 상세 문서

- [데이터 분석 에이전트 · Text-to-SQL 맵](../../../maps/analytics.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [K6 Text2Cypher](../../knowledge-graph/k6-text2cypher/README.md) — 지식 그래프 · GraphRAG 맵 · ✅ 구현됨

---

← [DA2 지표 정의 (의미 계층)](../da2-semantic/README.md) · [전체 맵](../../../maps/analytics.md) · [DA4 실행 검증 · 고치기](../da4-verify/README.md) →
