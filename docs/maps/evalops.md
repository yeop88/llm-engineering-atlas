<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 평가 · 관측 (LLMOps) 맵

평가 세트 → 오프라인 평가 · 회귀 → 트레이싱 → 피드백 → 드리프트 감지 · A/B → 개선 반영 — 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름

모든 맵의 개선은 '좋아졌다'를 숫자로 확인할 때만 의미가 있습니다. 이 맵은 평가 세트를 관리하고, 바꿀 때마다 회귀를 확인하고, 서비스 중의 질문 · 단계 · 시간 · 비용을 기록하고, 사람 피드백과 분포 변화를 모아 다시 평가 세트와 학습 데이터로 돌려보내는 흐름입니다. 실측에서 결론이 바뀐 이유가 대부분 측정 방법(프롬프트 캐시 · 비교 지표 · 판정 기준)이었습니다.

앱의 **맵 → 평가 · 관측 (LLMOps) 맵**(`/maps/evalops`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[평가 세트 · 정답] → [오프라인 평가 · 회귀] → [트레이싱]
                                      ↓
[비용 · 지연 대시보드] · [사용자 피드백 · 사람 판정] · [드리프트 감지] · [A/B 실험]
                                      ↓
                         [개선 반영 루프 (평가 세트 · 학습 데이터로)]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| E1 | [평가 세트 · 정답 관리](../stages/evalops/e1-sets/README.md) | ✅ 구현됨 | 질문 · 정답 근거 · 질문 유형을 세트로 관리하고, 생성 · 보정 · 보충 기록을 남긴다 | [2 RAG](../stages/llm/2-rag/README.md) | [평가 세트 관리 · 회귀 평가](../stages/evalops/e1-sets/regression.md) |
| E2 | [오프라인 평가 · 회귀](../stages/evalops/e2-offline/README.md) | ✅ 구현됨 | 설정 · 모델 · 라이브러리를 바꿀 때마다 고정 세트로 다시 재서 기준선보다 나빠졌는지 확인한다 | [2 RAG](../stages/llm/2-rag/README.md) · [6 라우팅](../stages/llm/6-routing/README.md) | [평가 세트 관리 · 회귀 평가](../stages/evalops/e1-sets/regression.md) |
| E3 | [트레이싱](../stages/evalops/e3-tracing/README.md) | ✅ 구현됨 | 질문마다 단계 · 시간 · 토큰 · 결정(라우팅 · 도구)을 기록해 한 요청을 끝까지 따라가 본다 | [2 RAG](../stages/llm/2-rag/README.md) · [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [요청 기록 · 비용 · 지연](../stages/evalops/e3-tracing/tracing.md) |
| E4 | [비용 · 지연 대시보드](../stages/evalops/e4-cost/README.md) | ✅ 구현됨 | 질문당 토큰 · 시간 · 비용을 모아 단계별 · 경로별로 보여 준다 | [7b 양자화](../stages/llm/7b-quant/README.md) · [6 라우팅](../stages/llm/6-routing/README.md) | [요청 기록 · 비용 · 지연](../stages/evalops/e3-tracing/tracing.md) |
| E5 | [사용자 피드백 · 사람 판정](../stages/evalops/e5-feedback/README.md) | ✅ 구현됨 | 답변마다 좋아요 · 싫어요 · 이유를 받고, 사람 판정으로 자동 판정을 보정한다 | [2 RAG](../stages/llm/2-rag/README.md) · [8b 강화학습](../stages/llm/8b-rl/README.md) | [사용자 피드백 · 개선 루프](../stages/evalops/e5-feedback/feedback.md) |
| E6 | [드리프트 · 이상 감지](../stages/evalops/e6-drift/README.md) | ✅ 구현됨 | 들어오는 질문의 분포 · 검색 확신도 · 거절률이 평소와 달라지면 알린다 | [A 의미 응용](../stages/llm/a-apps/README.md) | [드리프트 감지](../stages/evalops/e6-drift/drift.md) |
| E7 | [A/B · 온라인 실험](../stages/evalops/e7-ab/README.md) | ✅ 구현됨 | 실제 요청을 두 설정에 나눠 보내 품질 · 만족도 · 비용을 비교한다 | [6 라우팅](../stages/llm/6-routing/README.md) | [A/B 실험](../stages/evalops/e7-ab/ab.md) |
| E8 | [개선 반영 루프](../stages/evalops/e8-loop/README.md) | ✅ 구현됨 | 실패 사례를 모아 평가 세트 · 학습 데이터 · 규칙으로 되돌려 다음 버전을 만든다 | [5 파인튜닝](../stages/llm/5-finetune/README.md) · [8b 강화학습](../stages/llm/8b-rl/README.md) | [사용자 피드백 · 개선 루프](../stages/evalops/e5-feedback/feedback.md) |

## 설계 원칙

- 비교 측정은 같은 질문 · 같은 근거 · 같은 캐시 조건으로 — llama-server 프롬프트 캐시로 한 모델만 빨라 보인 사례(Q4 6초)
- 비교 지표를 단계에 맞게 — RAG vs 에이전트는 첫 검색이 같아 nDCG 차이가 늘 0, 답변 품질로 비교해야 차이가 보였다
- 자동 판정은 사람 판정으로 보정 — 판정 기준(근거 일치 vs 질문 관련성)을 먼저 확인한다
- 질문별 기록을 남긴다 — 평균만 있으면 '왜 나빠졌는지'(에이전트 20분 질문)를 찾을 수 없었다
- 질문이 적으면 '불확실'로 적는다 — 24 · 40문항 측정 대부분이 신뢰구간이 겹쳤다

## 예시

sentence-transformers 를 올린 날: 호환성 점검 → 고정 회귀 세트(법률 #5 · #7) 재실행 → 기준선 대비 nDCG · 근거 인용 차이가 유의하게 떨어지면 경보 → 질문별 기록에서 떨어진 유형(예: 여러 문서) 확인.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
