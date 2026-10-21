<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 코딩 에이전트 · 소프트웨어 엔지니어링 맵

코드 검색 · 저장소 이해 → 작업 계획 → 수정 · 패치 → 테스트 실행 · 고치기 → 리뷰 · 보안 검사 → 해결률 평가 — 코드를 고치는 에이전트

가장 빨리 업무에 들어온 에이전트는 코딩 에이전트입니다. 코드는 테스트로 정답을 확인할 수 있어 검증 가능한 과제의 대표이고, 저장소 검색은 RAG 의 다른 모양입니다. 이 프로젝트 저장소 자체(테스트 700여 개 · 구조 규칙 검사)를 과제로 써서 코드 검색 · 패치 · 테스트 실행 · 리뷰를 재는 맵입니다.

앱의 **맵 → 코딩 에이전트 · 소프트웨어 엔지니어링 맵**(`/maps/coding`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[코드 검색 · 저장소 이해] → [작업 계획]
                    ↓
[수정 · 패치] → [테스트 실행 · 고치기]
                    ↓
[리뷰 · 보안 검사] → [해결률 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| CD1 | [코드 검색 · 저장소 이해](../stages/coding/cd1-index/README.md) | ✅ 구현됨 | 함수 · 파일 단위로 나누고 기호 · 호출 관계로 관련 코드를 찾는다 | [2 RAG](../stages/llm/2-rag/README.md) · [K3 추출](../stages/knowledge-graph/k3-extract/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |
| CD2 | [작업 계획](../stages/coding/cd2-plan/README.md) | ✅ 구현됨 | 이슈를 바꿀 파일 · 단계 · 확인할 테스트로 나눈다 | [LR1 목표 분해](../stages/longrun/lr1-goal/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |
| CD3 | [수정 · 패치](../stages/coding/cd3-patch/README.md) | ✅ 구현됨 | 정확한 문자열 교체 · diff 로 고치고 형식 검사를 통과시킨다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |
| CD4 | [테스트 실행 · 고치기](../stages/coding/cd4-test/README.md) | ✅ 구현됨 | 샌드박스에서 테스트를 돌려 실패 출력으로 다시 고친다 | [IO2 샌드박스](../stages/interop/io2-sandbox/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |
| CD5 | [리뷰 · 보안 검사](../stages/coding/cd5-review/README.md) | ✅ 구현됨 | 비밀 · 위험 함수 · 구조 규칙을 검사하고 LLM 이 리뷰한다 | [G4 출력 검사](../stages/guardrails/g4-output/README.md) · [MA7 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |
| CD6 | [해결률 평가](../stages/coding/cd6-eval/README.md) | ✅ 구현됨 | 일부러 깬 코드와 테스트로 과제를 만들어 해결률 · 걸음 · 토큰을 잰다 | [RV1 과제 설계](../stages/rlvr/rv1-tasks/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | [코딩 에이전트 — 코드 검색 · 깬 코드 과제 · 계획 · 패치 · 테스트 주도 고치기 · 리뷰 · 해결률 · 실측](../stages/coding/cd1-index/coding.md) |

## 설계 원칙

- 테스트가 정답이다 — 검증 가능한 과제(RLVR)
- 코드 검색은 기호가 먼저 — 함수 이름 · 호출 관계(BM25 혼합)
- 패치는 작게 · 확인하며 — 한 번에 하나, 매번 테스트
- 구조 규칙도 테스트다 — 의존 방향 검사(test_architecture)

## 예시

'컬렉션을 지워도 남는 행' 이슈 → 코드 검색(삭제 함수 · collection_id 열) → 계획(외래 키 없는 표 찾기) → 패치 → 테스트 실행(실패 → 고침) → 리뷰(해시 사슬 기록은 고치지 않음) → 해결률 기록.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
