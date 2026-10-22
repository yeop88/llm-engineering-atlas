<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 실시간 스트리밍 LLM 맵

스트림 입력 → 조각 나누기 → 부분 인식 → 상태 갱신 → 점진 추론 → 토큰 · 소리 스트리밍 → 중단 처리 → 세션 복구 — TTFT · 첫 소리 · p95 · p99 · 복구율

실시간은 평균이 아니라 꼬리(p95 · p99)와 끊김에서 무너집니다. 음성 상담 · 옴니채널 맵에 끝점 · 끼어들기 · 인식 확정이 있지만, 스트림 전체(조각 · 지터 · 패킷 손실 · 세션 복구)를 한 흐름으로 재지는 않았습니다. 같은 스트림을 지연 · 손실을 섞어 다시 틀며 단계별 지연 분포와 복구율을 잽니다.

앱의 **맵 → 실시간 스트리밍 LLM 맵**(`/maps/realtime`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[스트림 입력] → [조각] → [부분 인식]
                    ↓
[상태 갱신] → [점진 추론]
                    ↓
[토큰 · 소리 스트리밍] → [중단] → [세션 복구]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| RT1 | [스트림 입력](../stages/realtime/rt1-input/README.md) | ✅ 구현됨 | 소리 · 영상 · 글 스트림을 시각 표시와 함께 받는다 | [VC1 음성 인식](../stages/voice/vc1-stt/README.md) · [OM2 실시간 음성](../stages/omni/om2-voice/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT2 | [조각 나누기](../stages/realtime/rt2-chunk/README.md) | ✅ 구현됨 | 조각 길이가 지연 · 인식 품질에 주는 영향을 잰다 | [VC2 턴 관리](../stages/voice/vc2-turn/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT3 | [부분 인식](../stages/realtime/rt3-partial/README.md) | ✅ 구현됨 | 잠정 결과를 확정 규칙으로 굳혀 나간다 | [OM2 실시간 음성](../stages/omni/om2-voice/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT4 | [상태 갱신](../stages/realtime/rt4-state/README.md) | ✅ 구현됨 | 확정된 조각마다 대화 · 화면 상태를 갱신한다 | [C3 대화 메모리](../stages/conversation/c3-memory/README.md) · [OM4 턴 융합](../stages/omni/om4-fuse/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT5 | [점진 추론](../stages/realtime/rt5-incremental/README.md) | ✅ 구현됨 | 문장 끝이 확정되면 검색 · 미리 채우기를 먼저 시작한다 | [VC3 짧은 지연 RAG](../stages/voice/vc3-fastrag/README.md) · [CX4 프롬프트 캐시](../stages/context/cx4-cache/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT6 | [토큰 · 소리 스트리밍](../stages/realtime/rt6-stream/README.md) | ✅ 구현됨 | 첫 토큰 · 첫 문장 · 첫 소리까지를 나눠 잰다 | [VC4 음성 합성](../stages/voice/vc4-tts/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT7 | [중단 처리](../stages/realtime/rt7-interrupt/README.md) | ✅ 구현됨 | 끼어들면 생성 · 합성 · 전송을 함께 멈추고 들은 데까지 남긴다 | [VC2 턴 관리](../stages/voice/vc2-turn/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |
| RT8 | [세션 복구](../stages/realtime/rt8-recover/README.md) | ✅ 구현됨 | 끊겼다 다시 붙으면 마지막 확정 지점부터 이어 간다 | [LR3 체크포인트](../stages/longrun/lr3-state/README.md) · [OM5 채널 이어 가기](../stages/omni/om5-handoff/README.md) | [실시간 스트리밍 — 지터 · 손실 · 끊김을 섞은 스트림 재생, 단계별 꼬리 지연 · 확정 오류 · 끼어들기 · 세션 복구](../stages/realtime/rt1-input/realtime.md) |

## 설계 원칙

- 평균 말고 꼬리 — p95 · p99 와 첫 소리까지
- 단계마다 따로 잰다 — 전송 · 인식 · LLM · 합성
- 끊겨도 이어진다 — 세션 상태는 서버에, 다시 붙으면 그 자리부터

## 예시

마이크 스트림 250ms 조각 → 지터 80ms · 손실 2% 섞어 재생 → 부분 인식 확정(N=2) → 문장 끝 확정 시 검색 미리 시작 → 첫 토큰 640ms · 첫 소리 1.1초(p95 1.8초) → 연결이 끊겼다 3초 뒤 다시 붙으면 마지막 확정 턴부터 이어 감.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
