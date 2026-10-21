<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# DA4 · 실행 검증 · 고치기 (Execution-guided repair)

**상태: ✅ 구현됨** — 읽기 전용으로 실행해 오류 · 빈 결과 · 이상 값이면 고쳐 다시 만든다

## 원리

실행 검증은 SQL 을 실제로 돌려 오류 · 빈 결과 · 상식 밖 값(음수 건수, 100% 넘는 비율)을 찾아 그 정보로 다시 생성하는 것입니다.

## 왜 하는가

문법이 맞는 SQL 도 틀린 숫자를 냅니다. 실행해 본 결과만이 판정 근거입니다.

## 어떻게 (이 앱에서)

- (기반) Text2Cypher 실행 검증 재시도 · 샌드박스(IO2)
- 읽기 전용 실행 → SQL 오류 · 막힘 · 빈 결과 · 상식 밖 값(음수 건수 · 100 넘는 비율 · 모두 NULL) 이면 그 사실을 붙여 다시(상한), 빈 결과는 한 번만 다시(정말 없을 수 있음)
- 시도마다 SQL · 문제를 화면에 남기고, 사람이 고친 SQL 도 같은 가드로 실행

## 화면

- `/analytics/ask#ask` — **실행 검증 · 고치기**: 오류 · 빈 결과 · 이상 값 → 다시

## 상세 문서

- [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../da1-schema/analytics.md)
- [데이터 분석 에이전트 · Text-to-SQL 맵](../../../maps/analytics.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [K6 Text2Cypher](../../knowledge-graph/k6-text2cypher/README.md) — 지식 그래프 · GraphRAG 맵 · ✅ 구현됨
- [IO2 권한 · 샌드박스](../../interop/io2-sandbox/README.md) — 에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A) · ✅ 구현됨

---

← [DA3 SQL 생성](../da3-sql/README.md) · [전체 맵](../../../maps/analytics.md) · [DA5 결과 해석 · 차트](../da5-explain/README.md) →
