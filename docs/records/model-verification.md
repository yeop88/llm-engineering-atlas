# 대체 임베딩 모델 정보 검증 (2026-10-17)

"EmbeddingGemma 2 대안"으로 정리된 메모의 내용을 Hugging Face 저장소 설정, 공식 발표, 그리고 이 앱의 실측 결과로 검증했습니다.

## 요약

| 주장 | 판정 | 근거 |
|---|---|---|
| EmbeddingGemma 2 Full 버전은 약 21GB VRAM 필요 | ❌ **틀림** | 전체 7.44억 파라미터, 저장소 1.5GB(BF16). Google은 양자화 시 Pixel 폰에서 텍스트 191MB / 전체 567MB RAM이라고 밝힘. 이 PC의 CPU(fp32)에서도 문제없이 실행됨 |
| BGE-M3는 3~4GB VRAM으로 가볍게 돈다 | ⚠️ 대체로 맞지만 비교가 틀림 | 568M 파라미터, 가중치 2.2GB(fp32). 오히려 EmbeddingGemma 2 텍스트 프로필(270M)보다 큼 |
| BGE-M3는 텍스트 중심, 완전한 멀티모달 아님 | ✅ 맞음 | dense/sparse/ColBERT 텍스트 전용 |
| BGE-M3는 한국어 포함 다국어의 강자 | ✅ 맞음 | 실측 검색 nDCG@10 0.977, STS Spearman 0.671(2위) |
| Qwen 2.5 / Qwen 3 계열이 한국어에 강함 | ⚠️ 부분적 | Qwen2.5 자체는 임베딩 모델이 아님. 해당 계열은 **Qwen3-Embedding**(0.6B/4B/8B). 실측 검색은 우수(0.975)하나 STS는 중하위(0.404), CPU에서 느림 |
| Qwen은 텍스트 전용 (암시) | ⚠️ 정보 누락 | 2026-01 공개된 **Qwen3-VL-Embedding**(2B/8B)은 텍스트·이미지·비디오 멀티모달 |
| Nomic Embed v2는 BGE-M3보다 훨씬 작고 성능 비슷 | ⚠️ 과장 | 전체 475M(활성 305M) vs 568M으로 "훨씬"은 아님. 최대 길이 **512 토큰**(BGE-M3 8,192)이라 긴 문서에 불리. 현재 transformers 5.x와 원격 코드가 맞지 않아 실행 불가 |
| CLIP / OpenCLIP은 이미지-텍스트 기본 뼈대 | ✅ 맞음 | 실측: 영어 쿼리는 정답, 한국어 쿼리는 1·2위 점수 차가 0.01로 구분이 약함 (77 토큰, 영어 위주) |
| ImageBind는 6개 모달리티 | ✅ 맞음 | 다만 2023년 공개, **CC-BY-NC-4.0(비상업)**, sentence-transformers 미지원이라 이 앱에는 넣지 않음 |
| Gemini Embedding 2가 EmbeddingGemma 2의 기반 | ⚠️ 표현 부정확 | Google 표현은 "Gemini Embedding 모델과 같은 기술로 만들었다". 기반 모델·증류 관계라고 밝히지 않음. 아키텍처는 Gemma 4 |
| OpenAI text-embedding-3는 Matryoshka 차원 축소 지원 | ✅ 맞음 | `dimensions` 파라미터 (클로즈드 API, 이 앱 범위 밖) |
| Cohere Embed v3가 기업용 최고 수준 | ⚠️ 오래된 정보 | 2025-04-15 **Embed v4** 공개 (멀티모달, 128K 컨텍스트, MRL) |

**빠진 정보:** 메모에는 2026년에 나온 오픈 모델이 거의 없습니다. Jina Embeddings v5(2026-01), Microsoft Harrier-OSS v1(2026-03), IBM Granite Embedding R2(2026-04), NVIDIA Nemotron-3-Embed(2026-07), Voyage 4 Nano, pplx-embed 등은 모두 카탈로그에 넣어 두었습니다.

## 실측 벤치마크

환경: Windows 11, CPU 16스레드(AMD, GPU 없음), fp32, sentence-transformers 6.1.0, transformers 5.20.1. 각 모델에 권장 query/document 프롬프트를 적용했습니다.

### 검색 — `ko_en_retrieval_mini` (쿼리 30 / 문서 33)

