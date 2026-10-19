# REST API

> `API_TOKEN` 을 설정한 서버는 모든 `/api/*` 에 `Authorization: Bearer <토큰>` 헤더가 필요합니다(`/api/health` 제외) — `docs/guides/deploy.md`.

서버 실행 후 http://127.0.0.1:8000/docs (Swagger UI)에서 모든 엔드포인트를 직접 호출해 볼 수 있습니다.

## 모델

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/models?q=&kind=&modality=&tag=&status=&sort=` | 목록. kind: `embedding`/`reranker`, status: `cached`/`loaded`/`favorite`, sort: `release_date`/`downloads`/`name`/`dim` |
| POST | `/api/models` | 수동 등록 (`hf_id` 필수) |
| GET / PATCH / DELETE | `/api/models/{id}` | 조회 / 수정 / 삭제(`?delete_cache=true`) |
| POST | `/api/models/{id}/sync?overwrite=false` | Hub 통계 갱신, 빈 스펙 보완 |
| POST | `/api/models/{id}/download` | 백그라운드 다운로드 → 작업 객체 반환 |
| DELETE | `/api/models/{id}/cache` | 로컬 캐시 삭제 |
| POST | `/api/models/{id}/load?multimodal=false` | 로드 (동기) |
| POST | `/api/models/{id}/unload` | 언로드 |
| POST | `/api/models/bulk-delete` | `{"ids": [...], "delete_cache": false}` 여러 모델 삭제 |
| GET | `/api/catalog/exclusions` | 삭제해서 seed 에서 제외된 기본 카탈로그 모델 |
| POST | `/api/catalog/restore` | 삭제한 기본 카탈로그 모델 복원 |
| GET | `/api/loaded` | 로드된 모델 |
| POST | `/api/loaded/unload-all` | 전부 언로드 |

## 문서 검색 (RAG)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/rag/options` | 청킹 방법·기본값, 지원 파일 형식, 벡터 DB 상태 |
| GET | `/api/vector-stores` | 벡터 DB 연결 상태 (qdrant / pgvector / mariadb) |
| GET / POST | `/api/collections` | 컬렉션 목록 / 생성 `{"name", "domain", "description"}` |
| GET / PATCH / DELETE | `/api/collections/{id}` | 상세(문서·청크 세트·인덱스) / 수정 / 삭제(벡터 DB 데이터 포함) |
| GET | `/api/public-corpora` | 공개 자료 프리셋 목록(설명 · 라이선스) |
| POST | `/api/collections/{id}/import-public` | 공개 자료 가져오기 작업 `{"preset": "labor_lease_law", "max_precedents"?}` |
| POST | `/api/collections/{id}/documents` | 파일 업로드 (multipart `files`, 여러 개) → `added`, `skipped`. 이미지 · 영상도 받음(영상은 프레임 추출 결과가 `warning` 에) |
| GET / DELETE | `/api/documents/{id}` | 본문 보기 / 삭제(청크·벡터 함께) |
| POST | `/api/collections/{id}/chunk-preview` | 청킹 미리보기 `{"method", "size", "overlap", ...}` → 통계·예시 |
| POST | `/api/collections/{id}/chunk-sets` | 청크 세트 생성 (백그라운드 작업) |
| GET | `/api/chunk-sets/{id}/chunks?offset=&limit=&document_id=` | 청크 목록 (BM25 토큰 포함) |
| DELETE | `/api/chunk-sets/{id}` | 청크 세트와 그 인덱스 삭제 |
| POST | `/api/indexes` | `{"chunk_set_id", "model_id", "store": "qdrant", "truncate_dim": null}` → 인덱스 구축 작업 |
| POST | `/api/indexes/{id}/rebuild` · DELETE `/api/indexes/{id}` | 다시 구축 / 삭제 |
| POST | `/api/collections/{id}/search` | 검색 비교 (아래) |
| GET | `/api/chunks/{id}/media` · `/api/documents/{id}/media` | 이미지 · 영상 프레임 청크의 그림 / 이미지 · 영상 원본 (검색 결과의 `media.url` · `media.source_url`) |

```http
POST /api/collections/1/search
{"query": "공문서는 어떤 문자로 작성하나요?",
 "configs": [
   {"label": "BM25", "chunk_set_id": 1, "mode": "bm25", "top_k": 5},
   {"label": "하이브리드+리랭커", "index_id": 2, "mode": "hybrid", "fusion": "rrf",
    "candidates": 50, "reranker_id": 40, "rerank_top": 30, "top_k": 5, "doc_ids": null}]}
```

