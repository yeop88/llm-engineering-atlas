# 아키텍처

## 코드 구조 — 흐름도의 단계 = 패키지

```
app/
  main.py            앱 생성, 시작 시 DB 마이그레이션 · 카탈로그 seed · 중단된 작업 정리, 라우터 등록(공통 → 단계 순서 → 화면)
  core/              모든 단계가 함께 쓰는 기반 (단계를 모른다 — 예외: 모델 카탈로그용 1 임베딩)
    config.py          설정(.env), 경로(BASE_DIR · APP_DIR)
    db.py · migrate.py SQLAlchemy 모델 · Alembic 자동 적용
    crud.py            모델 카탈로그 DB 헬퍼, 실행 이력 기록(record_run), 중단 작업 정리
    schemas.py         공용 스키마만(LLMRef · BulkDelete) — 단계의 요청 스키마는 각 단계의 schemas.py
    jobs.py            백그라운드 작업 큐(스레드 풀) + 작업 기록(job_records, 재시작해도 남음)
    auth.py            선택형 접근 토큰(API_TOKEN)
    runtime.py         디바이스 · dtype · 시스템 정보 · 메모리 표본
    stats.py           부트스트랩 신뢰구간 · 짝지은 비교
    llm.py · llm_api.py LLM 클라이언트(OpenAI 호환 · Claude, 스트리밍 · 그림 입력) · 연결 API
    korean.py          Kiwi 형태소 · 문장 분리 · 명사구
    media_store.py     이미지 · 영상 프레임 파일 위치(data/media/doc-<id>/) · 안전한 경로 해석
    vectorstores/      VectorStore 인터페이스 + Qdrant · pgvector · MariaDB (작은 인덱스는 정확 검색)
    system_api.py      작업 · 실행 이력 · 시스템 정보 API
  stages/            LLM 시스템 엔지니어링 맵의 단계 — 뒤 단계가 앞 단계를 가져다 쓴다
    <단계>/            로직 모듈 + schemas.py(요청 스키마) + api.py 또는 <주제>_api.py(HTTP API)
    embedding/         1 · 데이터 임베딩: catalog · hub · compat(호환성 점검) · model_manager · benchmark · public_benchmarks · projection, datasets/
    rag/               2 · RAG 검색: parsers · chunking · bm25 · fusion · service(검색·리랭킹) · evaluation · answer · verify · legal · public_corpus
    rerank/            3 · 리랭킹: llm_rerank(목록형) · evaluate
    search_lab/        4 · 검색 향상: enhance(질의 재작성 · HyDE · 다중 질의)
    finetune/          5 · 파인튜닝: data · trainer · service
    routing/           6 · 라우팅: routers(규칙 · 확신도 · LLM) · learned(학습 라우터) · service(라우터 채점)
    distill/ quant/    7a 지식 증류 · 7b 양자화
    agent/ rl/         8a 에이전트 · 8b 강화학습
    multimodal/        M · 멀티모달: ingest(이미지 · 영상 수집, 프레임 추출 · 같은 장면 제외)
    apps/              A · 의미 응용: 추천 · 분류 · 군집 · 중복 · 이상 · 키워드, presets/
    registry/          맵 · 단계 설명(데이터만, 다른 앱 모듈을 불러오지 않음)
      model.py           Map · Page · Stage 구조와 문서 경로 규칙
      maps/<맵>.py       맵 1개 = 파일 1개: MAP(흐름 · 원칙 · 예시) + STAGES
      __init__.py        MAP_MODULES 순서로 모으기 · 조회(map_stages · map_flow · stage_for_nav)
  pipeline/          단계 연결 계층 — 단계들을 이어 붙이는 진입점
    search.py          run_search: 2 RAG 검색(+3 리랭킹)에 4 검색 향상을 끼움. 모든 검색 API 가 여기를 거침
    flow.py · api.py   연결 실행기(4 → 1 → 2 → 3 → 6 → 7·8 → 답변), 연결 비교(/api/flow/*)
    schemas.py         경로 · 연결 설정(FlowPath · FlowConfig · RoutingConfig · 라우터 평가 요청)
  web/               화면
    pages.py           페이지 라우터 (맵은 전용 화면 3개 + 공통 화면 /maps/<맵>)
    templates/         base · dashboard · history · roadmap · stage + <영역>/<화면>.html, maps/
    static/js/lib/     공용 스크립트(common.js · charts.js)
    static/js/<영역>/<화면>.js   화면 스크립트 — 템플릿과 같은 구조(templates/rag/answer.html ↔ static/js/rag/answer.js)
tests/               app/ 와 같은 구조: core/ · pipeline/ · web/ · stages/<단계>/, 공용 helpers.py · conftest.py,
                     구조 규칙 test_architecture.py · 문서 test_docs.py
```

### 의존 방향과 배치 규칙 (`tests/test_architecture.py` 가 검사)

