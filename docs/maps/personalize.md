<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 개인화 · 적응 맵

사용자 동의 → 명시적 선호 → 행동 신호 → 프로필 갱신 → 응답 전략 → 개인화 응답 → 피드백 — 개인화 데이터 · 인증 · 민감 정보 · 학습 동의를 나눠서

같은 질문에도 상담원은 고객마다 다르게 답합니다 — 이미 해 본 조치는 건너뛰고, 짧게 듣고 싶은 사람에게는 짧게. 개인화는 메모리(무엇을 아나) 위에 '어떻게 답할까'를 얹는 것이고, 무엇보다 동의 범위 안에서만 해야 합니다. 개인화 데이터 · 인증 정보 · 민감 정보 · 학습 동의를 서로 다른 것으로 다룹니다.

앱의 **맵 → 개인화 · 적응 맵**(`/maps/personalize`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[동의] → [명시적 선호] → [행동 신호]
                    ↓
[프로필 갱신] → [응답 전략]
                    ↓
[개인화 응답] → [피드백]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| PS1 | [사용자 동의](../stages/personalize/ps1-consent/README.md) | ✅ 구현됨 | 개인화 · 기록 보관 · 학습 사용 동의를 따로 받고 범위를 남긴다 | [RC6 고지 · 이의](../stages/compliance/rc6-notice/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS2 | [명시적 선호](../stages/personalize/ps2-explicit/README.md) | ✅ 구현됨 | 사용자가 직접 고른 선호(길이 · 말투 · 채널 · 언어)를 받는다 | [C4 프로필](../stages/conversation/c4-profile/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS3 | [행동 신호](../stages/personalize/ps3-behavior/README.md) | ✅ 구현됨 | 동의 범위 안에서 해결 단계 · 재질문 · 끊김 같은 행동 신호를 모은다 | [E5 피드백](../stages/evalops/e5-feedback/README.md) · [ME1 기억 추출](../stages/memory/me1-extract/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS4 | [프로필 갱신](../stages/personalize/ps4-profile/README.md) | ✅ 구현됨 | 선호 · 숙련도 · 상황을 프로필로 갱신하고 오래된 추정은 낮춘다 | [ME4 갱신 · 충돌](../stages/memory/me4-update/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS5 | [응답 전략 선택](../stages/personalize/ps5-strategy/README.md) | ✅ 구현됨 | 프로필로 길이 · 단계 수 · 설명 깊이 · 채널 형식을 고른다 | [6 라우팅](../stages/llm/6-routing/README.md) · [OM7 응답 형식](../stages/omni/om7-format/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS6 | [개인화 응답](../stages/personalize/ps6-respond/README.md) | ✅ 구현됨 | 이미 한 조치는 건너뛰고 숙련도에 맞춰 답한다 | [C1 맥락 재작성](../stages/conversation/c1-rewrite/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |
| PS7 | [사용자 피드백](../stages/personalize/ps7-feedback/README.md) | ✅ 구현됨 | 개인화가 실제로 도움이 됐는지 A/B · 피드백으로 잰다 | [AS8 피드백](../stages/as-service/as8-feedback/README.md) · [E7 A/B 실험](../stages/evalops/e7-ab/README.md) | [개인화 · 적응 — 범위별 동의 · 명시 선호 · 행동 신호 · 반감기 프로필 · 응답 전략 · 사실 보존 개인화 · 오프라인 평가](../stages/personalize/ps1-consent/personalize.md) |

## 설계 원칙

- 동의가 먼저 — 동의하지 않은 신호는 모으지 않는다
- 개인화 데이터 ≠ 인증 정보 ≠ 민감 정보 ≠ 학습 동의
- 개인화는 형식을 바꾸고 사실은 바꾸지 않는다

## 예시

고객이 '짧게 답해 주세요' 선택(명시적) · 지난 3번 모두 2단계에서 해결(행동) → 프로필: 간결 · 숙련 → 같은 E4 질문에 1 · 2단계만 짧게, '더 보기' 버튼 → 근거 · 사실은 같은 답과 동일한지 검사.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