응답의 각 결과에는 `results[]`(문서·쪽·조문 제목·본문·점수·순위), `timings_ms`, `query_tokens` 가 들어 있습니다.

검색 설정(`SearchConfig`)에 `enhance` 를 넣으면 4 검색 향상이 적용됩니다. 검색 비교 · 조합 평가(`/api/eval-sets/{id}/evaluate`) · 답변 생성 · 답변 평가 모두 같은 형식입니다.

```json
{"mode": "dense", "index_id": 3,
 "enhance": {"technique": "rewrite", "keep_original": true, "n": 3, "provider": null, "model": null}}
```

`technique`: `none`(기준선) · `rewrite`(질의 재작성) · `hyde`(가상 문서, 문서 역할로 인코딩) · `multi`(다중 질의 `n`개). 응답에 `enhance`(LLM 이 만든 변형 · LLM 시간 · 캐시 사용 여부)가 붙고, `timings_ms.llm` 에 변형 생성 시간이 들어갑니다.

## 의미 기반 응용

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/apps/presets?app=` · `/api/apps/presets/{name}` | 예시 데이터 |
| POST | `/api/apps/items` | 입력 소스 펼쳐 보기 `{"source": {...}}` |
| GET | `/api/apps/cache` | 임베딩 캐시 통계 |
| POST | `/api/apps/recommend` | 콘텐츠 추천 (작업) |
| POST | `/api/apps/classify/zero-shot` · `/api/apps/classify/train` | 제로샷 분류 / 분류기 학습·평가·저장 (작업) |
| POST | `/api/apps/cluster` | 클러스터링 (작업) |
| POST | `/api/apps/dedup` · `/api/apps/plagiarism` | 중복 제거 / 문장 단위 표절 검사 (작업) |
| POST | `/api/apps/anomaly` | 이상·신종 탐지, `test` 가 없으면 학습 데이터 안 이상치 찾기 (작업) |
| POST | `/api/apps/keywords` · `/api/apps/summary` | 문서별 키워드 추출 / 추출 요약 (작업) |
| POST | `/api/apps/detectors/{id}/score` | 저장된 탐지기로 판정 `{"texts": [...]}` |
| POST | `/api/apps/classifiers/{id}/predict` | 저장된 분류기로 예측 `{"texts": [...]}` |
| GET / DELETE | `/api/apps/models?kind=` · `/api/apps/models/{id}` | 저장된 분류기·탐지기 목록 / 삭제 |

입력 소스: `{"type": "texts", "items": [{"text", "label"?, "id"?}]}` 또는 `{"type": "collection", "collection_id", "unit": "document"|"chunk", "chunk_set_id"?}`

## Hub

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/hub/search?q=&sort=&limit=&pipeline_tag=` | Hub 검색 |
| GET | `/api/hub/info?hf_id=` | 메타데이터 미리보기 |
| POST | `/api/hub/import` | `{"hf_id": "..."}` 카탈로그 등록 |
| GET | `/api/hub/discover?days=180&min_likes=10&limit=30&force=` | 카탈로그에 없는 최근 인기 모델 후보(자동 추가 안 함) — `docs/guides/deploy.md` |
| POST | `/api/models/compat-check` | 본문 `[모델 id…]` 또는 없음(내려받은 모델 전부) → 작업. 로드 · 차원 · NaN · 프롬프트 · 순서 점검 |
| GET | `/api/models/compat-check/last` | 마지막 점검 결과 · 지금 라이브러리 버전 · `upgrade_detected` |

## 테스트

```http
POST /api/embed
{"model_id": 1, "texts": ["..."], "role": "query", "truncate_dim": 256, "normalize": true, "preview": 8}

POST /api/similarity
{"model_id": 1, "texts": ["a", "b", "c"], "role": "plain"}

POST /api/retrieve
{"model_ids": [1, 2], "query": "...", "documents": ["...", "..."], "top_k": 5, "truncate_dim": null}

POST /api/projection
{"model_ids": [1, 2], "items": [{"group": "ko", "text": "..."}, {"group": "en", "text": "..."}],
 "method": "pca", "role": "plain", "pair_groups": true}
→ 모델별 points([[x, y], ...]), explained_variance(PCA), alignment(쌍 코사인·차이·짝 찾기 정확도)

POST /api/multimodal/retrieve   (multipart/form-data)
model_ids=1,34  query=...  files=@a.png files=@b.jpg
```

