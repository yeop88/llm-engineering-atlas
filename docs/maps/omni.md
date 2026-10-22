<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 옴니채널 · 실시간 멀티모달 에이전트 맵

채널 통합 세션 → 실시간 음성 대화 → 영상 스트림 분석 → 멀티모달 턴 융합 → 채널 간 이어 가기 → 비동기 메시지 처리 → 채널별 응답 형식 → 옴니 평가 — 전화 · 영상 · 메신저를 한 에이전트로

고객은 채팅으로 시작해 사진을 보내고, 전화로 바꾸고, 영상 통화로 세탁기를 비춥니다. 채널마다 따로 만든 봇은 앞의 대화를 모릅니다. 채널을 하나의 세션으로 묶고, 음성 · 영상 · 글을 같은 턴으로 합치며, 메신저처럼 늦게 오고 다시 오는 메시지를 안전하게 처리하는 것이 옴니채널 에이전트입니다.

앱의 **맵 → 옴니채널 · 실시간 멀티모달 에이전트 맵**(`/maps/omni`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[채널 통합 세션] → [실시간 음성 대화] · [영상 스트림 분석]
                    ↓
[멀티모달 턴 융합] → [채널 간 이어 가기]
                    ↓
[비동기 메시지 처리] → [채널별 응답 형식] → [옴니 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| OM1 | [채널 통합 세션](../stages/omni/om1-channel/README.md) | ⬜ 예정 | 채팅 · 메신저 · 이메일 · 전화 · 영상을 같은 메시지 봉투와 고객 세션으로 묶는다 | [AS1 문의 접수](../stages/as-service/as1-intake/README.md) · [C4 프로필](../stages/conversation/c4-profile/README.md) | — |
| OM2 | [실시간 음성 대화](../stages/omni/om2-voice/README.md) | ⬜ 예정 | 말하는 도중 인식 · 끼어들기 · 문장 단위 합성으로 사람처럼 주고받는다 | [VC1 음성 인식](../stages/voice/vc1-stt/README.md) · [VC2 턴 관리](../stages/voice/vc2-turn/README.md) · [VC4 음성 합성](../stages/voice/vc4-tts/README.md) | — |
| OM3 | [영상 스트림 분석](../stages/omni/om3-video/README.md) | ⬜ 예정 | 장면이 바뀐 프레임만 골라 읽고 사건 · 시간 색인을 만든다 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) · [AS4 사진 진단](../stages/as-service/as4-photo/README.md) | — |
| OM4 | [멀티모달 턴 융합](../stages/omni/om4-fuse/README.md) | ⬜ 예정 | 음성 · 지금 프레임 · 첨부를 한 턴으로 합치고 '이거' 같은 가리킴을 푼다 | [OM2 실시간 음성](../stages/omni/om2-voice/README.md) · [OM3 영상 분석](../stages/omni/om3-video/README.md) · [C1 맥락 재작성](../stages/conversation/c1-rewrite/README.md) | — |
| OM5 | [채널 간 이어 가기](../stages/omni/om5-handoff/README.md) | ⬜ 예정 | 채팅에서 전화로, 통화가 끊기면 메신저로 — 같은 맥락을 이어 간다 | [OM1 채널 통합](../stages/omni/om1-channel/README.md) · [C6 상담원 이관](../stages/conversation/c6-handoff/README.md) | — |
| OM6 | [비동기 메시지 처리](../stages/omni/om6-async/README.md) | ⬜ 예정 | 늦게 · 두 번 · 순서가 바뀌어 오는 메시지를 대기열 · 멱등 키로 한 번만 처리한다 | [IO3 A2A 위임](../stages/interop/io3-a2a/README.md) · [LR3 체크포인트](../stages/longrun/lr3-state/README.md) | — |
| OM7 | [채널별 응답 형식](../stages/omni/om7-format/README.md) | ⬜ 예정 | 같은 답을 음성은 짧게 · 채팅은 단계로 · 문자는 글자 수 안에 바꾼다 | [VC4 음성 합성](../stages/voice/vc4-tts/README.md) · [G4 출력 검사](../stages/guardrails/g4-output/README.md) | — |
| OM8 | [옴니 평가](../stages/omni/om8-eval/README.md) | ⬜ 예정 | 채널을 바꾸는 시나리오로 맥락 이어짐 · 채널별 지연 · 답의 일관성을 잰다 | [E1 평가 세트](../stages/evalops/e1-sets/README.md) | — |

## 설계 원칙

- 채널이 아니라 사람 · 세션 단위로 — 같은 고객이면 채널을 바꿔도 이어진다
- 영상은 전부 보지 않는다 — 장면이 바뀐 순간만 읽는다(같은 장면 제외)
- 메시지는 늦게 · 두 번 온다 — 멱등 키로 한 번만 처리
- 채널마다 말하는 법이 다르다 — 음성은 짧게, 채팅은 단계로

## 예시

카톡형 메신저 '세탁기 문이 안 열려요' → 같은 고객의 영상 통화로 이어 감 → 영상에서 장면이 바뀐 프레임만 읽어 'E4 표시 · 잠금 아이콘' 을 찾음 → '이거 뭐예요?' 의 '이거'를 지금 프레임으로 풀어 답 → 통화가 끊기면 메신저로 요약 · 다음 할 일을 보냄(같은 메시지 두 번 와도 한 번만).

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md)
