<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 합성 데이터 맵

데이터 부족 분석 → 생성 전략 → 합성 데이터 생성 → 다양성 검사 → 중복 · 오염 제거 → 인간 검토 → 학습 → 실제 데이터 평가 — 합성으로 늘리되 실제로 잰다

평가 질문 생성 · 후학습 합성 데이터 · 과제 생성이 여러 맵에 있지만, '무엇이 부족해서 무엇을 만들었고 실제로 나아졌나' 를 한 흐름으로 보지 않았습니다. 합성 데이터는 쉽게 많이 만들 수 있어 오히려 위험합니다 — 비슷한 것만 늘고, 평가 질문이 섞이고, 실제 데이터에서는 나아지지 않을 수 있습니다. 부족 분석부터 실제 데이터 평가까지를 잇습니다.

앱의 **맵 → 합성 데이터 맵**(`/maps/synthetic`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[부족 분석] → [생성 전략] → [생성]
                    ↓
[다양성] → [중복 · 오염 제거] → [인간 검토]
                    ↓
[학습] → [실제 데이터 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| SD1 | [데이터 부족 분석](../stages/synthetic/sd1-gap/README.md) | ⬜ 예정 | 실패 유형 · 유형별 데이터 수에서 무엇이 부족한지 찾는다 | [FW2 실패 분류](../stages/flywheel/fw2-triage/README.md) · [E6 드리프트](../stages/evalops/e6-drift/README.md) | — |
| SD2 | [생성 전략 선택](../stages/synthetic/sd2-strategy/README.md) | ⬜ 예정 | 템플릿 · LLM 바꿔 쓰기 · 그래프 · 역번역 중 유형에 맞는 방법을 고른다 | [P1 합성 데이터](../stages/posttrain/p1-synth/README.md) · [RV1 과제 설계](../stages/rlvr/rv1-tasks/README.md) | — |
| SD3 | [합성 데이터 생성](../stages/synthetic/sd3-generate/README.md) | ⬜ 예정 | 고른 전략으로 만들고 만든 방법 · 원본을 남긴다 | [P1 합성 데이터](../stages/posttrain/p1-synth/README.md) | — |
| SD4 | [다양성 검사](../stages/synthetic/sd4-diversity/README.md) | ⬜ 예정 | 임베딩 군집 · 표현 반복으로 다양성을 재고 비슷한 것을 줄인다 | [A 의미 응용](../stages/llm/a-apps/README.md) | — |
| SD5 | [중복 · 오염 제거](../stages/synthetic/sd5-dedup/README.md) | ⬜ 예정 | 중복 · 평가 질문 누수 · 개인정보를 제거한다 | [P2 선별](../stages/posttrain/p2-select/README.md) · [FW4 자산화](../stages/flywheel/fw4-assets/README.md) | — |
| SD6 | [인간 검토](../stages/synthetic/sd6-review/README.md) | ⬜ 예정 | 표본을 사람이 검토해 오류율을 재고 묶음을 통과 · 반려한다 | [FW3 검토 우선순위](../stages/flywheel/fw3-review/README.md) | — |
| SD7 | [학습](../stages/synthetic/sd7-train/README.md) | ⬜ 예정 | 합성 · 실제 데이터 비율을 바꿔 학습한다 | [P3 SFT](../stages/posttrain/p3-sft/README.md) · [FW5 재학습](../stages/flywheel/fw5-retrain/README.md) | — |
| SD8 | [실제 데이터 평가](../stages/synthetic/sd8-eval/README.md) | ⬜ 예정 | 합성이 아닌 실제 질문으로 나아졌는지 잰다 | [P6 후학습 평가](../stages/posttrain/p6-eval/README.md) · [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | — |

## 설계 원칙

- 부족한 것만 만든다 — 실패 분석에서 시작
- 많이보다 다양하게 — 다양성 · 중복을 잰다
- 평가는 실제 데이터로 — 합성 평가 점수를 믿지 않는다

## 예시

실패 분류: '조문 번호 계산' 유형 정답률 31% · 학습 예시 12건 → 전략: 조문 그래프에서 템플릿 질문 + LLM 바꿔 쓰기 → 400건 생성 → 다양성 검사로 160건 → 평가 세트와 겹치는 7건 제거 → 검토 20건 표본 → SFT → 실제 질문 세트에서 31% → 58%.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md)