## 벤치마크 / 작업 / 이력

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/datasets` | 데이터셋 목록 |
| GET | `/api/datasets/{name}` | 데이터셋 내용 |
| POST | `/api/datasets` | JSON 파일 업로드 (multipart `file`) |
| DELETE | `/api/datasets/{name}` | 사용자 데이터셋 삭제 |
| GET | `/api/public-benchmarks` | 공개 한국어 벤치마크 목록과 가져온 상태 |
| POST | `/api/public-benchmarks/{key}/import` | 내려받아 데이터셋 `pub_{key}` 로 추가 (작업) `{"max_queries", "max_corpus", "seed"}` |
| POST | `/api/benchmarks` | `{"model_ids": [...], "dataset": "...", "truncate_dim": null, "batch_size": null, "unload_after": false, "sweep_dims": [768, 256, 64]}` → 작업. `sweep_dims`가 있으면 결과의 모델별 `dim_sweep`에 차원별 지표 포함 |
| GET | `/api/jobs?kind=&limit=` · `/api/jobs/{id}` | 작업 상태 (progress 0~1, message, result). DB 기록(`job_records`)을 함께 보므로 재시작 전 작업도 나옴, 끊긴 작업은 `interrupted` |
| GET | `/api/health` | 상태 확인 (인증 없이 열림) |
| POST | `/api/jobs/{id}/cancel` | 취소 요청 |
| GET | `/api/runs?kind=&dataset=&limit=` · `/api/runs/{id}` | 실행 이력 (`dataset`은 벤치마크 데이터셋 이름) |
| GET | `/api/runs/summary` | 종류별 이력 개수 |
| DELETE | `/api/runs/{id}` | 이력 1건 삭제 |
| POST | `/api/runs/bulk-delete` | `{"ids": [...]}` 여러 건 삭제 |
| DELETE | `/api/runs?confirm=true&kind=&dataset=` | 범위 전체 삭제 (`confirm=true` 필수, kind/dataset 없으면 전부) |
| GET | `/api/benchmarks/trend?dataset=` | 데이터셋별 실행 추세 (모델별 대표 지표 시계열) |
| GET | `/api/system/metrics` | 메모리 표본 (5초 간격, 최근 10분) |
| GET | `/api/system` | 버전, 디바이스, 메모리, 로드 상태 |

## 예시 (PowerShell)

```powershell
$m = (Invoke-RestMethod "http://127.0.0.1:8000/api/models?q=embeddinggemma-2")[0]
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/embed" -ContentType "application/json" `
  -Body (@{ model_id = $m.id; texts = @("안녕하세요"); role = "query"; truncate_dim = 256 } | ConvertTo-Json)
```

## LLM

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/llm/status` | LLM 설정 상태 (키 값 제외) |
| POST | `/api/llm/test` | 연결 시험 |

## 문서 검색 평가

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/collections/{id}/eval-sets` | 평가 세트 목록 / 직접 입력·가져오기 `{"name", "method": "manual"\|"import", "items": [{"query", "doc_ids", "evidence"}]}` |
| POST | `/api/collections/{id}/eval-sets/generate` | 생성 (작업) `{"method": "llm"|"sentence", "chunk_set_id", "n_passages", "document_ids"?, "styles", "provider"?, "model"?}` — `document_ids` 면 그 문서에서만 지문 |\|"sentence", "chunk_set_id", "n_passages", "styles", "provider"?, "model"?}` |
| GET / PATCH / DELETE | `/api/eval-sets/{id}` | 조회(질문 포함) / 이름·질문 수정 / 삭제 |
| GET | `/api/eval-sets/{id}/export` | JSON 내려받기 |
| POST | `/api/eval-sets/{id}/evaluate` | 조합 평가 (작업) `{"configs": [SearchConfig, ...], "max_queries"?}` |
| GET | `/api/eval-sets/{id}/runs` | 이 평가 세트의 조합 평가 이력 |

## RAG 답변 생성

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/collections/{id}/answer` | NDJSON 스트림: `search` → `delta`(여러 번) → `verify` → `judge`(선택) → `done`, 오류는 `error`. 본문 `{"question", "config": SearchConfig, "context_top", "max_context_chars", "max_tokens", "temperature", "judge", "provider"?, "model"?}` |
| POST | `/api/eval-sets/{id}/answer-eval` | 평가 세트로 답변 일괄 평가 (작업) `{"config", "max_queries", "context_top", ...}` |

## 파인튜닝

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/finetune` | 실행 목록 / 학습 시작(작업) |
| GET / DELETE | `/api/finetune/{id}` | 상세(손실 기록 포함) / 삭제 (`?delete_model=true` 면 학습한 모델과 파일도) |
| POST | `/api/finetune/{id}/compare` | 학습 전후 비교만 다시 계산 (`?eval_set_id=` 로 다른 평가 세트, 학습에서 제외한 세트만) |
| GET | `/api/finetune/{id}/card` | 실행 기록(모델 카드, Markdown) |


