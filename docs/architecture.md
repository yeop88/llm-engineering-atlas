# 아키텍처

## 전체 흐름

```
브라우저 (Jinja2 페이지 + 바닐라 JS)
   │  fetch /api/*
   ▼
FastAPI 라우터 ── models / playground / benchmarks / pages
   │
   ├─ crud.py ──────── SQLite (data/app.db): EmbeddingModel, TestRun
   ├─ services/hub.py ─ Hugging Face Hub API, snapshot_download, 로컬 캐시(~/.cache/huggingface/hub)
   ├─ services/model_manager.py ─ SentenceTransformer 인스턴스 (메모리, LRU)
   ├─ services/jobs.py ─ 백그라운드 작업 (다운로드, 벤치마크)
   └─ services/benchmark.py ─ 데이터셋 + 지표 계산
```

## 문서 검색 (RAG) 구성

```
업로드 ─ rag/parsers ─▶ Document(pages)            ── 앱 DB (SQLite 기본, Alembic 관리)
            │
   ChunkSet(전략) ─ rag/chunking + rag/korean(Kiwi 형태소) ─▶ Chunk(text, tokens)
            │
   VectorIndex(모델·저장소) ─ ModelManager.encode(document) ─▶ vectorstores/{qdrant|pgvector|mariadb}
            │
검색 ─ encode(query) → store.search ┐
     └ rag/bm25 (청크 세트별 메모리 캐시) ┴ rag/fusion(RRF/가중합) → ModelManager.rerank(CrossEncoder) → 결과
```

- 청크 id 를 벡터 DB 의 포인트 id 로 쓰고, 문서 id 를 함께 저장해 문서 필터에 씁니다. 벡터 DB 쪽 이름은 `el_vi_{인덱스 id}` 입니다.
- BM25 는 문서 쪽 가중치를 미리 계산한 희소 행렬(scipy)로 메모리에 두고, 청크 수·최대 id 가 바뀌면 다시 만듭니다.
- 청크 세트 생성·인덱스 구축은 백그라운드 작업(`jobs`)이고, 실패하면 상태가 `error` 로 남아 화면에서 다시 구축할 수 있습니다.

## 모델 상태

| 상태 | 의미 | 판단 근거 |
|---|---|---|
| 등록됨 | 카탈로그(DB)에 있음 | `embedding_models` 테이블 |
| 다운로드됨 | 로컬 HF 캐시에 파일 있음 | `scan_cache_dir()` (5초 캐시) |
| 로드됨 | 메모리에 SentenceTransformer 인스턴스 존재 | `ModelManager._models` |

다운로드 없이 바로 로드해도 SentenceTransformer가 필요한 파일을 자동으로 받습니다. "다운로드" 버튼은 진행률을 보며 미리 받아 두는 용도입니다.

## 모델 로딩 (`ModelManager`)

- 키: `"{hf_id}::{profile}"` — profile은 `text` 또는 `multimodal`.
  - EmbeddingGemma 2는 `text` 프로필에서 `config_kwargs={"vision_config": None, "audio_config": None}`로 270M 텍스트 경로만 올리고, `multimodal` 프로필에서는 비전 인코더를 포함합니다. 두 프로필은 같은 체크포인트라 **같은 벡터 공간**입니다.
- dtype: `DTYPE=auto`이면 CUDA+bf16 지원 시 bfloat16, 그 외 float32. float16은 명시적으로 지정할 때만 사용합니다.
- `MAX_LOADED_MODELS`를 넘으면 가장 오래 사용하지 않은 모델부터 언로드합니다.
- 같은 모델을 동시에 두 번 로드하지 않도록 키별 락을 씁니다. 인코딩도 모델별 락으로 직렬화합니다.
- DB에서 모델 설정(프롬프트, 로드 kwargs 등)을 바꾸면 `ModelSpec`이 달라지므로 다음 사용 시 자동으로 다시 로드됩니다.
- 로드 후 실제 임베딩 차원을 DB에 반영하고, 토크나이저에 최대 길이가 없으면 카탈로그의 `max_seq_len`으로 제한합니다.

## 프롬프트 적용 규칙

`ModelManager.encode(..., role)`의 role이 `query`/`document`일 때:

1. `query_prompt`/`document_prompt`(prompt_name)가 모델의 `prompts`에 있으면 `prompt_name=`으로 전달
2. 없으면 경고를 남기고 무시
3. `query_prefix`/`document_prefix`가 있으면 텍스트 앞에 직접 붙임
4. `query_kwargs`/`document_kwargs`를 encode에 추가 전달 (예: Jina v3의 `task`)

`plain`은 아무것도 적용하지 않습니다(모델의 `default_prompt_name`은 SentenceTransformer가 자동 적용). 유사도 행렬과 STS 벤치마크는 기본적으로 `plain`을 씁니다.

## 백그라운드 작업

`jobs.submit(kind, title, fn)` → ThreadPoolExecutor(2 workers). 작업 상태는 메모리에만 있고 서버를 재시작하면 사라집니다. 벤치마크 결과는 완료 시 `test_runs`에 저장됩니다. 다운로드 진행률은 `snapshot_download(tqdm_class=...)`의 바이트 진행 바를 가로채 계산합니다.

## 데이터 저장 위치

| 데이터 | 위치 |
|---|---|
| 벡터 (Qdrant 로컬 모드) | `data/qdrant` (서버/pgvector/MariaDB 는 각 DB) |
| DB 마이그레이션 | `migrations/` (Alembic) |
| 앱 DB | `data/app.db` (`DATA_DIR`) |
| 사용자 데이터셋 | `data/datasets/*.json` |
| 내장 데이터셋 | `app/data/datasets/*.json` |
| 모델 파일 | `~/.cache/huggingface/hub` (`HF_HOME`/`HF_HUB_CACHE`로 변경) |
