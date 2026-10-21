<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 데이터 분석 에이전트 · Text-to-SQL 맵

스키마 연결 → 지표 정의(의미 계층) → SQL 생성 → 실행 검증 · 고치기 → 결과 해석 · 차트 → 권한 · 안전 → 실행 정확도 평가 — 사내 DB 에 자연어로 묻는 흐름

문서가 아니라 표에 있는 질문(지난달 E4 접수 건수, 모델별 재방문 비율)은 RAG 로 답할 수 없고 SQL 이 필요합니다. 이 프로젝트의 Text2Cypher(그래프 질의 생성 · 실행 검증)와 샌드박스 계산을 관계형 DB 로 넓힙니다. 틀린 SQL 도 그럴듯한 숫자를 내므로 실행 결과를 검증하는 것이 핵심입니다.

앱의 **맵 → 데이터 분석 에이전트 · Text-to-SQL 맵**(`/maps/analytics`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[스키마 연결] → [지표 정의 (의미 계층)]
                    ↓
[SQL 생성] → [실행 검증 · 고치기]
                    ↓
[결과 해석 · 차트] · [권한 · 안전] → [실행 정확도 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| DA1 | [스키마 연결](../stages/analytics/da1-schema/README.md) | ✅ 구현됨 | 표 · 열 설명 · 예시 값으로 질문과 관련된 표 · 열을 고른다 | [K2 온톨로지](../stages/knowledge-graph/k2-ontology/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA2 | [지표 정의 (의미 계층)](../stages/analytics/da2-semantic/README.md) | ✅ 구현됨 | '재방문 비율' 같은 업무 지표를 정의로 고정해 LLM 이 계산식을 만들지 않게 한다 | [K1 요구사항](../stages/knowledge-graph/k1-requirements/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA3 | [SQL 생성](../stages/analytics/da3-sql/README.md) | ✅ 구현됨 | 질문 · 연결된 스키마 · 지표 정의로 SQL 을 만든다 | [K6 Text2Cypher](../stages/knowledge-graph/k6-text2cypher/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA4 | [실행 검증 · 고치기](../stages/analytics/da4-verify/README.md) | ✅ 구현됨 | 읽기 전용으로 실행해 오류 · 빈 결과 · 이상 값이면 고쳐 다시 만든다 | [K6 Text2Cypher](../stages/knowledge-graph/k6-text2cypher/README.md) · [IO2 샌드박스](../stages/interop/io2-sandbox/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA5 | [결과 해석 · 차트](../stages/analytics/da5-explain/README.md) | ✅ 구현됨 | 결과 표를 문장 · 차트로 바꾸고 숫자는 결과에서만 쓴다 | [MA5 분석 에이전트](../stages/multi-agent/ma5-analysis-agent/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA6 | [권한 · 안전](../stages/analytics/da6-guard/README.md) | ✅ 구현됨 | 읽기 전용 · 행 · 열 권한 · 개인정보 열 · 무거운 질의를 막는다 | [G3 권한별 검색](../stages/guardrails/g3-acl/README.md) · [G2 개인정보](../stages/guardrails/g2-pii/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |
| DA7 | [실행 정확도 평가](../stages/analytics/da7-eval/README.md) | ✅ 구현됨 | 정답 SQL 과 결과가 같은지(실행 정확도)를 질문 유형별로 잰다 | [E1 평가 세트](../stages/evalops/e1-sets/README.md) | [데이터 분석 · Text-to-SQL — 분석 자료 · 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도 · 실측](../stages/analytics/da1-schema/analytics.md) |

## 설계 원칙

- 틀린 SQL 도 숫자를 낸다 — 실행 결과로 검증(Text2Cypher 실측: 실행 검증 재시도로 정확 일치 40 → 53%)
- 지표는 정의로 — LLM 이 계산식을 만들지 않게
- 읽기 전용 · 권한은 DB 에서 — 프롬프트로 막지 않는다
- 숫자는 결과에서만 — 지어낸 숫자 검사(장기 실행 완료 판정)

## 예시

'지난달 WM-200 E4 접수 중 재방문 비율은?' → 스키마 연결(상담 · 티켓 표) → 의미 계층의 '재방문' 정의 → SQL 생성 → 읽기 전용 실행 → 빈 결과면 날짜 조건을 고쳐 다시 → '31건 중 7건(22.6%)' 과 막대 차트, 숫자는 결과 표에서만.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