## 연결 실행 (맵)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/flow/steps` | 흐름 단계 목록(서비스 순서) |
| POST | `/api/flow/run` | 한 질문을 연결 실행. 본문 `{"question", "flow": FlowConfig, "provider"?, "model"?}` → `steps[]`(key · 단계 번호 · 상태 run/off/default · ms · 설명), `results`, `answer`(답변 단계를 켰을 때), `total_ms` |
| POST | `/api/flow/evaluate` | 평가 세트로 연결 방식(최대 4개, 첫 번째가 기준) 비교 작업. `{"eval_set_id", "flows": [FlowConfig], "max_queries"}` |

`FlowConfig`: `{"label", "config": SearchConfig(enhance · reranker_id 포함), "answer": true, "context_top": 5, "max_context_chars", "max_tokens"}`

## 라우팅

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/routing/route` | 질문 하나를 라우터들에 넣어 판단만 봄. `{"question", "easy": FlowPath, "routers": ["rule","confidence","llm"], "threshold", "rule_max_chars"}` → `decisions[]`(path easy/hard · 이유 · ms) |
| POST | `/api/routing/evaluate` | 평가 세트로 라우터 비교 작업. `{"eval_set_id", "easy": FlowPath, "hard": FlowPath, "routers", "threshold", "max_queries"}` → 라우터별 어려움 비율 · 품질(95% 구간) · 전체 경로 대비 짝지은 차이 · 지연, 확신도 기준값 곡선(`sweep`), 질문별 판단 |

연결 실행의 `FlowConfig` 에 `"routing": {"router", "threshold", "rule_max_chars", "hard": FlowPath}` 를 넣으면 라우터가 어렵다고 판단한 질문만 `hard` 경로로 처리합니다. `FlowPath.model` 로 경로별 답변 모델을 지정할 수 있습니다.

## 양자화

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/quant/options` | 기술 카탈로그(`techniques` · `groups`) · KV 캐시 종류 · 검색 벤치마크 데이터셋 · 로컬 GGUF 파일(`LLM_MODELS_DIR`) · 모델별 서버 주소 |
| POST | `/api/quant/vectors` | 양자화 조합 비교 작업. `{"dataset", "model_ids": [..3], "weights": ["w_fp32","w_bf16","w_int8"], "dims": [512, 256], "precisions": ["float32","float16","int8","int4","binary","binary_rescore","pq"], "rescore_mult": 4, "pq_m": 32, "max_queries"?}` → 모델별 조합 행(지표 · 기준 대비 짝지은 차이 · 기준 상위 10 유지율 · 메모리 · 검색 시간 · 인코딩 속도 · 파레토 여부) |
| POST | `/api/quant/llm-command` | 가중치(GGUF) × KV 캐시 양자화 llama-server 명령과 `.env` 줄 만들기. `{"model_path", "alias", "port", "kv_k", "kv_v", "ctx"}` |
| POST | `/api/quant/llm` | LLM 비교 작업(같은 근거). `{"eval_set_id", "config": SearchConfig, "models": [..4], "max_queries"}` → 모델별 품질 · 답변 지표 · 질문당 시간 · 생성 속도, 첫 모델 대비 짝지은 차이 |

모델별 서버 주소: `.env` 의 `OPENAI_MODEL_URLS={"모델 이름": "http://주소/v1"}` — 목록에 없는 모델은 `OPENAI_BASE_URL`.

