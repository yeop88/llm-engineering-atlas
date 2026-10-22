<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 실시간 오디오 · 비디오 풀듀플렉스 맵

연속 오디오 · 비디오 → 화자 · 시선 · 대상 추적 → 시간 상태 융합 → 발화 의도 예측 → 끼어들 시점 → 동시 듣기 · 보기 · 말하기 → 전환 타이밍 — 내용 이해와 대화 타이밍을 나눠서

반이중(차례로 말하기) 음성 상담은 끝점을 기다린 뒤 답합니다. 사람은 듣는 동안 맞장구치고, 상대가 말을 맺기 전에 대답을 준비하고, 화면을 보며 말합니다. 오디오 · 비디오를 한 구조에서 계속 처리하며 응답 시점까지 모델링하는 풀듀플렉스는 아직 실험 단계라, 이 맵은 내용 이해 · 대화 타이밍 · 차례 · 화자 · 시각 가리킴 · 끼어들기 정책 · 안전 정책을 나눠 설계하고 흉내 실험으로 타이밍 규칙을 잽니다.

앱의 **맵 → 실시간 오디오 · 비디오 풀듀플렉스 맵**(`/maps/duplex`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[연속 입력] → [화자 · 시선 · 대상] → [상태 융합]
                    ↓
[발화 의도] → [끼어들 시점]
                    ↓
[동시 듣기 · 말하기] → [전환 타이밍]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| FD1 | [연속 오디오 · 비디오 입력](../stages/duplex/fd1-input/README.md) | 🔬 연구 | 소리 · 영상을 끊지 않고 같은 시계로 받는다 | [RT1 스트림 입력](../stages/realtime/rt1-input/README.md) | — |
| FD2 | [화자 · 시선 · 대상 추적](../stages/duplex/fd2-track/README.md) | 🔬 연구 | 누가 말하는지, 어디를 보고 가리키는지 따라간다 | [AU3 화자 · 언어](../stages/audio/au3-speaker/README.md) · [VD4 추적](../stages/video/vd4-track/README.md) | — |
| FD3 | [시간 상태 융합](../stages/duplex/fd3-fuse/README.md) | 🔬 연구 | 말 · 화면 · 사건을 하나의 대화 상태로 시간에 따라 합친다 | [OM4 턴 융합](../stages/omni/om4-fuse/README.md) · [RT4 상태 갱신](../stages/realtime/rt4-state/README.md) | — |
| FD4 | [발화 의도 예측](../stages/duplex/fd4-intent/README.md) | 🔬 연구 | 상대가 말을 맺을지 · 이어 갈지 · 끼어들기를 원하는지 예측한다 | [VC2 턴 관리](../stages/voice/vc2-turn/README.md) | — |
| FD5 | [끼어들기 시점 · 정책](../stages/duplex/fd5-barge/README.md) | 🔬 연구 | 언제 끼어들고 언제 맞장구만 칠지 정책으로 정한다 | [VC2 턴 관리](../stages/voice/vc2-turn/README.md) · [G4 출력 검사](../stages/guardrails/g4-output/README.md) | — |
| FD6 | [동시 듣기 · 보기 · 말하기](../stages/duplex/fd6-duplex/README.md) | 🔬 연구 | 말하는 동안에도 듣고 보며 응답을 고친다 | [RT6 스트리밍](../stages/realtime/rt6-stream/README.md) | — |
| FD7 | [전환 타이밍 조정](../stages/duplex/fd7-turn/README.md) | 🔬 연구 | 차례가 넘어가는 간격을 재고 사람 대화에 맞춘다 | [RT6 스트리밍](../stages/realtime/rt6-stream/README.md) · [E4 비용 · 지연](../stages/evalops/e4-cost/README.md) | — |

## 설계 원칙

- 내용 이해와 대화 타이밍은 다른 문제 — 따로 재고 따로 고친다
- 차례는 상태다 — 지금 누가 말할 차례인지 명시적으로
- 끼어들기에도 정책 — 안전 경고는 끊고 들어가고, 맞장구는 짧게

## 예시

고객이 화면을 가리키며 '여기 이게요…' 하고 멈칫 → 시선 · 손 방향으로 표시창 영역 · 말끝 억양으로 '아직 말하는 중' 판단 → 0.3초 '네' 맞장구만 → 고객이 말을 맺자 0.4초 만에 'E4 표시네요' 로 이어 감.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
