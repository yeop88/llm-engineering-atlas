<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)

도구 정의 · 검색(MCP) → 권한 · 샌드박스 → 에이전트 간 위임(A2A) → 장기 작업 · 복구 → 호출 · 비용 상한 → 감사 추적 — 신뢰 경계를 넘나드는 에이전트 연결

에이전트가 쓰는 도구를 표준 방식(MCP — Model Context Protocol)으로 연결하고, 다른 팀 · 다른 회사의 에이전트에게 일을 맡기는(A2A — Agent-to-Agent) 흐름입니다. 도구가 늘수록 할 수 있는 일이 늘지만, 외부 도구 · 외부 에이전트의 응답이 그대로 LLM 에 들어오므로 신뢰 경계를 넘을 때마다 권한 · 격리 · 기록이 필요합니다.

앱의 **맵 → 에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)**(`/maps/interop`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[도구 정의 · 검색 (MCP 서버)] → [권한 · 샌드박스]
                                      ↓
[에이전트 간 위임 (A2A)] → [장기 작업 · 재시도 · 복구]
                                      ↓
[호출 · 비용 상한] → [감사 추적 · 신뢰 경계]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 |
|---|---|---|---|---|
| IO1 | [도구 정의 · 검색 (MCP 서버)](../stages/interop/io1-io-tools/README.md) | ⬜ 예정 | 검색 · 조회 · 계산 같은 도구를 MCP 서버로 표준화해 어느 에이전트 · 앱에서나 쓰게 한다 | [8a 에이전틱 AI](../stages/8a-agent/README.md) |
| IO2 | [권한 · 샌드박스](../stages/interop/io2-io-sandbox/README.md) | ⬜ 예정 | 도구마다 할 수 있는 일(읽기 · 쓰기 · 네트워크)을 제한하고, 실행형 도구는 격리된 곳에서 돌린다 | [MA5 분석 에이전트](../stages/agents/ma5-analysis-agent/README.md) · [G1 입력 방어](../stages/guardrails/g1-gr-injection/README.md) |
| IO3 | [에이전트 간 위임 (A2A)](../stages/interop/io3-io-a2a/README.md) | ⬜ 예정 | 다른 팀 · 다른 회사의 에이전트에게 작업을 맡기고 결과를 받아 검증한다 | [MA3 오케스트레이터](../stages/agents/ma3-orchestrator/README.md) |
| IO4 | [장기 작업 · 재시도 · 복구](../stages/interop/io4-io-longtask/README.md) | ⬜ 예정 | 오래 걸리는 도구 · 위임 작업을 비동기로 돌리고, 끊기면 재시도 · 이어 하기를 한다 | [MA3 오케스트레이터](../stages/agents/ma3-orchestrator/README.md) |
| IO5 | [호출 · 비용 상한](../stages/interop/io5-io-limits/README.md) | ⬜ 예정 | 요청 하나가 쓸 수 있는 도구 호출 수 · 시간 · 비용에 상한을 두고, 넘으면 멈추고 알린다 | [S7 예산](../stages/serving/s7-sv-budget/README.md) |
| IO6 | [감사 추적 · 신뢰 경계](../stages/interop/io6-io-audit/README.md) | ⬜ 예정 | 어느 도구 · 에이전트가 무엇을 받아 무엇을 했는지 추적 id 로 남기고, 신뢰 경계를 넘은 입력을 표시한다 | [G5 감사 로그](../stages/guardrails/g5-gr-audit/README.md) · [E3 트레이싱](../stages/evalops/e3-ev-tracing/README.md) |

## 설계 원칙

- 도구 응답도 공격 경로 — 외부 도구 · 에이전트의 응답 속 지시는 간접 프롬프트 인젝션과 같다
- 도구는 적게, 고르는 일은 규칙으로 — 작은 모델은 도구가 많을수록 잘못 고르고, 번호 조회를 규칙으로 먼저 하게 하자 75% → 100%
- 실행 도구는 격리가 먼저 — 계산 도구가 eval 을 쓰지 않는 이유
- 호출 수 · 시간 상한 — 에이전트 측정에서 한 질문이 20분 걸렸다

## 예시

사내 에이전트가 MCP 로 '법령 조회' · '사내 위키 검색' · '일정 조회' 도구를 쓰고, 계약서 검토는 법무팀의 검토 에이전트에게 A2A 로 위임 → 위임 결과는 검증 후에만 답에 사용, 모든 도구 호출 · 위임은 추적 id 로 기록.

---

다른 맵: [LLM 시스템 엔지니어링 맵](../map.md) · [지식 그래프 · GraphRAG 맵](../kg-map.md) · [멀티에이전트 · 멀티모달 맵](../agents-map.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