## 리랭킹 · 지식 증류 · 에이전트 · 강화학습

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/rerank/evaluate` | 리랭커 평가 작업. `{"eval_set_id", "config": SearchConfig, "reranker_ids": [..4], "ks": [5,10,20], "llm": {"top", "max_chars", "model"}?}` → 리랭커 · 후보 수 · 융합별 nDCG(95% 구간) · 리랭킹 없음 대비 · 지연 |
| GET / POST | `/api/distill` | 증류 실행 목록 / 시작(`FinetuneCreate` + `teacher_model_id`, 학생 = `base_model_id`) |
| POST | `/api/distill/llm-data` | LLM 증류 데이터 작업. `{"collection_id", "chunk_set_id", "config", "n_passages", "teacher_model"?, "min_support": 0.8}` |
| GET | `/api/distill/llm-data` · `/api/distill/llm-data/{name}` | 만든 JSONL 목록 / 내려받기 |
| POST | `/api/agent/run` | 에이전트 실행 NDJSON 스트림: `step`(n · thought · action · input · observation · ms) … `final`(answer · sources · verify · steps). `{"question", "config", "agent": {"max_steps", "top_k", "max_chars"}}` |
| GET | `/api/rl/reward-weights` | 보상 가중치 |
| POST | `/api/rl/sample` | 같은 근거로 답 후보 n 개와 보상 (사람이 고르기용) |
| GET / POST / DELETE | `/api/rl/preferences` · `/api/rl/preferences/{id}` | 선호 쌍 목록(자동 · 사람 수) / 저장 / 삭제 |
| GET | `/api/rl/preferences/export` | DPO 형식 JSONL (`?source=auto|human`) |
| POST | `/api/rl/evaluate` | Best-of-N 평가 작업 — 평소 답 대비 품질 · 보상 짝지은 비교, 보상 차가 큰 쌍 자동 저장 |

검색 설정(`SearchConfig`): `"rerank_fusion": true`(크로스 인코더 순위와 1단계 순위 RRF), `"llm_rerank": {"top": 10, "max_chars": 300, "fusion": false}`(LLM 목록형, 연결 계층에서 적용). 처리 경로(`FlowPath`): `"model"`(경로 답변 모델), `"agent": {"max_steps", "top_k"}`(8a), `"best_of": 4`(8b), `"compress": {"keep": 3}`(근거 압축). 청킹 전략(`ChunkStrategy`)에 `"merge_below": 200`(짧은 청크 합치기).

평가 세트 항목: `{"query", "doc_ids": [...], "evidence", "evidences": [...]?, "answerable": true, "type"}` — 여러 문서 질문은 `evidences` 에 근거를 모두, 답 없는 질문은 `"answerable": false` 와 빈 `doc_ids`. LLM 생성(`/eval-sets/generate`)의 `styles` 에 `condition` · `long_situation` · `multi` · `unanswerable`, 수는 `n_multi` · `n_unanswerable`.

## 답변 근거 검증 보정

> 라벨은 두 가지 — `label`(근거 일치) · `relevant`(질문 관련성) — 을 따로 받습니다(둘 중 하나는 필수). `/agreement` 는 근거 일치 방식별 일치도와 함께 `relevance` · `relevance_current` · `relevance_auc` · `relevance_sweep`(질문-문장 유사도 기준 탐색)을 돌려줍니다. 답변 검증 결과(`verify`)의 문장에는 `relevance` · `off_topic`, 전체에는 `relevant_ratio` · `off_topic` 이 붙습니다(`ANSWER_RELEVANCE`).

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/verify/settings` | 현재 검증 방식 · 모델 · 문턱 |
| POST | `/api/verify/sample` | 판정할 문장 만들기 작업 `{"eval_set_id", "config", "n_questions", "llm_judge"}` → 문장 · 인용 근거 · 자동 점수(lexical · semantic · llm) |
| GET / POST / DELETE | `/api/verify/labels` · `/api/verify/labels/{id}` | 사람 판정 라벨 목록 / 저장 `{"collection_id", "items": [{"question", "sentence", "sources", "label", "scores"}]}` / 삭제 |
| GET | `/api/verify/agreement` | 방식별 일치도(정확도 · 정밀도 · 재현율 · F1 · 카파), 의미 문턱 탐색 결과 |

## 도메인 · 학습 라우터

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/agent/run` | `agent.lookup: true` 면 법령 조문 · 판례 번호 조회 도구 + 답변 번호 검사(`citations`) |
| POST | `/api/collections/{id}/answer` | `images: true, max_images: 3` 근거 중 이미지 · 장면을 그림으로 첨부(비전 LLM). verify 이벤트에 `citations`(번호가 나온 답변만) |
| POST | `/api/routing/learned` | `{"run_id", "model_id", "margin": 0, "c": 1.0, "threshold": 0.5, "save": true}` → 작업. 라우팅 평가 기록으로 학습 라우터 학습 · 교차검증 비교 |
| GET | `/api/routing/learned` | 저장된 학습 라우터. 연결 실행 `routing: {"router": "learned", "learned_id"}` |
