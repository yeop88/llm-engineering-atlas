<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 에이전트 경제 · 거래 맵

서비스 발견 → 가격 · 조건 비교 → 예산 정책 → 거래 승인 → 결제 · 에스크로 → 결과 검증 → 정산 → 분쟁 처리 — 에이전트가 돈을 쓰기 전에 지켜야 할 것

에이전트가 다른 에이전트 · 서비스의 기능을 사서 쓰는 흐름(유료 API · 번역 · 배송 접수)이 생기고 있습니다. 돈이 오가는 행동은 되돌리기 어렵습니다. 실제 결제는 하지 않고 흉내 장부로, 예산 · 위임(mandate) · 승인 · 영수증 · 환불 · 책임을 한 흐름으로 설계하고 '승인 없는 거래 0 · 예산 초과 0'을 시험합니다.

앱의 **맵 → 에이전트 경제 · 거래 맵**(`/maps/economy`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[서비스 발견] → [가격 비교] → [예산 정책]
                    ↓
[거래 승인] → [결제 · 에스크로]
                    ↓
[결과 검증] → [정산] → [분쟁]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| EC1 | [서비스 발견](../stages/economy/ec1-discover/README.md) | 🔬 연구 | 에이전트 카드 · 도구 목록에서 살 수 있는 서비스를 찾는다 | [IO3 A2A 위임](../stages/interop/io3-a2a/README.md) | — |
| EC2 | [가격 · 조건 비교](../stages/economy/ec2-compare/README.md) | 🔬 연구 | 같은 기능의 가격 · 품질 · 납기 · 환불 조건을 비교한다 | [S7 예산](../stages/serving/s7-budget/README.md) | — |
| EC3 | [예산 정책 · 위임](../stages/economy/ec3-budget/README.md) | 🔬 연구 | 누가 · 무엇에 · 얼마까지 쓰게 할지 위임 범위를 정하고 검사한다 | [PF7 비용 배분](../stages/platform/pf7-chargeback/README.md) · [LR7 상한](../stages/longrun/lr7-limits/README.md) | — |
| EC4 | [거래 승인](../stages/economy/ec4-approve/README.md) | 🔬 연구 | 금액 · 위험에 따라 사람 승인을 요구한다 | [LR4 승인 지점](../stages/longrun/lr4-approval/README.md) · [CU4 위험 승인](../stages/computer-use/cu4-approve/README.md) | — |
| EC5 | [결제 · 에스크로](../stages/economy/ec5-escrow/README.md) | 🔬 연구 | 흉내 장부에서 돈을 묶어 두고 결과 확인 뒤 푼다 | [IO4 장기 작업](../stages/interop/io4-longtask/README.md) | — |
| EC6 | [결과 검증](../stages/economy/ec6-verify/README.md) | 🔬 연구 | 산 결과가 조건에 맞는지 검사한다 | [LR6 완료 판정](../stages/longrun/lr6-verify/README.md) · [MA7 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) | — |
| EC7 | [정산 · 영수증](../stages/economy/ec7-settle/README.md) | 🔬 연구 | 통과하면 정산하고 영수증 · 감사 기록을 남긴다 | [G5 감사 로그](../stages/guardrails/g5-audit/README.md) | — |
| EC8 | [분쟁 처리](../stages/economy/ec8-dispute/README.md) | 🔬 연구 | 불합격 · 미이행이면 환불 · 분쟁 · 책임을 정한다 | [C6 상담원 이관](../stages/conversation/c6-handoff/README.md) | — |

## 설계 원칙

- 돈은 승인 없이 움직이지 않는다 — 위임 범위 · 금액 · 상대마다
- 결과를 확인한 뒤 낸다 — 에스크로로 묶고 검증 뒤 정산
- 실제 결제는 하지 않는다 — 흉내 장부로 규칙을 시험

## 예시

'계약서 영문 번역' 작업 → 번역 서비스 3곳 카드 비교(가격 · 품질 · 납기) → 월 예산 5만 원 · 건당 1만 원 위임 안 → 8천 원 서비스 선택 · 사람 승인 → 흉내 에스크로 → 번역 품질 검사 통과 → 정산 · 영수증 → 불합격이면 환불 분쟁.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
