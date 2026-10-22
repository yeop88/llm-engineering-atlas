<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 데이터 계보 · 근거 맵

원본 소스 → 수집 시각 → 변환 파이프라인 → 청크 → 주장 → 답 문장 → 인용 → 검증 결과 — 모든 답 문장을 원본까지 거슬러 올라가게

답이 틀렸을 때 '어느 문서의 어느 판, 어떤 변환을 거친 어느 청크에서 나왔나'를 바로 짚을 수 있어야 고칠 수 있습니다. 이 앱은 요청 기록에 근거 청크를, 문서에 해시 · 판을 남기지만 답 문장 → 주장 → 근거 → 원본으로 잇는 사슬은 없었습니다. 답을 주장 단위로 나눠 근거와 잇고, 서로 부딪히는 주장을 찾습니다.

앱의 **맵 → 데이터 계보 · 근거 맵**(`/maps/provenance`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[원본] → [수집 시각] → [변환]
                    ↓
[청크] → [주장] → [답 문장]
                    ↓
[인용] → [검증]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| PV1 | [원본 소스](../stages/provenance/pv1-source/README.md) | ⬜ 예정 | 문서의 원본(파일 · URL · API)과 그 해시 · 권리를 남긴다 | [D1 수집](../stages/docintel/d1-ingest/README.md) | — |
| PV2 | [수집 시각 · 판](../stages/provenance/pv2-ingest/README.md) | ⬜ 예정 | 언제 받은 어느 판인지, 판이 바뀌면 무엇이 바뀌었나 | [D6 증분 갱신](../stages/docintel/d6-meta/README.md) · [RC3 데이터 근거](../stages/compliance/rc3-data/README.md) | — |
| PV3 | [변환 파이프라인](../stages/provenance/pv3-transform/README.md) | ⬜ 예정 | 파싱 · OCR · 표 복원 · 정제의 각 단계를 기록한다 | [D2 파싱](../stages/docintel/d2-parse/README.md) · [D3 레이아웃 · 표](../stages/docintel/d3-layout/README.md) | — |
| PV4 | [청크](../stages/provenance/pv4-chunk/README.md) | ⬜ 예정 | 청크가 원본의 어디(쪽 · 조문 · 글자 범위)에서 왔는지 남긴다 | [D5 청킹](../stages/docintel/d5-chunk/README.md) | — |
| PV5 | [주장](../stages/provenance/pv5-claim/README.md) | ⬜ 예정 | 답을 확인 가능한 주장 단위로 나눈다 | [AS6 검증](../stages/as-service/as6-verify/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | — |
| PV6 | [답 문장](../stages/provenance/pv6-sentence/README.md) | ⬜ 예정 | 답 문장 → 주장 → 근거를 요청 기록에 남긴다 | [E3 트레이싱](../stages/evalops/e3-tracing/README.md) | — |
| PV7 | [인용](../stages/provenance/pv7-cite/README.md) | ⬜ 예정 | 인용 번호가 실제 근거를 가리키고, 근거가 주장을 뒷받침하는지 본다 | [2 RAG](../stages/llm/2-rag/README.md) · [RC4 설명 가능성](../stages/compliance/rc4-explain/README.md) | — |
| PV8 | [검증 결과 · 부딪힘](../stages/provenance/pv8-verify/README.md) | ⬜ 예정 | 주장끼리 · 판끼리 부딪히는 것을 찾고 검증 결과를 남긴다 | [K4 융합 · 정제](../stages/knowledge-graph/k4-fusion/README.md) · [E6 드리프트](../stages/evalops/e6-drift/README.md) | — |

## 설계 원칙

- 답 문장 하나가 원본까지 — 문장 → 주장 → 근거 → 청크 → 판 → 원본
- 판과 시각을 남긴다 — 같은 문서도 언제 받은 판인지
- 부딪힘도 관계다 — CONTRADICTS 를 찾아 보여 준다

## 예시

'임금은 매월 1회 이상 지급' 문장 → 주장 1개 → 근로기준법 제43조 청크(2026-07 판, 법령 API 수집, 조문 단위 청킹) → 인용 [2] 일치 · 근거 문장 겹침 0.82 → 같은 질문의 예전 답이 '격월' 이라 CONTRADICTS 로 표시.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
