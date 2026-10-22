<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 규제 대응 · 컴플라이언스 맵

적용 규제 식별 → 위험 등급 → 규정 조항 ↔ 시스템 통제 매핑 → 데이터 처리 근거 · 설명 가능성 · 고지 → 영향 평가 · 정기 감사 — 법 조항을 시스템 요구로

개인정보보호법, 인공지능 기본법, 업종별 규정 같은 법 조항은 결국 '무엇을 기록하고, 무엇을 설명하고, 무엇을 막아야 하는가'라는 시스템 요구로 바뀝니다. 이 맵은 규정 조항과 시스템 통제(접근 제어 · 감사 로그 · 근거 기록 · 고지)를 연결해, 감사 때 '이 조항은 이 기능과 이 기록으로 지킨다'를 보일 수 있게 합니다. 이미 있는 법률 자료와 지식 그래프 맵을 그대로 씁니다. 이 맵은 기술 설계를 위한 정리이며 법률 자문이 아닙니다.

앱의 **맵 → 규제 대응 · 컴플라이언스 맵**(`/maps/compliance`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[적용 규제 식별] → [위험 등급 분류] → [규정 조항 ↔ 시스템 통제 매핑]
                                      ↓
[데이터 처리 근거 · 보관] · [설명 가능성 · 결정 기록] · [사용자 고지 · 이의 제기]
                                      ↓
                 [영향 평가] → [정기 감사 · 증적]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| RC1 | [적용 규제 식별](../stages/compliance/rc1-scope/README.md) | ✅ 구현됨 | 서비스 · 자료 · 사용자에 따라 적용되는 법령 · 지침을 목록으로 만들고 근거 조항을 연결한다 | [2 RAG](../stages/llm/2-rag/README.md) · [K1 요구사항](../stages/knowledge-graph/k1-requirements/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC2 | [위험 등급 분류](../stages/compliance/rc2-risk/README.md) | ✅ 구현됨 | AI 기능마다 영향 · 자율성 · 데이터 민감도로 위험 등급을 정하고 등급별 통제를 고른다 | [RC1 규제 식별](../stages/compliance/rc1-scope/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC3 | [데이터 처리 근거 · 보관](../stages/compliance/rc3-data/README.md) | ✅ 구현됨 | 자료 · 로그마다 수집 근거 · 목적 · 보관 기한을 기록하고, 기한이 지나면 지운다 | [G6 라이선스](../stages/guardrails/g6-license/README.md) · [D1 수집](../stages/docintel/d1-ingest/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC4 | [설명 가능성 · 결정 기록](../stages/compliance/rc4-explain/README.md) | ✅ 구현됨 | 답 · 결정마다 근거 문서 · 검증 결과 · 사용한 버전을 남겨 '왜 그렇게 답했나'를 설명할 수 있게 한다 | [2 RAG](../stages/llm/2-rag/README.md) · [G5 감사 로그](../stages/guardrails/g5-audit/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC5 | [영향 평가](../stages/compliance/rc5-impact/README.md) | ✅ 구현됨 | 출시 전에 정확도 · 편향 · 안전성 · 개인정보 영향을 측정해 기록하고 승인받는다 | [E2 회귀 평가](../stages/evalops/e2-offline/README.md) · [G7 레드팀](../stages/guardrails/g7-redteam/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC6 | [사용자 고지 · 이의 제기](../stages/compliance/rc6-notice/README.md) | ✅ 구현됨 | AI 가 답한다는 사실 · 한계를 알리고, 사람에게 다시 판단받을 길을 연다 | [C6 상담원 이관](../stages/conversation/c6-handoff/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC7 | [규정 조항 ↔ 시스템 통제 매핑](../stages/compliance/rc7-controls/README.md) | ✅ 구현됨 | 규정 조항과 시스템 통제(기능 · 설정 · 기록)를 그래프로 연결해 개정 영향을 바로 찾는다 | [K3 추출](../stages/knowledge-graph/k3-extract/README.md) · [K5 그래프 DB](../stages/knowledge-graph/k5-graph-db/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |
| RC8 | [정기 감사 · 증적](../stages/compliance/rc8-audit/README.md) | ✅ 구현됨 | 통제가 실제로 동작했는지 로그 · 측정 기록 표본으로 정기 점검하고 증적을 남긴다 | [G5 감사 로그](../stages/guardrails/g5-audit/README.md) · [E3 트레이싱](../stages/evalops/e3-tracing/README.md) | [규제 대응 — 규제 자료 · 적용 규제 · 조항-통제 그래프 · 감사 · 실측](../stages/compliance/rc1-scope/compliance.md) |

## 설계 원칙

- 조항과 통제를 그래프로 잇는다 — '판례 -인용→ 조문'처럼 '통제 -근거→ 조항', 조항이 개정되면 영향받는 통제를 바로 찾는다
- 설명은 기록에서 나온다 — 근거 인용 · 검증 결과 · 실행 이력이 이미 '왜 그렇게 답했나'의 증적
- 규정 문서도 문서 처리 · 버전 관리 대상 — 개정 전후 조항이 섞이면 잘못된 통제로 이어진다
- 판단이 필요한 부분은 사람이 — 위험 등급 · 영향 평가 결론은 자동 분류가 아니라 검토를 거친다

## 예시

상담 AI 출시 전: 적용 규제 목록(개인정보 · 소비자 보호 · AI 고지) → 상담 기능을 위험 등급으로 분류 → 각 조항을 통제(개인정보 마스킹 · 보관 30일 · AI 응답 고지 · 상담원 이관 요청권)에 연결 → 영향 평가 기록 → 분기마다 감사 로그 표본 점검.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md)