- `web · *_api → pipeline → stages → core`. 단계끼리는 흐름도 앞 단계만 가져다 씁니다(예: `rag` 는 `embedding.model_manager`, `finetune` 은 `rag.evaluation`). 앞 단계 화면에서 뒤 단계 기능을 켜야 하면(2 RAG 검색에서 4 검색 향상) 단계끼리 직접 부르지 않고 API 가 `pipeline` 을 부릅니다 — 단계 내부 로직은 `pipeline` 을 모릅니다. 예외로 `core` 의 모델 CRUD 는 1 임베딩의 모델 관리자 · 카탈로그 · 스키마를 씁니다.
- 요청 스키마는 그 단계의 `schemas.py` 에. 여러 단계 설정을 묶는 스키마(경로 · 연결)는 `pipeline/schemas.py`. `core/schemas.py` 는 공용만(80줄 미만 · 단계 import 없음).
- 레지스트리는 데이터만 — 앱의 다른 모듈을 불러오지 않습니다(화면 · 문서 생성이 무거운 모델 코드를 끌고 오지 않게). `maps/` 의 모든 파일이 `MAP_MODULES` 에 있어야 합니다.
- 화면 스크립트는 정적 파일로. 템플릿에는 서버 값 한 줄 설정(`const MODEL_ID = {{ model_id }};`)만 인라인으로 두고, `static/js/` 의 화면 파일은 짝이 되는 템플릿이 있어야 합니다(한 화면을 나누면 `<화면>_<부분>.js`).
- 테스트는 `app/` 와 같은 구조. 최상위에는 `conftest.py` · `helpers.py` · `test_architecture.py` · `test_docs.py` 만.

### 확장 체크리스트

**새 단계 (구현)** — 예: 리랭킹 고도화 · 라우팅 · 에이전트처럼 화면 · API 가 있는 단계

1. `app/stages/<단계>/` — 로직 모듈, `schemas.py`(요청 스키마), `api.py`(라우터, 블로킹 작업은 `def` 또는 `jobs.submit`)
2. `app/main.py` 라우터 목록(흐름도 순서), DB 가 필요하면 `core/db.py` 모델 + Alembic 리비전
3. 화면: `app/web/templates/<단계>/<화면>.html` + `app/web/static/js/<단계>/<화면>.js`, `pages.py` 의 `PAGES`
4. 레지스트리: `app/stages/registry/maps/<맵>.py` 의 단계 항목(상태 · `pages` · 원리 · 왜 · 어떻게 · 할 일)
5. 테스트: `tests/stages/<단계>/test_<주제>.py` (가짜 모델 · `tests/helpers.py` · 공용 픽스처 `scripted_llm` · `rag_collection`)
6. 문서: `docs/stages/<맵>/<번호>-<이름>/<단계>.md` 상세 · 실측, `uv run python scripts/gen_docs.py`, `CHANGELOG.md`, `docs/guides/api.md`

**새 맵** — 1. `app/stages/registry/maps/<맵>.py` 에 `MAP`(흐름 묶음 · 원칙 · 예시) + `STAGES` 2. `registry/__init__.py` 의 `MAP_MODULES` 에 한 줄 3. `uv run python scripts/gen_docs.py` (화면 `/maps/<맵>` · 개요 · 단계 문서가 생김). 전용 화면이 필요할 때만 `template` 을 지정하고 템플릿을 만듭니다.

**새 화면만** — 템플릿 + 같은 경로의 화면 스크립트 + `PAGES` + 레지스트리 단계의 `pages`.

## 요청 흐름

```
브라우저 (Jinja2 페이지 + 바닐라 JS)
   │  fetch /api/*
   ▼
FastAPI 라우터 ── core/system_api · llm_api / stages/*/…_api / web/pages
   │
   ├─ core/crud · db ─────────── 앱 DB (SQLite 기본, Alembic): 모델 · 실행 이력 · 컬렉션 · 평가 세트 · 파인튜닝 …
   ├─ stages/embedding/hub ───── Hugging Face Hub API, 로컬 캐시(~/.cache/huggingface/hub)
   ├─ stages/embedding/model_manager ─ SentenceTransformer · CrossEncoder 인스턴스 (메모리, LRU)
   ├─ core/jobs ──────────────── 백그라운드 작업 (다운로드 · 벤치마크 · 인덱스 · 평가 · 학습)
   └─ core/llm ───────────────── 로컬 LLM(OpenAI 호환) · Claude API
```

## 문서 검색 (RAG) 구성

```
업로드 ─ stages/rag/parsers ─▶ Document(pages)            ── 앱 DB (SQLite 기본, Alembic 관리)
            │
   ChunkSet(전략) ─ rag/chunking + core/korean(Kiwi 형태소) ─▶ Chunk(text, tokens)
            │
   VectorIndex(모델·저장소) ─ ModelManager.encode(document) ─▶ core/vectorstores/{qdrant|pgvector|mariadb}
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

`jobs.submit(kind, title, fn)` → ThreadPoolExecutor(2 workers). 계산은 메모리에서 돌고 상태 · 진행률 · 결과는 DB(`job_records`)에도 남깁니다 — 재시작하면 끝나지 않은 작업은 '중단됨'으로 표시합니다(파인튜닝 · 평가 세트 생성도 같이 정리). 벤치마크 결과는 완료 시 `test_runs`에 저장됩니다. 다운로드 진행률은 `snapshot_download(tqdm_class=...)`의 바이트 진행 바를 가로채 계산합니다.

## 데이터 저장 위치

| 데이터 | 위치 |
|---|---|
| 벡터 (Qdrant 로컬 모드) | `data/qdrant` (서버/pgvector/MariaDB 는 각 DB) |
| DB 마이그레이션 | `migrations/` (Alembic) |
| 앱 DB | `data/app.db` (`DATA_DIR`) |
| 사용자 데이터셋 | `data/datasets/*.json` |
| 내장 데이터셋 | `app/stages/embedding/datasets/*.json` |
| 의미 응용 예시 데이터 | `app/stages/apps/presets/*.json` |
| 학습한 모델 | `data/finetuned/ft-{실행 번호}/` (모델 · train_pairs.jsonl · README.md 기록) |
| 모델 파일 | `~/.cache/huggingface/hub` (`HF_HOME`/`HF_HUB_CACHE`로 변경) |
