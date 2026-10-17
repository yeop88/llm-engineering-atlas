<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서

LLM Engineering Atlas 의 문서는 [전체 맵](map.md)의 단계 순서로 정리되어 있습니다. 각 단계 폴더의 `README.md` 에 그 단계의 **원리 · 왜 하는가 · 어떻게(이 앱에서)** 가 있고, 같은 폴더에 상세 문서가 있습니다.

```
[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]
                                        ↓
[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]
                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| 1 | [데이터 임베딩](stages/1-embedding/README.md) | ✅ 구현됨 | 텍스트·이미지를 의미 벡터로 바꾸는 모델을 고르고 비교한다 | [모델 카탈로그](stages/1-embedding/models.md) · [벤치마크](stages/1-embedding/benchmarks.md) · [시각화](stages/1-embedding/visualization.md) |
| 2 | [RAG 검색](stages/2-rag/README.md) | ✅ 구현됨 | 내 문서에서 근거를 찾아 LLM 이 그 근거로 답하게 한다 | [문서 검색(RAG)](stages/2-rag/rag.md) · [LLM 연결](guides/llm.md) |
| 3 | [리랭킹](stages/3-rerank/README.md) | 🟡 기초 있음 | 1단계 검색이 고른 후보를 정밀하게 다시 줄 세운다 | [RAG 조합 평가 실측](stages/2-rag/rag.md) |
| 4 | [검색 향상](stages/4-search-lab/README.md) | ✅ 구현됨 | 모델을 바꾸지 않고 질의를 LLM 으로 다듬어 검색을 좋게 한다 | [검색 향상: 기법 · 측정 기록](stages/4-search-lab/search-lab.md) |
| 5 | [파인튜닝](stages/5-finetune/README.md) | ✅ 구현됨 | 임베딩 모델을 내 문서 분야에 맞게 추가 학습한다 | [파인튜닝: 왜 · 어떻게 · 실행 기록](stages/5-finetune/finetune.md) |
| 6 | [라우팅](stages/6-routing/README.md) | ⬜ 예정 | 질문의 난이도 · 종류를 먼저 분류해 처리할 모델을 고른다 | — |
| 7a | [지식 증류](stages/7a-distill/README.md) | ⬜ 예정 | 큰 모델의 판단을 작은 모델이 따라 하도록 학습한다 | — |
| 7b | [양자화](stages/7b-quant/README.md) | ⬜ 예정 | 가중치 · 벡터를 낮은 비트로 바꿔 메모리와 지연을 줄인다 | — |
| 8a | [에이전틱 AI](stages/8a-agent/README.md) | ⬜ 예정 | LLM 이 계획을 세우고 도구를 여러 번 써서 어려운 질문을 푼다 | — |
| 8b | [강화학습](stages/8b-rl/README.md) | ⬜ 예정 | 보상 · 선호 신호로 모델의 행동을 최적화한다 | — |
| M | [멀티모달](stages/multimodal/README.md) | ✅ 구현됨 | 이미지 · 영상 장면을 텍스트와 같은 벡터 공간에서 찾는다 | [멀티모달: 모델 · 이미지 · 영상 컬렉션 · 실측](stages/multimodal/multimodal.md) |
| A | [의미 응용](stages/apps/README.md) | ✅ 구현됨 | 임베딩으로 추천 · 분류 · 군집 · 중복 · 이상 탐지 · 키워드를 만든다 | [의미 응용](stages/apps/apps.md) |

## 가이드

- [아키텍처 — 코드 구조(core · stages · web)와 동작 방식](guides/architecture.md)
- [REST API](guides/api.md)
- [LLM 연결 — 로컬 llama.cpp · OpenAI 호환 · Claude, 소형 모델 비교](guides/llm.md)
- [CPU · CUDA · ROCm 설치](guides/gpu.md)
- [문제 해결](guides/troubleshooting.md)

## 기록

- [대체 모델 정보 검증과 실측 벤치마크](records/model-verification.md)
- [파인튜닝 실행 기록 (#1~#3)](stages/5-finetune/finetune.md#실행-기록)
- [벡터 검색 재현율 문제와 정정 기록](stages/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색)
