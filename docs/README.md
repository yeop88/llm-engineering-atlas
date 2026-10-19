<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서

LLM Engineering Atlas 의 문서는 맵의 단계 순서로 정리되어 있습니다. 맵은 [LLM 시스템 엔지니어링 맵](map.md) · [지식 그래프 · GraphRAG 맵](kg-map.md) · [멀티에이전트 · 멀티모달 맵](agents-map.md) 입니다. 각 단계 폴더의 `README.md` 에 그 단계의 **원리 · 왜 하는가 · 어떻게(이 앱에서)** 가 있고, 같은 폴더에 상세 문서가 있습니다.

## LLM 시스템 엔지니어링 맵

임베딩 → RAG 검색 → 리랭킹 → 라우팅 → 소형/대형 모델 · 에이전트 — 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름

```
[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]
                                        ↓
[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]
                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| 1 | [데이터 임베딩](stages/1-embedding/README.md) | ✅ 구현됨 | 텍스트·이미지를 의미 벡터로 바꾸는 모델을 고르고 비교한다 | [모델 카탈로그](stages/1-embedding/models.md) · [벤치마크](stages/1-embedding/benchmarks.md) · [시각화](stages/1-embedding/visualization.md) |
| 2 | [RAG 검색](stages/2-rag/README.md) | ✅ 구현됨 | 내 문서에서 근거를 찾아 LLM 이 그 근거로 답하게 한다 | [문서 검색(RAG)](stages/2-rag/rag.md) · [LLM 연결](guides/llm.md) |
| 3 | [리랭킹](stages/3-rerank/README.md) | ✅ 구현됨 | 1단계 검색이 고른 후보를 정밀하게 다시 줄 세운다 | [리랭킹: 방법 · 실측](stages/3-rerank/rerank.md) |
| 4 | [검색 향상](stages/4-search-lab/README.md) | ✅ 구현됨 | 모델을 바꾸지 않고 질의를 LLM 으로 다듬어 검색을 좋게 한다 | [검색 향상: 기법 · 측정 기록](stages/4-search-lab/search-lab.md) |
| 5 | [파인튜닝](stages/5-finetune/README.md) | ✅ 구현됨 | 임베딩 모델을 내 문서 분야에 맞게 추가 학습한다 | [파인튜닝: 왜 · 어떻게 · 실행 기록](stages/5-finetune/finetune.md) |
| 6 | [라우팅](stages/6-routing/README.md) | ✅ 구현됨 | 질문의 난이도를 먼저 판단해 쉬운 질문은 싼 경로, 어려운 질문은 비싼 경로로 보낸다 | [라우팅: 라우터 · 평가 방법 · 실측](stages/6-routing/routing.md) |
| 7a | [지식 증류](stages/7a-distill/README.md) | ✅ 구현됨 | 큰 모델의 판단을 작은 모델이 따라 하도록 학습한다 | [지식 증류: 방법 · 실측](stages/7a-distill/distill.md) |
| 7b | [양자화](stages/7b-quant/README.md) | ✅ 구현됨 | 가중치 · 벡터를 낮은 비트로 바꿔 메모리와 지연을 줄이고, 정확도 손실을 잰다 | [양자화: 방법 · 실측](stages/7b-quant/quant.md) |
| 8a | [에이전틱 AI](stages/8a-agent/README.md) | ✅ 구현됨 | LLM 이 도구를 여러 번 써서 어려운 질문을 푼다 | [에이전트: 방법 · 실측](stages/8a-agent/agent.md) |
| 8b | [강화학습](stages/8b-rl/README.md) | ✅ 구현됨 | 보상 · 선호 신호로 답변 행동을 좋게 만든다 | [강화학습: 보상 · 방법 · 실측](stages/8b-rl/rl.md) |
| M | [멀티모달](stages/multimodal/README.md) | ✅ 구현됨 | 이미지 · 영상 장면을 텍스트와 같은 벡터 공간에서 찾는다 | [멀티모달: 모델 · 이미지 · 영상 컬렉션 · 실측](stages/multimodal/multimodal.md) |
| A | [의미 응용](stages/apps/README.md) | ✅ 구현됨 | 임베딩으로 추천 · 분류 · 군집 · 중복 · 이상 탐지 · 키워드를 만든다 | [의미 응용](stages/apps/apps.md) |

## 지식 그래프 · GraphRAG 맵

온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름

```
[요구사항 정의] → [온톨로지 설계] → [데이터 추출 (ETL · LLM)] → [지식 융합 · 정제]
                                        ↓
                              [그래프 DB (Neo4j)]
                                        ↓
  GraphRAG: [Text2Cypher] · [그래프 하이브리드 검색] · [글로벌 커뮤니티 요약]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| K1 | [요구사항 정의](stages/kg/k1-requirements/README.md) | ⬜ 예정 | 지식 그래프가 답해야 할 업무 질문 10~15개로 그래프의 범위를 정한다 | — |
