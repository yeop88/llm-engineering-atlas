# 모델 카탈로그 (2026-10 기준)

앱을 처음 실행하면 아래 임베딩 모델 37개와 리랭커 11개가 등록됩니다. 스펙은 각 모델의 Hugging Face 설정 파일(`config.json`, `config_sentence_transformers.json`)과 모델 카드를 기준으로 했습니다. 공개일은 공식 발표일 또는 Hub 저장소 생성일입니다. Hub 통계(다운로드·좋아요)는 모델 상세 화면의 **Hub 동기화**로 갱신됩니다.

| 모델 | 제공사 | 공개일 | 파라미터 | 차원 (MRL) | 컨텍스트 | 라이선스 | 언어 | 모달리티 |
|---|---|---|---|---|---|---|---|---|
| [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) | Google | 2026-10-06 | 740M (텍스트 270M) | 768 (512/256/128) | 8,192 | Apache-2.0 | multilingual | text, image, audio, video |
| [Nemotron-3-Embed 1B](https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16) | NVIDIA | 2026-07-14 | 1.1B | 2048 | 32,768 | OpenMDW-1.1 | multilingual | text |
| [Nemotron-3-Embed 8B](https://huggingface.co/nvidia/Nemotron-3-Embed-8B-BF16) | NVIDIA | 2026-07-14 | 8.0B | 4096 | 32,768 | OpenMDW-1.1 | multilingual | text |
| [LFM2.5-Embedding 350M](https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M) | Liquid AI | 2026-05-05 | 354M | 1024 | 512 | LFM Open License v1.0 | multilingual (ko/ja/zh 포함) | text |
| [Granite Embedding 97M Multilingual R2](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2) | IBM | 2026-04-20 | 97M | 384 | 32,768 | Apache-2.0 | multilingual (ko 포함) | text |
| [Granite Embedding 311M Multilingual R2](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2) | IBM | 2026-04-20 | 312M | 768 (512/384/256/128) | 32,768 | Apache-2.0 | multilingual (ko 포함) | text |
| [Jina Embeddings v5 Omni Small](https://huggingface.co/jinaai/jina-embeddings-v5-omni-small) | Jina AI | 2026-04-01 | 1.6B | 1024 (768…32) | 32,768 | CC-BY-NC-4.0 | multilingual | text, image |
| [Harrier-OSS v1 270m](https://huggingface.co/microsoft/harrier-oss-v1-270m) | Microsoft | 2026-03-30 | 268M | 640 | 32,768 | MIT | multilingual (90+) | text |
| [Harrier-OSS v1 0.6b](https://huggingface.co/microsoft/harrier-oss-v1-0.6b) | Microsoft | 2026-03-30 | 596M | 1024 | 32,768 | MIT | multilingual (90+) | text |
| [Harrier-OSS v1 27b](https://huggingface.co/microsoft/harrier-oss-v1-27b) | Microsoft | 2026-03-30 | 27B | 5376 | 131,072 | MIT | multilingual (90+) | text |
| [Jina Embeddings v5 Text Small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small) | Jina AI | 2026-01-22 | 596M | 1024 (768…32) | 32,768 | CC-BY-NC-4.0 | multilingual | text |
| [Jina Embeddings v5 Text Nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano) | Jina AI | 2026-01-22 | 212M | 768 (512…32) | 8,192 | CC-BY-NC-4.0 | multilingual | text |
| [pplx-embed v1 0.6B](https://huggingface.co/perplexity-ai/pplx-embed-v1-0.6b) | Perplexity | 2026-01-14 | 596M | 1024 (MRL, 차원 미기재) | 32,768 | MIT | multilingual | text |
| [Qwen3-VL-Embedding-2B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) | Alibaba Qwen | 2026-01-07 | 2.1B | 2048 | 32,768 | Apache-2.0 | multilingual | text, image, video |
| [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B) | Alibaba Qwen | 2026-01-07 | 8.1B | 4096 | 32,768 | Apache-2.0 | multilingual | text, image, video |
| [Voyage 4 Nano](https://huggingface.co/voyageai/voyage-4-nano) | Voyage AI | 2026-01-06 | 346M | 2048 (1024/512/256) | 32,768 | Apache-2.0 | multilingual | text |
| [Llama-Embed-Nemotron 8B](https://huggingface.co/nvidia/llama-embed-nemotron-8b) | NVIDIA | 2025-10-07 | 7.5B | 4096 | 32,768 | NVIDIA Custom (비상업) | multilingual | text |
| [EmbeddingGemma 300M](https://huggingface.co/google/embeddinggemma-300m) | Google | 2025-09-04 | 308M | 768 (512/256/128) | 2,048 | Gemma (gated) | multilingual | text |
| [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Alibaba Qwen | 2025-06-05 | 0.6B | 1024 (768…32) | 32,768 | Apache-2.0 | multilingual (100+) | text |
| [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) | Alibaba Qwen | 2025-06-05 | 4B | 2560 (2048…32) | 32,768 | Apache-2.0 | multilingual (100+) | text |
| [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | Alibaba Qwen | 2025-06-05 | 8B | 4096 (2048…32) | 32,768 | Apache-2.0 | multilingual (100+) | text |
| [Nomic Embed Text v2 (MoE)](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe) | Nomic AI | 2025-02-12 | 475M (활성 305M) | 768 (256) | 512 | Apache-2.0 | multilingual (~100) | text |
| [KURE v1](https://huggingface.co/nlpai-lab/KURE-v1) | 고려대 NLP&AI Lab | 2024-12-18 | 568M | 1024 | 8,192 | MIT | ko, en | text |
| [Granite Embedding 278M Multilingual](https://huggingface.co/ibm-granite/granite-embedding-278m-multilingual) | IBM | 2024-12-18 | 278M | 768 | 512 | Apache-2.0 | multilingual (12, ko 포함) | text |
| [Arctic Embed L v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0) | Snowflake | 2024-12-04 | 568M | 1024 (256) | 8,192 | Apache-2.0 | multilingual | text |
| [Jina Embeddings v3](https://huggingface.co/jinaai/jina-embeddings-v3) | Jina AI | 2024-09-18 | 572M | 1024 (512…32) | 8,192 | CC-BY-NC-4.0 | multilingual (89) | text |
| [BGE-m3-ko](https://huggingface.co/dragonkue/BGE-m3-ko) | dragonkue | 2024-09-17 | 568M | 1024 | 8,192 | Apache-2.0 | ko, en | text |
| [GTE Multilingual Base](https://huggingface.co/Alibaba-NLP/gte-multilingual-base) | Alibaba NLP | 2024-07-20 | 305M | 768 | 8,192 | Apache-2.0 | multilingual (70+) | text |
| [mxbai-embed-large-v1](https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1) | Mixedbread | 2024-03-08 | 335M | 1024 (512…64) | 512 | Apache-2.0 | en | text |
| [Nomic Embed Text v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) | Nomic AI | 2024-02-10 | 137M | 768 (512…64) | 8,192 | Apache-2.0 | en | text |
| [mE5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct) | Microsoft (intfloat) | 2024-02-08 | 560M | 1024 | 512 | MIT | multilingual (100+) | text |
| [BGE-M3](https://huggingface.co/BAAI/bge-m3) | BAAI | 2024-01-30 | 568M | 1024 | 8,192 | MIT | multilingual (100+) | text |
| [mE5-large](https://huggingface.co/intfloat/multilingual-e5-large) | Microsoft (intfloat) | 2023-06-30 | 560M | 1024 | 512 | MIT | multilingual (100+) | text |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | sentence-transformers | 2021-08-30 | 22.7M | 384 | 256 | Apache-2.0 | en | text |
| [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | sentence-transformers | 2021-06-22 | 118M | 384 | 128 | Apache-2.0 | multilingual (50+) | text |
| [CLIP ViT-B/32](https://huggingface.co/sentence-transformers/clip-ViT-B-32) | OpenAI (ST 포팅) | 2021-01-05 | 151M | 512 | 77 | MIT | en | text, image |
| [CLIP ViT-L/14](https://huggingface.co/sentence-transformers/clip-ViT-L-14) | OpenAI (ST 포팅) | 2021-01-05 | 428M | 768 | 77 | MIT | en | text, image |

## 리랭커 (Cross-Encoder)

검색으로 뽑은 후보를 질의와 함께 다시 읽어 순위를 매기는 모델입니다. 문서 검색 화면에서 하이브리드 검색 뒤에 붙여 씁니다(입력 길이 기본 1024토큰, `RERANKER_MAX_LENGTH`).

| 모델 | 제공사 | 공개일 | 파라미터 | 최대 길이 | 라이선스 | 언어 |
|---|---|---|---|---|---|---|
| [BGE Reranker v2 M3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | BAAI | 2024-03-15 | 568M | 8,192 | Apache-2.0 | multilingual (100+) |
| [BGE Reranker v2 M3 (한국어)](https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko) | dragonkue | 2024-10-16 | 568M | 8,192 | Apache-2.0 | ko, en |
| [Qwen3-Reranker 0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Alibaba Qwen | 2025-05-29 | 596M | 32,768 | Apache-2.0 | multilingual (100+) |
| [Qwen3-Reranker 4B](https://huggingface.co/Qwen/Qwen3-Reranker-4B) | Alibaba Qwen | 2025-06-03 | 4.0B | 32,768 | Apache-2.0 | multilingual (100+) |
| [mxbai-rerank-base-v2](https://huggingface.co/mixedbread-ai/mxbai-rerank-base-v2) | Mixedbread | 2025-03-03 | 494M | 32,768 | Apache-2.0 | multilingual (100+) |
| [Llama-Nemotron Rerank 1B v2](https://huggingface.co/nvidia/llama-nemotron-rerank-1b-v2) | NVIDIA | 2025-10-16 | 1.2B | 8,192 | OpenMDW-1.1 | multilingual |
| [GTE Multilingual Reranker Base](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base) | Alibaba NLP | 2024-07-20 | 306M | 8,192 | Apache-2.0 | multilingual (70+) |
| [Jina Reranker v2 Base Multilingual](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) | Jina AI | 2024-06-19 | 278M | 1,024 | CC-BY-NC-4.0 | multilingual |
| [zerank-2](https://huggingface.co/zeroentropy/zerank-2-reranker) | ZeroEntropy | 2025-11-19 | 4.0B | 32,768 | Apache-2.0 | en (다국어 일부) |
| [mMiniLMv2 mMARCO (다국어 소형)](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1) | sentence-transformers | 2022-06-01 | 118M | 512 | Apache-2.0 | multilingual (14, ko 미포함) |
| [MS MARCO MiniLM-L6 (영어 소형)](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) | sentence-transformers | 2022-03-02 | 22.7M | 512 | Apache-2.0 | en |

`jinaai/jina-reranker-v3` · `v3.5` 는 전용 구조(JinaForRanking)라 sentence-transformers `CrossEncoder` 로 불러올 수 없어 넣지 않았습니다.

## 선택 가이드

| 상황 | 추천 | 이유 |
|---|---|---|
| CPU/노트북에서 한국어 RAG | EmbeddingGemma 2(텍스트 프로필), Qwen3-Embedding-0.6B, KURE v1, BGE-M3 | 1B 미만, 한국어 품질 검증됨 |
| 이미지·오디오까지 한 공간에서 검색 | EmbeddingGemma 2, Qwen3-VL-Embedding-2B | 네이티브 멀티모달 |
| 최고 정확도 (GPU 있음) | Nemotron-3-Embed 8B, Qwen3-Embedding-8B, Harrier-OSS 27B | 대형 LLM 기반 |
| 저장 공간/속도 최우선 | EmbeddingGemma 2 MRL 128/256, Granite 97M R2, Harrier 270M | 작은 모델 또는 차원 축소 |
| 긴 문서 (8K 토큰 이상) | Qwen3-Embedding, Nemotron-3, Harrier, Granite R2 (32K) | 롱 컨텍스트 |
| 상업 서비스 | Apache-2.0 / MIT 모델 | CC-BY-NC(Jina), NVIDIA Custom, LFM 라이선스는 조건 확인 |

실측 결과와 대체 모델 정보 검증은 [model-verification.md](../../records/model-verification.md)를 참고하세요.

## 카탈로그에 없는 모델 추가

1. **Hub 검색** 화면에서 찾아 "추가" — 프롬프트·차원·라이선스·trust_remote_code를 자동으로 채웁니다.
2. 또는 **모델** 화면의 "+ Hub ID로 추가"에 `조직/모델명`을 입력합니다.
3. 추가 후 모델 상세에서 query/document 프롬프트를 확인하세요. 모델을 한 번 로드하면 사용 가능한 프롬프트 이름이 표시됩니다.

카탈로그 기본값을 바꾸려면 `app/stages/embedding/catalog.py`를 수정합니다. 이미 DB에 있는 모델은 덮어쓰지 않으므로, 기본값을 다시 적용하려면 앱에서 해당 모델을 삭제한 뒤 "삭제한 기본 모델 복원"을 누르세요.

## 모델 삭제

- **모델** 화면에서 행의 "삭제" 버튼, 또는 체크박스로 여러 개를 고른 뒤 "선택 삭제"를 누릅니다. 모델 상세 화면에도 삭제 버튼이 있습니다.
- 삭제 대화상자에서 "다운로드한 로컬 파일(캐시)도 삭제"를 켜면 디스크 공간도 확보합니다. 끄면 파일은 남아 나중에 다시 등록할 때 바로 쓸 수 있습니다.
- 테스트·벤치마크 이력은 지워지지 않습니다.
- 기본 카탈로그 모델을 삭제하면 그 사실을 기억해 **서버를 재시작해도 다시 생기지 않습니다**. 되돌리려면 모델 화면의 "삭제한 기본 모델 복원 (n)" 버튼을 누릅니다(카탈로그 기본 설정으로 다시 등록).
