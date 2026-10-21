<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# IO3 · 에이전트 간 위임 (A2A) (Agent-to-agent delegation)

**상태: ✅ 구현됨** — 다른 팀 · 다른 회사의 에이전트에게 작업을 맡기고 결과를 받아 검증한다

## 원리

A2A(Agent-to-Agent)는 에이전트가 서로의 능력 설명(Agent Card)을 보고 작업을 위임 · 진행 상황 확인 · 결과 수신하는 표준 방식입니다. 오케스트레이터가 내부 전문가 대신 외부 에이전트를 부르는 것과 같습니다.

## 왜 하는가

모든 능력을 한 시스템에 만들 수 없습니다. 법무팀의 계약 검토 에이전트, 협력사의 재고 에이전트를 연결하면 업무가 이어집니다. 대신 외부 결과는 신뢰 경계 밖에서 온 입력입니다.

## 어떻게 (이 앱에서)

- 에이전트 카드(/.well-known/agent-card.json, 기술 document_qa · compliance_scope)와 /a2a 의 message/send · tasks/get · tasks/cancel(A2A 0.3, JSON-RPC)
- 다른 에이전트에 맡기기: 결과 속 지시 문장을 빼고, 같은 질문으로 우리 자료를 찾아 근거 일치를 다시 재 0.5 이상일 때만 '받아들임'
- 받은 작업도 서비스 답변(가드레일 · 검증 · 요청 기록 · AI 응답 고지)으로 답함

## 화면

- `/interop/a2a` — **A2A 위임 · 작업**: 에이전트 카드 · 맡기기 · 결과 검증 · 작업

## 앞으로 할 일

- 스트리밍(message/stream) · 푸시 알림

## 상세 문서

- [에이전트 상호운용 — MCP 서버 · 샌드박스 · A2A · 상한 · 감사 · 실측](../io1-tools/interop.md)
- [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](../../../maps/interop.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [8a 에이전틱 AI](../../llm/8a-agent/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [IO2 권한 · 샌드박스](../io2-sandbox/README.md) · [전체 맵](../../../maps/interop.md) · [IO4 장기 작업 · 재시도 · 복구](../io4-longtask/README.md) →
