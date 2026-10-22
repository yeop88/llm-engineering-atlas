<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 해석 가능성 · 모델 내부 맵

임베딩 공간 분석 → 근거 기여 → 탐침 → 희소 특징 → 조종 · 편집 → 내부 신호 환각 탐지 — 모델이 왜 그렇게 답했는지 안을 보는 흐름

근거 일치 검증은 답을 '밖'에서 보는 방법입니다. 작은 공개 모델(Qwen3 0.6B · 임베딩 모델)은 내부를 직접 볼 수 있어, 어느 근거 문장이 답에 기여했는지, 모델이 '모른다'를 안에서 알고 있는지, 특정 방향으로 출력을 조종할 수 있는지를 잴 수 있습니다. 규제 대응의 설명 가능성(RC4)을 모델 안쪽에서 보완합니다.

앱의 **맵 → 해석 가능성 · 모델 내부 맵**(`/maps/interp`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[임베딩 공간 분석] → [근거 기여]
                    ↓
[탐침] → [희소 특징]
                    ↓
[조종 · 편집] → [내부 신호 환각 탐지]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| IP1 | [임베딩 공간 분석](../stages/interp/ip1-space/README.md) | ✅ 구현됨 | 차원 축소 · 군집 · 이방성 · 언어 간 정렬로 임베딩 공간을 본다 | [1 임베딩](../stages/llm/1-embedding/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |
| IP2 | [근거 기여](../stages/interp/ip2-attribution/README.md) | ✅ 구현됨 | 어텐션 · 그래디언트 · 근거 지우기로 어느 문장이 답에 기여했는지 잰다 | [RC4 설명 가능성](../stages/compliance/rc4-explain/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |
| IP3 | [탐침](../stages/interp/ip3-probe/README.md) | ✅ 구현됨 | 은닉 상태로 '근거에 답이 있나' · 주제 · 언어를 선형 분류한다 | [A 의미 응용](../stages/llm/a-apps/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |
| IP4 | [희소 특징](../stages/interp/ip4-sae/README.md) | ✅ 구현됨 | 은닉 상태를 사람이 읽을 수 있는 희소 특징으로 나눈다 | [P5 어댑터 · 병합](../stages/posttrain/p5-adapter/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |
| IP5 | [조종 · 편집](../stages/interp/ip5-steer/README.md) | ✅ 구현됨 | 특징 방향을 더해 말투 · 거절을 조종하고 부작용을 잰다 | [P5 어댑터 · 병합](../stages/posttrain/p5-adapter/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |
| IP6 | [내부 신호 환각 탐지](../stages/interp/ip6-hallu/README.md) | ✅ 구현됨 | 토큰 확률 · 엔트로피 · 탐침으로 근거 없는 답을 잡고 근거 일치 검증과 비교한다 | [AS6 검증](../stages/as-service/as6-verify/README.md) | [해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측](../stages/interp/ip1-space/interp.md) |

## 설계 원칙

- 밖의 검증과 비교한다 — 근거 일치 검증 실측이 기준
- 작은 공개 모델로 — 안을 볼 수 있는 모델에서 재고 큰 모델은 밖에서
- 설명은 재현돼야 한다 — 근거를 지웠을 때 답이 바뀌는지로 확인
- 조종은 부작용을 잰다 — 같은 평가 세트 · 레드팀

## 예시

법률 답 '제23조에 따라…' → 근거 문장을 하나씩 지워 기여 확인(지우면 답이 바뀌는 문장만 진짜 근거) → 은닉 상태 탐침으로 '근거에 답 없음'을 미리 감지 → 거절 방향 조종의 부작용을 레드팀으로 → 토큰 엔트로피 환각 탐지와 근거 일치 검증의 정확도 비교.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