| K2 | [온톨로지 설계](stages/kg/k2-ontology/README.md) | ⬜ 예정 | 도메인의 개념(클래스) · 속성 · 관계와 그 규칙을 기계가 읽는 스키마로 정의한다 | — |
| K3 | [데이터 추출](stages/kg/k3-extract/README.md) | ⬜ 예정 | 정형 데이터는 스키마 매핑으로, 비정형 문서는 LLM 으로 [주어-관계-목적어] 트리플을 뽑는다 | — |
| K4 | [지식 융합 · 정제](stages/kg/k4-fusion/README.md) | ⬜ 예정 | 다른 이름의 같은 개체를 하나로 묶고(개체 정규화) 중복 · 충돌을 정리해 그래프를 완성한다 | — |
| K5 | [그래프 DB](stages/kg/k5-graph-db/README.md) | ⬜ 예정 | 노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다 | — |
| K6 | [Text2Cypher](stages/kg/k6-text2cypher/README.md) | ⬜ 예정 | 질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다 | — |
| K7 | [그래프 하이브리드 검색](stages/kg/k7-graph-hybrid/README.md) | ⬜ 예정 | 벡터 검색으로 찾은 청크에서 연결된 개체 · 관계(서브그래프)를 함께 가져와 답변 맥락을 넓힌다 | [LLM 맵 · 2 RAG 검색](stages/2-rag/rag.md) |
| K8 | [글로벌 커뮤니티 요약](stages/kg/k8-community-summary/README.md) | ⬜ 예정 | 그래프를 계층적 커뮤니티로 나눠 미리 요약해 두고, 전체 주제 · 추세 질문은 요약들을 모아 답한다 | — |

## 멀티에이전트 · 멀티모달 맵

멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력

```
[멀티모달 입력 (텍스트 · 이미지 · 음성 · 문서)] → [멀티모달 임베딩]
                                        ↓
                     [오케스트레이터 에이전트 (작업 분해 · 분배)]
          ↓                             ↓                              ↓
  [검색 전문가 (멀티모달 RAG)]   [분석 · 코딩 (표 · 코드 · 차트)]   [보고서 작성 (sLLM / LLM)]
                                        ↓
                     [품질 검증 (Critic) · 교차 검증]
                                        ↓
                [멀티모달 출력 (텍스트 + 차트 + 음성)]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| MA1 | [멀티모달 입력 · 임베딩](stages/agents/ma1-mm-input/README.md) | 🟡 기초 있음 | 텍스트 · 이미지 · 음성 · 문서를 공통 벡터 공간에 놓아, 사진으로 매뉴얼을 찾는 식의 교차 검색을 한다 | [LLM 맵 · 멀티모달](stages/multimodal/multimodal.md) |
| MA2 | [멀티모달 RAG](stages/agents/ma2-mm-rag/README.md) | 🟡 기초 있음 | 표 · 그래프 · 설계도를 글로 바꾸지 않고 이미지 청크 그대로 저장 · 검색하고, 멀티모달로 다시 순위를 매긴다 | [LLM 연결 · 그림 근거 답변](guides/llm.md) |
| MA3 | [오케스트레이터 에이전트](stages/agents/ma3-orchestrator/README.md) | ⬜ 예정 | 복잡한 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화 | [LLM 맵 · 에이전트 실측](stages/8a-agent/agent.md) |
| MA4 | [검색 전문가 에이전트](stages/agents/ma4-retrieval-agent/README.md) | 🟡 기초 있음 | 사내 문서 · 이미지 · 웹 검색만 맡고, 결과가 부실하면 스스로 질의를 고쳐 다시 찾는다(Self-RAG) | — |
| MA5 | [분석 · 코딩 에이전트](stages/agents/ma5-analysis-agent/README.md) | ⬜ 예정 | 검색된 표 · 수치를 파이썬 코드로 계산 · 검증하고 결과 차트를 만든다 | — |
| MA6 | [보고서 작성 에이전트](stages/agents/ma6-report-agent/README.md) | ⬜ 예정 | 모은 근거 · 분석 결과로 정해진 형식의 답 · 보고서를 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델 | [LLM 맵 · 소형 모델 실측](stages/7b-quant/quant.md) |
| MA7 | [품질 검증 에이전트](stages/agents/ma7-critic-agent/README.md) | 🟡 기초 있음 | 최종 답이 원문과 맞는지(환각) · 질문에 답하는지 · 보안 규정을 어기지 않는지 검사해 반려하거나 통과시킨다 | [LLM 맵 · 답변 원칙과 검증](stages/2-rag/rag.md) |
| MA8 | [멀티모달 출력](stages/agents/ma8-mm-output/README.md) | ⬜ 예정 | 텍스트 답에 더해 차트 · 이미지 · 음성으로 결과를 낸다 | — |

## 가이드

- [아키텍처 — 코드 구조(core · stages · web)와 동작 방식](guides/architecture.md)
- [REST API](guides/api.md)
- [데이터 처리 — 수집 · 전처리 · 평가 자료 기록과 유효하게 처리하는 법](guides/data-processing.md)
- [배포 · 운영 — Docker, 접근 토큰, 작업 기록, 모델 호환성 점검, 새 모델 후보](guides/deploy.md)
- [LLM 연결 — 로컬 llama.cpp · OpenAI 호환 · Claude, 소형 모델 비교](guides/llm.md)
- [CPU · CUDA · ROCm 설치](guides/gpu.md)
- [문제 해결](guides/troubleshooting.md)

## 기록

- [대체 모델 정보 검증과 실측 벤치마크](records/model-verification.md)
- [파인튜닝 실행 기록 (#1~#3)](stages/5-finetune/finetune.md#실행-기록)
- [벡터 검색 재현율 문제와 정정 기록](stages/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색)
