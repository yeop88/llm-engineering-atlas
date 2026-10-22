<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 장기 메모리 · 메모리 DB 맵

대화에서 기억 뽑기 → 메모리 DB 저장 · 연결 → 관련 · 최근 · 중요도로 찾기 → 갱신 · 충돌 해결 → 통합 · 망각 → 메모리 계층 → 여러 세션 평가 — 긴 맥락을 DB 로 유지하는 흐름

맥락 창이 커져도 몇 달치 상담 기록을 매번 다 넣을 수는 없습니다. 기억할 것만 뽑아 DB 에 두고, 지금 질문에 필요한 기억만 꺼내 맥락에 넣는 것이 장기 메모리입니다. 기억은 바뀌고(이사 · 제품 교체) 서로 부딪히며(예전 주소 vs 새 주소) 쌓일수록 낡습니다 — 갱신 · 충돌 · 망각 규칙과, 전체 기록을 넣는 것보다 정말 나은지를 재는 평가가 함께 있어야 합니다.

앱의 **맵 → 장기 메모리 · 메모리 DB 맵**(`/maps/memory`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[기억 추출] → [메모리 DB 저장 · 연결] → [기억 검색]
                    ↓
[갱신 · 충돌 해결] → [통합 · 망각]
                    ↓
[메모리 계층] → [여러 세션 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| ME1 | [기억 추출](../stages/memory/me1-extract/README.md) | ✅ 구현됨 | 대화에서 기억할 사실 · 선호 · 사건을 한 문장 단위로 뽑는다 | [C3 대화 메모리](../stages/conversation/c3-memory/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME2 | [메모리 DB 저장 · 연결](../stages/memory/me2-store/README.md) | ✅ 구현됨 | 기억을 DB 에 벡터 · 낱말 · 연결과 함께 저장한다 | [CX5 외부 메모리](../stages/context/cx5-memory/README.md) · [K4 융합 · 정제](../stages/knowledge-graph/k4-fusion/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME3 | [기억 검색](../stages/memory/me3-retrieve/README.md) | ✅ 구현됨 | 질문과 비슷함 · 최근 · 중요도 · 연결을 합쳐 기억을 고른다 | [2 RAG](../stages/llm/2-rag/README.md) · [K7 하이브리드 검색](../stages/knowledge-graph/k7-graph-hybrid/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME4 | [갱신 · 충돌 해결](../stages/memory/me4-update/README.md) | ✅ 구현됨 | 새 기억이 기존 기억과 같은지 · 바꾸는지 · 부딪히는지 판단해 고친다 | [K4 융합 · 정제](../stages/knowledge-graph/k4-fusion/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME5 | [통합 · 망각](../stages/memory/me5-consolidate/README.md) | ✅ 구현됨 | 비슷한 기억을 합치고 낡고 안 쓰는 기억은 요약하거나 지운다 | [C5 대화 압축](../stages/conversation/c5-compress/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME6 | [메모리 계층](../stages/memory/me6-tier/README.md) | ✅ 구현됨 | 항상 넣는 핵심 기억 · 꺼내 쓰는 기억 · 보관 기억으로 나눠 맥락 예산을 지킨다 | [CX1 맥락 배치](../stages/context/cx1-budget/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |
| ME7 | [여러 세션 평가](../stages/memory/me7-eval/README.md) | ✅ 구현됨 | 여러 세션에 걸친 대화로 기억 · 갱신 · 시간 질문을 묻고 전체 기록 넣기와 비교한다 | [E1 평가 세트](../stages/evalops/e1-sets/README.md) | [장기 메모리 — 기억 추출 · 시점 기록 · 연결 · 점수 검색 · 계층 · 통합 · 망각 · 여러 세션 평가 · 실측](../stages/memory/me1-extract/memory.md) |

## 설계 원칙

- 기억은 원문이 아니라 사실 단위로 — 한 문장 한 사실, 언제 · 누구에게서
- 찾기는 비슷함만이 아니다 — 최근 · 중요도 · 연결을 함께
- 덮어쓰지 말고 시점을 남긴다 — 예전 사실은 '언제까지 맞았나'로
- 전체 기록을 넣는 것보다 나은지 같은 질문으로 잰다

## 예시

석 달 전 '서울 강남구로 이사했어요', 오늘 '부산으로 다시 옮겼어요' → 주소 기억을 갱신하고 강남구는 '9월까지'로 남김 → '기사님 방문 가능한가요?' 에 부산 주소 · WM-200 보유 · 지난 E4 수리 이력만 꺼내 답 → 오래 안 쓴 잡담 기억은 요약 뒤 지움.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [토크나이저 · 표현 공간 맵](tokenizer.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
