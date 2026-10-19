<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 보안 · 가드레일 · 거버넌스 맵

입력 방어 → 개인정보 마스킹 → 권한별 검색 → 출력 정책 → 감사 로그 · 라이선스 · 레드팀 — 써도 되는 답인지 확인하는 흐름

사내 문서와 법률 자료를 다루는 서비스는 '맞는 답'만으로는 내보낼 수 없습니다. 볼 권한이 없는 문서가 근거로 나오거나, 개인정보가 답에 섞이거나, 문서에 숨은 지시가 LLM 을 조종하면 사고입니다. 이 맵은 입력 · 검색 · 출력 · 기록 단계마다 지켜야 할 것을 둡니다.

앱의 **맵 → 보안 · 가드레일 · 거버넌스 맵**(`/maps/guardrails`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[입력 방어 (프롬프트 인젝션)] → [개인정보 탐지 · 마스킹] → [권한별 검색 (ACL)]
                                      ↓
             [출력 정책 검사] → [접근 제어 · 감사 로그]
                                      ↓
        [데이터 · 모델 라이선스 · 출처] · [레드팀 · 안전성 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| G1 | [입력 방어 (프롬프트 인젝션)](../stages/guardrails/g1-injection/README.md) | ⬜ 예정 | 사용자 입력과 근거 문서 속에 숨은 지시가 LLM 을 조종하지 못하게 막는다 | [2 RAG](../stages/llm/2-rag/README.md) · [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | — |
| G2 | [개인정보 탐지 · 마스킹](../stages/guardrails/g2-pii/README.md) | ⬜ 예정 | 주민번호 · 연락처 · 이름 같은 개인정보를 색인 전 · 답변 전에 찾아 가린다 | [2 RAG](../stages/llm/2-rag/README.md) · [A 의미 응용](../stages/llm/a-apps/README.md) | — |
| G3 | [권한별 검색 (ACL)](../stages/guardrails/g3-acl/README.md) | 🟡 기초 있음 | 사용자가 볼 수 있는 문서만 검색 후보에 넣는다 | [2 RAG](../stages/llm/2-rag/README.md) | — |
| G4 | [출력 정책 검사](../stages/guardrails/g4-output/README.md) | 🟡 기초 있음 | 답변이 근거 · 질문 · 정책을 어기지 않는지 내보내기 전에 검사한다 | [2 RAG](../stages/llm/2-rag/README.md) · [MA7 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) | — |
| G5 | [접근 제어 · 감사 로그](../stages/guardrails/g5-audit/README.md) | 🟡 기초 있음 | 누가 언제 무엇을 묻고 어떤 문서를 근거로 받았는지 남기고, 접근을 토큰 · 권한으로 막는다 | [2 RAG](../stages/llm/2-rag/README.md) | — |
| G6 | [데이터 · 모델 라이선스 · 출처](../stages/guardrails/g6-license/README.md) | 🟡 기초 있음 | 자료 · 모델마다 출처 · 라이선스 · 사용 조건을 기록하고 상업 사용 가능 여부를 확인한다 | [1 임베딩](../stages/llm/1-embedding/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | — |
| G7 | [레드팀 · 안전성 평가](../stages/guardrails/g7-redteam/README.md) | ⬜ 예정 | 공격 · 유도 질문 세트로 방어가 실제로 동작하는지 정기적으로 잰다 | [2 RAG](../stages/llm/2-rag/README.md) · [E1 평가 세트](../stages/evalops/e1-sets/README.md) | — |

## 설계 원칙

- 권한은 검색 단계에서 — 답변 후에 지우면 LLM 이 이미 읽었다. 볼 수 없는 문서는 후보에서 뺀다
- 근거 문서도 공격 경로 — 업로드된 문서 속 '이전 지시를 무시하라'는 사용자 입력과 같은 위험
- 규칙으로 정할 수 있는 검사는 규칙으로 — 주민번호 · 전화번호 패턴, 조문 번호처럼(번호 조회 실측의 교훈)
- 출처 · 라이선스는 수집 때 기록 — 공개 자료 가져오기가 문서마다 출처 · 라이선스를 남기는 이유

## 예시

인사팀 문서가 섞인 사내 컬렉션: 일반 직원 질문에는 인사 문서를 검색 후보에서 빼고(ACL), 답변에 직원 이름 · 연락처가 나오면 가리고, 누가 언제 무엇을 물었는지 남긴다.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
