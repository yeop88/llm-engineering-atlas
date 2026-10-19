# 아키텍처

## 코드 구조 — 흐름도의 단계 = 패키지

```
app/
  main.py            앱 생성, 시작 시 DB 마이그레이션 · 카탈로그 seed · 중단된 작업 정리, 라우터 등록(공통 → 단계 순서 → 화면)
  core/              모든 단계가 함께 쓰는 기반
    config.py          설정(.env), 경로(BASE_DIR · APP_DIR)
    db.py · migrate.py SQLAlchemy 모델 · Alembic 자동 적용
    crud.py            모델 카탈로그 DB 헬퍼, 실행 이력 기록(record_run), 중단 작업 정리
    schemas.py         API 요청/응답 스키마
    jobs.py            인메모리 백그라운드 작업 큐
    runtime.py         디바이스 · dtype · 시스템 정보 · 메모리 표본
    stats.py           부트스트랩 신뢰구간 · 짝지은 비교
    llm.py · llm_api.py LLM 클라이언트(OpenAI 호환 · Claude, 스트리밍) · 연결 API
    korean.py          Kiwi 형태소 · 문장 분리 · 명사구
    media.py           이미지 · 영상 프레임 파일 위치(data/media/doc-<id>/) · 안전한 경로 해석
    vectorstores/      VectorStore 인터페이스 + Qdrant · pgvector · MariaDB (작은 인덱스는 정확 검색)
    system_api.py      작업 · 실행 이력 · 시스템 정보 API
  stages/            LLM 시스템 엔지니어링 맵의 단계 — 뒤 단계가 앞 단계를 가져다 쓴다
    embedding/         1 · 데이터 임베딩: catalog · hub · model_manager · benchmark · public_benchmarks · projection, datasets/
    rag/               2 · RAG 검색: parsers · chunking · bm25 · fusion · service(검색·리랭킹) · evaluation(질문 유형 · 채점 규칙) · answer · verify(근거 검증 방식 · 일치도) · public_corpus(공개 자료)
    multimodal/        멀티모달: media(이미지 · 영상 수집, 프레임 추출 · 같은 장면 제외) — 결과는 RAG 컬렉션의 미디어 문서
    rerank/            3 · 리랭킹: llm_rerank(목록형) · evaluate(리랭커 × 후보 수 × 융합) · api
    distill/           7a · 지식 증류: service(교사 오답 · 점수 차 → MarginMSE 학습 → 비교) · llm_data(교사 답 JSONL) · api
    agent/             8a · 에이전트: agent(ReAct 루프 · 도구 search/read/calc · 근거 검증) · api(스트리밍)
    rl/                8b · 강화학습: reward(보상 함수) · service(Best-of-N · 선호 쌍 · DPO 내보내기) · api
    quant/             7b · 양자화: vectors(float32 · int8 · binary · 재점수 점수와 메모리) · llm_bits(같은 근거로 LLM 비트 수 비교) · api
    routing/           6 · 라우팅: routers(규칙 · 검색 확신도 · LLM 판단) · service(두 경로 기록으로 라우터 채점 · 오라클 · 기준값 곡선) · api
    search_lab/        4 · 검색 향상: enhance(질의 재작성 · HyDE · 다중 질의, LLM 변형 캐시)
    finetune/          파인튜닝: data(학습 쌍) · trainer · service(학습 → 등록 → 전후 비교 → 기록)
    apps/              의미 기반 응용: 추천 · 분류 · 군집 · 중복 · 이상 · 키워드, presets/
    (각 단계의 *_api.py · api.py 가 그 단계의 HTTP API)
  pipeline/          단계 연결 계층 — 단계들을 이어 붙이는 진입점
    search.py          run_search: 2 RAG 검색(+3 리랭킹)에 4 검색 향상을 끼움. 모든 검색 API 가 여기를 거침
    flow.py · api.py   연결 실행기: 4 → 1 → 2 → 3 → 6 → 7·8 → 답변을 이어 단계별 상태 · 시간 기록, 평가 세트로 연결 방식 비교(/api/flow/*)
  web/               화면
    pages.py           페이지 라우터
    templates/         base · dashboard · history · roadmap + 단계별 하위 폴더(embedding · rag · finetune · multimodal · apps)
    static/            css · js
```

의존 방향: `web · *_api → pipeline → stages → core`, 단계끼리는 흐름도 앞 단계만 가져다 씁니다(예: `rag` 는 `embedding.model_manager`, `finetune` 은 `rag.evaluation` 을 씀). 앞 단계 화면에서 뒤 단계 기능을 켜야 할 때(예: 2 RAG 의 검색 · 평가 · 답변에서 4 검색 향상)는 단계끼리 직접 가져다 쓰지 않고 API 가 `pipeline` 을 부릅니다 — 단계 내부 로직은 `pipeline` 을 모릅니다. 예외로 `core` 의 모델 CRUD 는 1 임베딩의 모델 관리자 · 카탈로그를 씁니다. 이 규칙은 `tests/test_search_lab.py::test_dependency_direction` 이 검사합니다. 새 단계(리랭킹 고도화 · 라우팅 · 증류 · 양자화 · 에이전트 · 강화학습)는 `app/stages/<단계>/` 로 추가합니다([roadmap.md](../maps/llm.md)).

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

`jobs.submit(kind, title, fn)` → ThreadPoolExecutor(2 workers). 작업 상태는 메모리에만 있고 서버를 재시작하면 사라집니다(시작할 때 DB 에 '진행 중'으로 남은 파인튜닝 · 평가 세트 생성은 '중단됨'으로 정리). 벤치마크 결과는 완료 시 `test_runs`에 저장됩니다. 다운로드 진행률은 `snapshot_download(tqdm_class=...)`의 바이트 진행 바를 가로채 계산합니다.

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
