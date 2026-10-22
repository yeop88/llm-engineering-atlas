<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

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

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| IO1 | [도구 정의 · 검색 (MCP 서버)](../stages/interop/io1-tools/README.md) | ✅ 구현됨 | 검색 · 조회 · 계산 같은 도구를 MCP 서버로 표준화해 어느 에이전트 · 앱에서나 쓰게 한다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |
| IO2 | [권한 · 샌드박스](../stages/interop/io2-sandbox/README.md) | ✅ 구현됨 | 도구마다 할 수 있는 일(읽기 · 쓰기 · 네트워크)을 제한하고, 실행형 도구는 격리된 곳에서 돌린다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) · [G1 입력 방어](../stages/guardrails/g1-injection/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |
| IO3 | [에이전트 간 위임 (A2A)](../stages/interop/io3-a2a/README.md) | ✅ 구현됨 | 다른 팀 · 다른 회사의 에이전트에게 작업을 맡기고 결과를 받아 검증한다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |
| IO4 | [장기 작업 · 재시도 · 복구](../stages/interop/io4-longtask/README.md) | ✅ 구현됨 | 오래 걸리는 도구 · 위임 작업을 비동기로 돌리고, 끊기면 재시도 · 이어 하기를 한다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |
| IO5 | [호출 · 비용 상한](../stages/interop/io5-limits/README.md) | ✅ 구현됨 | 요청 하나가 쓸 수 있는 도구 호출 수 · 시간 · 비용에 상한을 두고, 넘으면 멈추고 알린다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |
| IO6 | [감사 추적 · 신뢰 경계](../stages/interop/io6-audit/README.md) | ✅ 구현됨 | 어느 도구 · 에이전트가 무엇을 받아 무엇을 했는지 추적 id 로 남기고, 신뢰 경계를 넘은 입력을 표시한다 | [G5 감사 로그](../stages/guardrails/g5-audit/README.md) · [E3 트레이싱](../stages/evalops/e3-tracing/README.md) | [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../stages/interop/io1-tools/interop.md) |

## 설계 원칙

- 도구 응답도 공격 경로 — 외부 도구 · 에이전트의 응답 속 지시는 간접 프롬프트 인젝션과 같다
- 도구는 적게, 고르는 일은 규칙으로 — 작은 모델은 도구가 많을수록 잘못 고르고, 번호 조회를 규칙으로 먼저 하게 하자 75% → 100%
- 실행 도구는 격리가 먼저 — 계산 도구가 eval 을 쓰지 않는 이유
- 호출 수 · 시간 상한 — 에이전트 측정에서 한 질문이 20분 걸렸다

## 예시

사내 에이전트가 MCP 로 '법령 조회' · '사내 위키 검색' · '일정 조회' 도구를 쓰고, 계약서 검토는 법무팀의 검토 에이전트에게 A2A 로 위임 → 위임 결과는 검증 후에만 답에 사용, 모든 도구 호출 · 위임은 추적 id 로 기록.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md)