| 순위 | 모델 | 파라미터 | nDCG@10 | Recall@1 | MRR@10 | ko | en | ko→en | en→ko | texts/s |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | google/embeddinggemma-2 | 270M (텍스트) | **1.000** | **0.950** | **1.000** | 1.00 | 1.00 | 1.00 | 1.00 | 21 |
| 2 | jinaai/jina-embeddings-v5-text-nano | 212M | 0.988 | 0.917 | 0.983 | 1.00 | 1.00 | 1.00 | 0.91 | 26 |
| 3 | nlpai-lab/KURE-v1 | 568M | 0.978 | 0.917 | 0.975 | 0.99 | 1.00 | 1.00 | 0.86 | 14 |
| 4 | BAAI/bge-m3 | 568M | 0.977 | 0.917 | 0.973 | 0.99 | 1.00 | 1.00 | 0.85 | 13 |
| 5 | Qwen/Qwen3-Embedding-0.6B | 596M | 0.975 | 0.883 | 0.967 | 1.00 | 1.00 | 0.91 | 0.91 | 7 |
| 6 | ibm-granite/granite-embedding-97m-multilingual-r2 | 97M | 0.952 | 0.850 | 0.939 | 0.99 | 1.00 | 0.88 | 0.78 | **103** |
| 7 | microsoft/harrier-oss-v1-270m | 268M | 0.906 | 0.783 | 0.889 | 0.99 | 1.00 | 0.41 | 0.91 | 30 |
| 8 | intfloat/multilingual-e5-large-instruct | 560M | 0.857 | 0.783 | 0.854 | 0.98 | 1.00 | **0.08** | 0.91 | 11 |
| 9 | sentence-transformers/all-MiniLM-L6-v2 | 23M | 0.529 | 0.400 | 0.505 | 0.45 | 0.96 | 0.00 | 0.20 | 149 |

(ko/en/ko→en/en→ko 열은 그룹별 nDCG@10)

### 의미 유사도 — `ko_sts_mini` (문장쌍 24)

| 순위 | 모델 | Spearman | Pearson |
|---|---|---|---|
| 1 | jinaai/jina-embeddings-v5-text-nano | **0.684** | **0.892** |
| 2 | BAAI/bge-m3 | 0.671 | 0.859 |
| 3 | nlpai-lab/KURE-v1 | 0.665 | 0.859 |
| 4 | intfloat/multilingual-e5-large-instruct | 0.559 | 0.762 |
| 5 | google/embeddinggemma-2 | 0.526 | 0.755 |
| 6 | Qwen/Qwen3-Embedding-0.6B | 0.404 | 0.624 |
| 7 | microsoft/harrier-oss-v1-270m | 0.377 | 0.590 |
| 8 | ibm-granite/granite-embedding-97m-multilingual-r2 | 0.303 | 0.604 |
| 9 | sentence-transformers/all-MiniLM-L6-v2 | 0.170 | 0.098 |

### 실행 실패

| 모델 | 원인 | 조치 |
|---|---|---|
| nomic-ai/nomic-embed-text-v2-moe (v1.5도 같은 코드) | 원격 코드가 transformers 5.x에서 제거된 `get_extended_attention_mask` 호출 | transformers<5 별도 환경 필요. 카탈로그 메모에 기록 |
| jinaai/jina-embeddings-v5-* (처음 실행 시) | `peft` 미설치, 로드 시 `default_task` 필요 | `peft`·`einops` 의존성 추가, 카탈로그에 `default_task=retrieval` 설정 → 해결 |

### 해석과 주의점

- 미니 데이터셋이라 상위 모델은 만점 가까이 나와 **차이가 작습니다**. 순위보다는 "어디서 무너지는가"를 보세요. mE5-instruct와 Harrier-270M은 **한국어 쿼리 → 영어 문서** 교차 검색이 약했습니다.
- 검색과 STS 순위가 다릅니다. EmbeddingGemma 2와 Qwen3는 검색용 프롬프트에서 강하고, STS(프롬프트 없이 문장 비교)에서는 BGE-M3·KURE·Jina v5가 강했습니다. 용도에 맞는 데이터로 평가해야 합니다.
- 속도는 CPU 기준입니다. Granite 97M이 가장 빠르고(103 texts/s), Qwen3-0.6B는 디코더 기반이라 가장 느렸습니다.
- 멀티모달 실측은 [multimodal.md](../stages/multimodal/multimodal.md)에 있습니다.

## 결론 (메모의 요약 수정판)

- **로컬 한국어 RAG**: EmbeddingGemma 2(텍스트 프로필 270M, Apache-2.0)가 이 테스트에서 가장 좋았고 가볍습니다. BGE-M3 / KURE v1 / Qwen3-Embedding-0.6B도 좋은 선택입니다. Jina v5 Nano는 성능이 뛰어나지만 비상업 라이선스입니다.
- **이미지·소리까지 온디바이스 검색**: EmbeddingGemma 2. 이미지+텍스트만이면 Qwen3-VL-Embedding-2B도 후보입니다. VRAM 21GB는 필요 없습니다.
- **API로 편하게**: Gemini Embedding 2, OpenAI text-embedding-3, Cohere **Embed v4** (이 앱은 오픈 모델만 다룹니다).

## 출처

- [google/embeddinggemma-2 모델 카드](https://huggingface.co/google/embeddinggemma-2)
- [EmbeddingGemma 2 발표 (Google 블로그, 2026-10-06)](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/)
- [EmbeddingGemma 2 개발자 가이드](https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/)
- [Cohere Embed v4 발표](https://docs.cohere.com/v2/changelog/embed-multimodal-v4)
- 각 모델 스펙: Hugging Face `config.json`, `config_sentence_transformers.json`, 모델 카드 (2026-10-17 조회)
