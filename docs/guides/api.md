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
| POST | `/api/collections/{id}/answer` | NDJSON 스트림: `search` → `delta`(여러 번) → `verify` → `guard`(입력 · 근거 · 출력 검사 결과) → `judge`(선택) → `done`(`trace_id` 포함 — 피드백에 씀), 오류는 `error`. 본문 `{"question", "config": SearchConfig, "context_top", "max_context_chars", "max_tokens", "temperature", "judge", "guard_mode"?: "off"·"mask"·"enforce", "provider"?, "model"?}`. mask 이상이면 `delta` 는 문장 단위로 모아 개인정보를 가린 글 |
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

## 사용자 · 검색 제한 (공통)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/me` | 지금 사용자 `{"name", "groups", "role", "auth"}` (토큰 없이 쓰면 `local` · 모든 그룹 · 관리자) |

`SearchConfig` 에 `filters: {"doc_type": [], "dept": [], "product_model": [], "date_from", "date_to", "latest_only"}`(문서 메타 필터) · `acl_groups`(이 그룹 권한으로 검색 — 모든 문서를 보는 사용자만, 다른 사용자는 자기 그룹으로 덮어씀)를 넣을 수 있습니다. 허용 문서가 0개면 결과도 0개이고 응답에 `restricted` 가 붙습니다.

## 문서 처리 (`/api/docintel`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/docintel/sources` | 폴더 수집 소스 목록(`?collection_id=`) / 추가 `{"collection_id", "path", "pattern": "*", "interval_min": 0}` — `INGEST_ROOTS`(기본 `data/inbox`) 밖 경로는 400 |
| DELETE | `/api/docintel/sources/{id}` | 소스 삭제(문서는 그대로) |
| POST | `/api/docintel/sources/{id}/sync` | 동기화 작업 `{"refresh": true}` → 새 · 바뀜 · 지움 · 그대로 + 청크 세트 증분 갱신 결과. 이미 도는 중이면 409 |
| GET | `/api/docintel/collections/{id}/parsing` · `/api/docintel/documents/{id}/parsing` | 파싱 점검(깨진 글자 비율 · 빈 쪽 `empty_pages` · OCR 했지만 글이 적은 쪽 `ocr_sparse_pages`) |
| POST | `/api/docintel/documents/{id}/ocr` | OCR 작업(PDF, 비전 LLM) `{"pages": [], "provider"?, "model"?}` — 빈 쪽은 채우고, 글이 있는 쪽은 덮어쓰지 않고 글자 정확도만 잼 |
| POST | `/api/docintel/documents/{id}/layout` | 표 · 그림 추출 작업 `{"figures": true}` — 표는 마크다운으로 페이지 글에, 그림은 미디어 청크로 |
| GET | `/api/docintel/documents/{id}/tables` | 추출한 표 · 그림 목록 |
| GET | `/api/docintel/documents/{id}/figures/{n}` | 뽑은 그림 n 번째(0부터) JPEG — 색인 전에 잘린 모양 확인용 |
| GET / POST | `/api/docintel/collections/{id}/clean` · `…/clean/apply` | 머리말 · 꼬리말 · 거의 같은 문서 · 판 묶음 분석(`?threshold=0.85`) / 적용 `{"boilerplate", "versions", "threshold"}` |
| GET | `/api/docintel/chunk-sets/{id}/quality` | 청크 품질(길이 분포 · 짧은 · 긴 · 끊긴 청크) |
| GET | `/api/docintel/chunk-sets/{id}/preservation?eval_set_id=` | 근거 보존율(근거 문장이 한 청크에 온전히 들어간 비율) |
| GET | `/api/docintel/collections/{id}/meta` | 문서별 메타 · 모음(facets) |
| PATCH | `/api/docintel/documents/{id}/meta` | 메타 고치기 `{"values": {"doc_type", "dept", "product_model", "date", "acl", "superseded", …}}` |
| GET | `/api/docintel/collections/{id}/status` | 청크 세트별 증분 갱신 계획(추가 · 변경 · 삭제 문서) |
| POST | `/api/docintel/chunk-sets/{id}/refresh` | 증분 갱신 작업: 바뀐 문서만 다시 청크 · 임베딩(인덱스 모두) |

## 보안 · 가드레일 (`/api/guardrails`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/guardrails/check-input` | `{"text"}` → 인젝션 의심 여부 · 걸린 규칙 |
| POST | `/api/guardrails/pii/scan` | `{"text"}` → 개인정보 위치 · 종류별 수 · 가린 글 |
| POST | `/api/guardrails/check-output` | `{"text", "domain": "general"·"legal"·"medical"·"support"}` → 위반 · 판정(pass · fix · block) · 고친 글 |
| GET | `/api/guardrails/policies` | 분야별 정책 규칙 · 개인정보 종류 · 인젝션 규칙 · 지금 `GUARD_MODE` |
| GET / POST | `/api/guardrails/pii/collections/{id}` · `…/mask` | 문서별 개인정보 수 / 문서 글 가리기(원본 파일은 남음, 바뀐 문서로 표시) |
| GET | `/api/guardrails/acl/collections/{id}` | 문서별 권한 그룹 |
| POST | `/api/guardrails/acl/leak-test` | 권한 누출 시험(관리자) `{"config", "groups", "queries" 또는 "eval_set_id", "max_queries"}` |
| GET | `/api/guardrails/audit` · `/audit/export.csv` | 감사 로그 조회(관리자, `?user=&kind=&status=&document_id=&date_from=&date_to=&limit=`) · CSV(같은 거르기). 행마다 `n_sources` · `source_files`(근거 문서 이름 최대 3개) |
| GET | `/api/guardrails/audit/integrity` | 해시 체인 무결성 검사 → 처음 깨진 기록 |
| POST | `/api/guardrails/audit/purge?confirm=true` | 보관 기간이 지난 기록 지우기 |
| POST | `/api/guardrails/license` | 라이선스 점검 `{"collection_id", "index_id", "reranker_id", "llm_models"}` |
| GET | `/api/guardrails/redteam/preset` | 공격 세트(37개) · 공격 재료 문서 |
| POST | `/api/guardrails/redteam` | 레드팀 작업 `{"mode": "off"·"mask"·"enforce", "types": [], "provider"?, "model"?}` → 유형별 공격 성공률 · 정상 통과율 · 문항별 결과 |
| GET | `/api/guardrails/redteam/runs` · `/runs/{id}` | 실행 기록 |

## 평가 · 관측 (`/api/evalops`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/evalops/sets` · `/sets/{id}` | 평가 세트(버전 · 검토 상태 · 회귀 지정 · 기준선 · 변경 이력) |
| POST | `/api/evalops/sets/{id}/review` | 문항 검토 `{"item_id", "status": "pending"·"ok"·"excluded", "note"}` (버전 +1) |
| POST | `/api/evalops/sets/{id}/regression` | 회귀 세트 지정 `{"on": true}` |
| POST | `/api/evalops/sets/{id}/baseline` | 기준선 만들기 작업 `{"config": SearchConfig, "label"}` |
| POST | `/api/evalops/regression/run` | 회귀 실행 작업 `{"set_ids": [] (비우면 회귀 세트 모두), "config"?: 바꾼 설정, "update_baseline": false}` → 세트별 기준선 대비 짝지은 차이 · 경보 · 유형별 · 가장 나빠진 질문 |
| GET | `/api/evalops/regression/runs` | 회귀 실행 기록 |
| GET | `/api/evalops/traces` · `/traces/{id}` | 요청 기록(`?days=&kind=&flag=느림·실패·차단·근거 약함·관련 없음·거절·싫어요&q=`) / 상세(단계 · 근거 · 검증 · 검사) |
| GET | `/api/evalops/cost` | 대시보드: 전체 · 날짜 · 경로 · 모델 · 종류별 p50 · p95 지연 · 토큰 · 비용, 단계별 시간 |
| POST | `/api/evalops/traces/{id}/feedback` | `{"rating": 1·0·-1, "reason", "note"}` |
| GET | `/api/evalops/feedback` | 피드백 요약 · 자동 판정과 일치율 |
| POST | `/api/evalops/traces/to-eval-set` | `{"trace_ids"}` → 평가 세트 후보로 |
| POST | `/api/evalops/questions/to-eval-set` | `{"collection_id", "questions", "source": "drift"}` → 질문만(정답 문서 없이 검토 전) 평가 세트 후보로, 같은 질문은 한 번만 |
| POST | `/api/evalops/drift` | 드리프트 작업 `{"collection_id", "recent_days", "base_days", "eval_set_id"?, "recent_questions"?, "novel_sim": 0.6}` |
| GET / POST | `/api/evalops/experiments` | A/B 실험 목록 / 만들기 `{"name", "collection_id", "a": ArmConfig, "b": ArmConfig, "split": 0.5}` (`ArmConfig`: `label · config · context_top · max_tokens · compress_keep · provider · model`) |
| GET | `/api/evalops/experiments/{id}` | 실험 보고: `arms`(팔별 지표) · `arm_config`(팔 설정) · `diff`(B − A, 95% 구간) · `verdict` |
| POST | `/api/evalops/experiments/{id}/ask` · `/replay` · `/stop` | 질문 하나(배정 키로 팔 고정) / 평가 세트 질문 재생 작업 `{"eval_set_id", "max_queries", "seed"}` / 멈춤 |
| GET | `/api/evalops/loop` | 실패 유형별 기록(검색 실패 · 인용 · 질문과 다름 · 과잉 거절 · 정책) |
| POST | `/api/evalops/loop/send` | `{"category", "days", "dest": "eval_set"·"gap_csv"}` |
| GET | `/api/evalops/watch` | 정기 점검(레드팀 · 드리프트 · 회귀)의 주기 · 마지막 · 다음 실행과 최근 경보(`?days=30`), 웹훅 설정 여부 |
| POST | `/api/evalops/watch/{kind}/run` | 지금 한 번 점검(`redteam` · `drift` · `regression`) — 작업, 끝나면 그 실행의 경보를 `ALERT_WEBHOOK` 으로 |

## 대화 · 메모리 (`/api/conversation`)

대화 기록은 화면이 들고 와서 매 턴 보냅니다(서버에 대화 표 없음). 메모리는 기록에서 매번 다시 계산합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/conversation/turn` | 한 턴 `{"collection_id", "question", "history": [{"role": "user"·"assistant", "text"}], "config"?: SearchConfig, "method": "auto"·"none"·"history"·"rule"·"llm", "clarify": true, "asked": [], "profile_key"?, "session_id"?, "guard_mode"?, "keep_turns": 4, "provider"?, "model"?}` → `reply` · `answered` · `rewrite`(query · method · changed · depends · reason) · `clarify`(ask · reason · prompt) · `memory`(product_model · codes · symptoms · tried · topic · turns) · `history_prompt` · `sources` · `verify` · `guard` · `trace_id` · `profile` |
| GET | `/api/conversation/collections/{id}/vocab` | 메모리가 알아보는 제품 모델(문서 메타) · 오류 코드(문서 제목 줄) · 모델별 코드 |
| POST | `/api/conversation/handoff` | 인계 요약 `{"collection_id", "history"}` → 제품 · 코드 · 증상 · 안내한 조치 · 처음과 마지막 질문 |
| GET / DELETE | `/api/conversation/profiles/{key}` | 고객 프로필(보유 제품 · 지난 문의) / 지우기 |
| POST | `/api/conversation/profiles/{key}/remember` | `{"collection_id", "history", "summary"?}` → 대화의 제품 · 문의 요약(가린 글)을 프로필에 |
| GET | `/api/conversation/eval/preset` | 대화 평가 세트(후속 질문 24 · 되묻기 11)와 쓰는 컬렉션 |
| POST | `/api/conversation/eval` | 실측 작업 `{"methods": ["none", "history", "rule", "llm"], "domains": ["as", "legal"], "top_k": 10}` → 분야 · 방법별 Hit@1 · Hit@3 · MRR · 풀어 쓰기 시간, 대화별 순위, 되묻기 정확도 · 메모리 정확도 |
| GET | `/api/conversation/eval/runs` · `/eval/runs/{id}` | 실측 기록 |

## 지식 그래프 · GraphRAG (`/api/kg`)

원본 그래프는 앱 DB(내장 그래프 저장소), Cypher 는 엔진(Neo4j · FalkorDB)으로 옮겨서 실행합니다. `engine` 을 비우면 `GRAPH_ENGINE`(없으면 연결이 설정된 쪽, 둘 다면 Neo4j).

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/kg/ontology` | 온톨로지(클래스 · 관계 · 규칙)와 Text2Cypher 스키마 설명 |
| POST | `/api/kg/build` | 구축 작업(관리자) `{"collection_id", "graph": "legal", "issue_limit": 0·N·-1, "provider"?, "model"?}` → 노드 · 관계 수, 걸러 낸 것, 쟁점 합치기 기록 |
| GET | `/api/kg/builds` · `/api/kg/graphs` · `/api/kg/graphs/{g}/stats` | 구축 기록 · 그래프 목록 · 통계(클래스 · 관계별 수, 만든 컬렉션) |
| GET | `/api/kg/graphs/{g}/nodes` · `/nodes/{id}` | 노드 찾기(`?q=&label=`) · 노드와 이웃(`?hops=1·2`) |
| POST | `/api/kg/graphs/{g}/expand` | `{"question", "config"?, "max_docs": 3}` → 검색 결과 + 그래프로 넓힌 문서(연결 수 · 무엇으로 이어졌나) · 관계 요약 |
| POST | `/api/kg/graphs/{g}/answer` | GraphRAG 답변 `{"question", "provider"?, "model"?}` — 검색 + 넓힌 문서를 근거로, 관계 요약을 시스템 프롬프트에 |
| POST / GET | `/api/kg/graphs/{g}/communities` | 커뮤니티 요약 작업(관리자) `{"top": 12, "min_size": 4}` / 저장된 요약 |
| POST | `/api/kg/graphs/{g}/global` | 전체 질문 `{"question"}` → 가까운 커뮤니티 요약 4개로 답(묶음 인용 [C1]) |
| GET | `/api/kg/engines` | 엔진별 연결 상태 `{"default", "engines": [{"engine", "label", "ok", "url", "detail"?}]}` |
| POST | `/api/kg/graphs/{g}/sync?engine=neo4j·falkordb` | 그래프를 엔진으로 옮기기(관리자, 그 엔진의 기존 그래프는 지움) → 노드 · 관계 수 · 걸린 초 |
| POST | `/api/kg/cypher` | 읽기 Cypher 실행 `{"query", "engine"?}` — 쓰기 쿼리는 403(Neo4j 는 EXPLAIN 쿼리 종류, FalkorDB 는 GRAPH.RO_QUERY 로 차단) |
| POST | `/api/kg/text2cypher` | `{"question", "engine"?, "provider"?, "model"?}` → Cypher · 결과 · 시도(오류 · 빈 결과면 다시 씀) |
| GET / POST | `/api/kg/cq` · `/api/kg/cq/eval` | 역량 질문 15개 / Text2Cypher 정확도 작업 `{"engine"?, "ids"?}` → 정확 일치 · 같은 답 · 겹침 · 종류별(엔진에 연결이 안 되면 400) |
| POST | `/api/kg/graphs/{g}/hybrid-eval` | `{"eval_set_id", "k": 10, "add": 3, "only_multi"}` → 벡터 상위 k vs 벡터 + 그래프 확장의 hit · all · MRR |
| GET | `/api/kg/runs` · `/runs/{id}` | KG 실행 기록(구축 · 커뮤니티 · 역량 질문 · 하이브리드) |

## 규제 대응 · 컴플라이언스 (`/api/compliance`)

기술 설계를 위한 정리이며 법률 자문이 아닙니다. 법령 판 받기 · 개정 감시는 `LAW_API_OC`(국가법령정보 공동활용) 가 필요합니다. 사람 판단(확정 · 승인 · 처리 · 등록 · 파기)은 관리자만.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/compliance/catalog` | 규제 목록 · 서비스 기능 · 특성 · 적용 규칙 · 통제 · 등급 기준표, 법령 API 사용 여부 · AI 응답 고지 문구 |
| POST | `/api/compliance/corpus/{cid}/import` | 법령 판 받기 작업(관리자) `{"laws"?: [...], "date"?: "YYYYMMDD"}` — 그날 시행 중이던 판(비우면 현행), 이미 있는 법령은 건너뜀 |
| GET | `/api/compliance/corpus/{cid}/articles` · `/revisions` | 조항 목록(`?q=`) · 개정 감시(현행 · 시행예정 판과 조항 비교 → 바뀜 · 새로 생김 · 없어짐, 그래프가 있으면 영향받는 통제 · 기능) |
| GET | `/api/compliance/scope/{profile}` | 기능의 적용 조항 · 의무 요지 · 통제 · 원문(`?collection_id=`), 규칙에 없는 검색 후보 |
| POST | `/api/compliance/scope/eval` | 의무 질문 22개 검색 실측 작업 `{"collection_id", "k": 10, "mode": "default·bm25"}` → 조항 단위 hit@k · MRR |
| GET / POST | `/api/compliance/risk` · `/risk/{profile}` | 기능별 제안 등급 · 기록 · 없는 통제 / 초안 저장 `{"values", "grade"?, "reason"}`(제안과 다르면 이유 필수) |
| POST | `/api/compliance/records/{id}/confirm` | 위험 등급 확정 · 영향 평가 승인(관리자) |
| GET / POST | `/api/compliance/data` · `/data/register` | 처리 목록(컬렉션 · 요청 기록 · 프로필 · AS 대화) / 처리 근거 등록 `{"subject": "collection:3·log:traces", "purpose", "basis", "retention_days", "owner"}` |
| POST | `/api/compliance/data/purge?confirm=true` | 보관 기한 지난 요청 기록 · 프로필 · 컬렉션 문서 파기(관리자, confirm 없으면 400) |
| GET | `/api/compliance/decisions` · `/decisions/{trace_id}` | 최근 서비스 답 · 결정 기록(근거 청크 · 검증 · 조치 · 모델 · 단계 · 행 무결성 · 검토 요청), 남의 기록은 관리자만 |
| POST / GET | `/api/compliance/reviews` · `/reviews/{id}/resolve` | 사람 검토 요청 `{"trace_id", "reason": "wrong·source·human·other", "note"}`(누구나) / 목록(관리자) / 처리 `{"outcome": "upheld·corrected·handoff", "note"}` |
| GET / POST | `/api/compliance/impact/draft` · `/impact` | 측정 기록으로 영향 평가 초안(`?collection_id=`) · 약한 집단 / 저장 `{"profile", "collection_id", "affected", "mitigations", "decision"}`(증적은 서버가 다시 모음) |
| POST / GET | `/api/compliance/graph/build` · `/graph` · `/graph/impact` | 조항-통제 그래프 만들기(관리자) `{"collection_id"}` · 통제별 근거 조항 · 기능 · 조항 → 영향 `{"keys": [...]}` |
| POST / GET | `/api/compliance/audit/run` · `/audit/runs` · `/audit/runs/{id}` | 통제 감사(관리자, 통제 15개 증적 · 통과 · 실패 · 부분 · 없음 · 수동) · 기록 |

서비스 답변(`/api/rag/answer` 스트림의 `done`, AS 상담 · 대화 · GraphRAG 답)에는 AI 응답 고지 `notice` 가 함께 옵니다.

## 에이전트 상호운용 (`/mcp` · `/a2a` · `/api/interop`)

표준 끝점은 `/api` 밖입니다. 인증은 다른 API 와 같습니다(API_TOKEN 이 있으면 `Authorization: Bearer`).

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/mcp` | MCP 서버(Streamable HTTP · JSON-RPC 2.0, 규격 2025-06-18): `initialize`(응답 머리 `Mcp-Session-Id`) · `ping` · `tools/list`(역할이 허용한 도구만) · `tools/call` → `content` · `structuredContent` · `isError`. 알림은 202, 묶음 요청은 오류 |
| GET | `/mcp` | 405 (서버가 먼저 보내는 SSE 스트림 없음) |
| GET | `/.well-known/agent-card.json` | A2A 에이전트 카드(공개) — 기술 `document_qa` · `compliance_scope`, 인증 방식 |
| POST | `/a2a` | A2A JSON-RPC: `message/send` `{"message": {"messageId", "parts": [{"kind": "text", "text"}]}, "metadata": {"skill", "collection_id"?}, "configuration": {"blocking": true}}` → 작업(같은 messageId 면 같은 작업) · `tasks/get` · `tasks/cancel` `{"id"}` |
| GET | `/api/interop/tools` | 도구 · 범위 · 지금 역할에서 허용 여부 · 역할별 정책 · 샌드박스(Docker 여부) · MCP 주소 |
| POST | `/api/interop/tools/{name}/call` | 화면에서 도구 호출 `{"arguments", "trace_key"?}` (권한 · 상한 · 감사가 MCP 와 같음) |
| POST | `/api/interop/sandbox` | 코드 실행(관리자) `{"code"}` → stdout · stderr · 종료 코드 · 격리 방식 |
| GET | `/api/interop/servers` | 설정의 외부 MCP 서버 · A2A 상대(토큰 감춤)와 이 앱 주소 |
| POST | `/api/interop/remote/tools` · `/remote/call` | 외부 MCP 서버의 도구 목록(설명 속 지시 표시) · 호출 `{"url", "token"?, "name", "arguments"}` → 지시 문장을 뺀 결과 |
| POST | `/api/interop/a2a/card` · `/a2a/delegate` | 상대 에이전트 카드 · 맡기기 작업 `{"url", "skill", "text", "metadata", "verify_collection_id"?}` → 결과 · 검증 · 받아들임 |
| GET | `/api/interop/tasks` · `/calls` · `/trace/{key}` · `/limits` | 작업(`?direction=in·out`) · 호출 기록(`?channel=&status=`) · 추적 id 로 이은 호출 · 작업 · 상한과 세션 사용량 |

## 장기 실행 업무 (`/api/longrun`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/longrun/catalog` | 행동(되돌릴 수 있나 · 보상 · 대체 · LLM) · 템플릿 · 기본 범위 |
| POST | `/api/longrun/plan` | 계획 보기 `{"planner": "template·llm", "template", "goal", "params": {"days", "collection_id"}, "scope"}` → 검사를 거친 계획 · 고친 것 |
| POST | `/api/longrun/runs` | 업무 만들기 · 시작 `{… , "plan"?: 미리 본 계획, "start": true}` → 업무 · 단계 · 작업 |
| GET | `/api/longrun/runs` · `/runs/{id}` | 업무 목록 · 단계별 체크포인트 · 기록 · 완료 판정 |
| POST | `/api/longrun/runs/{id}/go` | 이어 하기(마지막 체크포인트 다음부터, 멈춘 업무는 실패 · 반려 단계부터) |
| POST | `/api/longrun/runs/{id}/steps/{idx}/approve` | 승인 · 반려(관리자) `{"ok", "note"}` — 승인하면 이어 감 |
| POST | `/api/longrun/runs/{id}/rollback?confirm=true` | 되돌리기(관리자) — 보상 작업을 나중 단계부터 |
| POST | `/api/longrun/runs/{id}/extend` · `/cancel` | 범위 늘리기(관리자) `{"max_steps", "max_seconds", "max_cost"}` · 취소 |
| GET | `/api/longrun/approvals` | 승인을 기다리는 단계(초안 · 완료 조건 검사 포함) |

## 멀티에이전트 · 멀티모달 (`/api/multiagent`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/multiagent/run` | 협업 작업 `{"collection_id", "question", "analyze": "auto·on·off", "rounds": 3, "revisions": 2, "vision": true, "tts": false, "provider"?, "model"?}` → 계획 · 흐름(events) · 답 · 결정 · 검증 · 근거 · 분석 · 출력(차트 · 그림 · 음성) · 요청 기록 번호 |
| GET | `/api/multiagent/runs` · `/runs/{id}` | 실행 기록 |
| GET | `/api/multiagent/audio/{name}` | 합성한 음성(mp3) |
| POST | `/api/multiagent/image-search` | 사진으로 찾기(multipart: `collection_id`, `image`, `question`?, `top_k`) — 멀티모달 인덱스가 필요 |

## 데이터 플라이휠 (`/api/flywheel`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/flywheel/triage` | 실패 유형 · 날짜별 추이 · 예 · 처방(싼 것부터) `?days=&collection_id=` |
| GET | `/api/flywheel/queue` | 검토 순서(우선순위 + 무작위 표본) `?n=&collection_id=` |
| POST | `/api/flywheel/reviews` | 판정 · 분배 `{"trace_id", "label": "correct·wrong", "category", "destination": "eval·train·ignore", "gold_doc_ids", "corrected"}` → 보낸 곳(누수면 막힘과 이유) |
| GET | `/api/flywheel/reviews/stats` | 검토 수 · 틀림 비율 · 분배 · 학습 데이터 줄 수 |
| GET / POST | `/api/flywheel/versions` | 버전 목록 / 만들기 `{"name", "collection_id", "search"?, "guard_mode"?, "llm_model"?}` |
| POST | `/api/flywheel/versions/{id}/gate` | 게이트 작업 `{"redteam": true}` — 회귀 세트 짝 비교 + 레드팀 |
| POST | `/api/flywheel/versions/{id}/start` · `/step` · `/rollback` | 배포 시작(5%) · 단계(건강하면 다음 비율, 100% 다음은 승격, 나빠졌으면 롤백) · 롤백(관리자) |
| GET | `/api/flywheel/versions/{id}/monitor` | 후보 팔 vs 나머지 지표 · 판단 |

## 엔터프라이즈 플랫폼 (`/api/platform`)

모든 요청은 속도 제한(`RATE_LIMIT_PER_MIN`, 넘으면 429 · `Retry-After`)을 거칩니다. 설정을 바꾸는 요청은 관리자만.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/platform/gateway` | 사용량(테넌트 · 사용자 · 경로 묶음) · 상한 · 거절 수 |
| GET / POST | `/api/platform/tenants` | 컬렉션 ↔ 테넌트 · 사용자의 테넌트 / 지정 `{"collection_id", "tenant"}`(비우면 공용) |
| POST | `/api/platform/tenants/leak-test` | 누출 시험 `{"queries"}` → 테넌트마다 남의 컬렉션 검색 결과 수 |
| GET / POST | `/api/platform/prompts` · `/prompts/{name}/activate` | 프롬프트 버전 · 코드 기본값 / 추가 `{"name", "text", "note", "activate"}` / 활성 `{"version"}`(비우면 코드 기본값) |
| GET / POST | `/api/platform/flags` · `/flags/{key}` · `/flags/{key}/eval` | 플래그 · 기본값 · 규칙 · 기록 / 바꾸기 `{"default", "rules": [{"tenant"·"group"·"user"·"pct", "value"}]}` / 이 사용자면 어떤 값 |
| GET | `/api/platform/ops` | 앱 버전 · 마이그레이션 · 벡터 DB · 그래프 엔진 · LLM 대체 사슬 · 차단기 |
| POST | `/api/platform/ops/llm-check` | 대체 사슬의 모델마다 짧게 불러 보기(관리자) |
| GET / POST | `/api/platform/chargeback` · `/budgets` | 이번 달 테넌트 · 기능별 요청 · 토큰 · 비용 · 예산 / 예산 `{"tenant", "monthly_usd", "alert_pct"}` |

## 서빙 · 추론 최적화 (`/api/serving`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/serving/resources` | 캐시 · 올라간 모델 · 장치 · 메모리 · LLM 경로 · GGUF 파일 · llama-server 유무 |
| POST | `/api/serving/load` | 동시 부하 작업 `{"levels": [1, 2, 4], "max_tokens", "prompts"?}` → 동시 수별 요청/초 · 토큰/초 · p50 · p95 |
| POST | `/api/serving/decode` | 디코딩 설정 비교 작업(관리자) `{"model": GGUF 이름, "variants": [{"label", "kv_k", "kv_v", "draft"?}], "eval_set_id", "max_queries"}` → 설정별 품질 · 기준 대비 · 생성 속도 · KV 캐시 · RSS |
| POST | `/api/serving/budget` | 예산 `{"max_ms", "max_cost", "min_quality", "days"}` → 평가 세트별 목표 안 최고 품질 · 파레토 앞줄 · 운영 경로별 p95 · 비용 |

## 후학습 (`/api/posttrain`)

학습 · 병합 · 변환 · 데이터 만들기는 관리자만.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/posttrain/overview` | 기본 모델 · 장치 · 증류 파일 · 데이터 · 학습한 모델 · 변환 스크립트 유무 |
| POST | `/api/posttrain/datasets` | 데이터 만들기 `{"name", "kind": "sft·dpo", "distill": [...], "flywheel", "refusal_sets", "exclude_sets", "collection_id"?}` → 단계별 남은 건수 |
| POST | `/api/posttrain/train` | LoRA 학습 작업 `{"name", "dataset", "method": "sft·dpo", "init_adapter_id"?, "max_steps", "epochs", "max_len", "r", "beta"}` |
| POST | `/api/posttrain/merge` | 병합 작업 `{"name", "adapters": [...], "weights"?, "method": "linear·ties·cat", "into_base"}` |
| DELETE | `/api/posttrain/models/{id}` | 학습한 모델 지우기 |
| POST | `/api/posttrain/v1/chat/completions` | OpenAI 호환(비스트리밍) — `model`: `pt-base` · `pt-<번호>` |
| POST | `/api/posttrain/evaluate` | 학습 전후 작업 `{"models": [...], "eval_set_id", "max_queries", "redteam"}` → 품질(7b 채점) · 기준 대비 · 레드팀 |
| POST | `/api/posttrain/export` | GGUF 변환 · 양자화 작업 `{"model_id": 병합 모델, "quant"}` (스크립트가 없으면 명령) |

## 옴니채널 (`/api/omni`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/omni/channels` | 채널 7종(이름 · 동기 여부 · 지연 예산 · 주소)과 채널별 형식 규칙 |
| POST | `/api/omni/webhook/{channel}` | 채널 웹훅 그대로 → 봉투 → 고객 · 세션 → 받기(멱등) → 장면 → 답 → 형식 → 전달. 같은 외부 id 는 `duplicate: true` 와 처음 답 |
| POST | `/api/omni/send` | 화면의 채널 흉내 `{"channel", "address", "text", "external_id", "image_b64", "verified_phone", "link_session", "collection_id", "provider", "model"}` → 웹훅과 같은 결과(`reply` · `fuse` · `same_session` · `seconds`) |
| GET | `/api/omni/sessions` · `/api/omni/sessions/{sid}` | 열린 세션 목록 · 세션(메시지 · 채널 주소 · 대화 메모리 · 장면 색인 · 넘김 · 대기열 통계) |
| DELETE | `/api/omni/sessions/{sid}` | 세션 · 메시지 · 키프레임 삭제(고객의 마지막 세션이면 채널 주소 연결도) |
| POST | `/api/omni/sessions/{sid}/frame` | 영상 통화 프레임 하나(multipart `file`) → 장면이 바뀌었을 때만 비전 읽기 · 색인 |
| POST | `/api/omni/sessions/{sid}/video` | 녹화 영상 작업(multipart `file`, `interval`) → 키프레임만 읽어 색인 |
| GET | `/api/omni/frames/{sid}/{fid}` | 키프레임 사진(서버 메모리에만 잠시) |
| POST | `/api/omni/sessions/{sid}/handoff` | 넘김 요약 `{"to_channel"}` → 요약 · 사실 · 미해결 질문 · 다음 할 일 · 새 채널의 첫 말 |
| POST | `/api/omni/render` | 같은 답을 채널마다 `{"text", "channels"}` → 글 · 버튼 · 읽는 글 · 가림 · 규칙 위반 |
| POST | `/api/omni/stabilize` | 인식 확정 `{"text"\|"hypotheses", "agree", "noise"}` → 가설마다 확정 · 잠정, 확정 오류 · 깜빡임 · 지연 |
| POST | `/api/omni/keyframes` | 키프레임 채점 `{"codes", "scene_seconds", "threshold", "min_gap"}` → 놓친 장면 · 더 남긴 프레임 · 절약률 |
| POST | `/api/omni/drill` | 대기열 훈련 `{"n", "dup_rate", "shuffle", "fail_rate"}` → 한 번만 처리 · 답, 순서, 재시도 · 실패 · 늦게 도착 |
| GET | `/api/omni/scenarios` | 평가 시나리오 목록 |
| POST | `/api/omni/eval` | 옴니 평가 작업 `{"collection_id", "scenarios", "provider", "model"}` → 표기 · 넘김 · 같은 세션 · 중복 · 형식 · 지연 · 일관성, 채널별 지연 |

## 프롬프트 · KV 캐시 압축 (`/api/compress`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/compress/options` | 방법 · KV 정책 이름 · 압축 모델 |
| POST | `/api/compress/preview` | 압축 미리 보기 `{"text", "question", "method": "token"\|"query"\|"lexical"\|"random", "ratio"}` → 압축 글 · 남은 비율 · 숫자 · 조항 보존 · 문장 대조 점수 |
| POST | `/api/compress/eval` | 압축 평가 작업 `{"eval_set_id", "methods", "ratios", "max_queries", "provider", "model"}` → 방법 × 비율 정답률 · 남은 글자 · 보존 · 시간 |
| POST | `/api/compress/kv` | KV 실험 작업 `{"eval_set_id", "policies", "keeps", "kv_bits", "max_queries", "max_new"}` → 정책 × 비율 · 비트별 다음 토큰 일치 · KL · 갈라진 답 |

## 장기 메모리 (`/api/memory`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/memory/owners` · `/items` | 기억의 주인 목록 · key 목록 / 한 고객의 기억 `?owner=&history=`(시점 이력 · 연결 · 핵심 기억) |
| POST | `/api/memory/remember` | 기억하기 `{"owner", "text", "at", "extractor": "rule"\|"llm"\|"both", "model_id", "source"}` → 뽑은 기억 · 갱신 판단(추가 · 고치기 · 그대로) |
| POST | `/api/memory/recall` | 꺼내기 `{"owner", "question", "k", "w_sim", "w_rec", "w_imp"}` → 점수 · 항목별 점수 · 핵심 기억 · 맥락 글 · 계층별 글자 수 |
| POST | `/api/memory/consolidate` | 통합 · 망각 `{"owner", "min_events", "older_days", "forget_below", "dry_run"}` → 요약 · 보관 · 잊음 |
| DELETE | `/api/memory/owners/{owner}` | 한 고객의 기억 · 연결 지우기 |
| POST | `/api/memory/eval` | 여러 세션 평가 작업 `{"personas", "methods", "extractor", "k"}` → 방식별 · 유형별 정답률 · 맥락 글자 |

## 해석 가능성 · 모델 내부 (`/api/interp`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/interp/overview` | 안을 보는 모델 · 저장한 내부 신호 · 번역 쌍 수 |
| POST | `/api/interp/space` | 임베딩 공간 작업 `{"model_ids", "collection_id", "max_chunks"}` → 모델별 이방성 · 유효 차원 · 주성분 · 문서 군집 · 한-영 정렬 |
| POST | `/api/interp/attribution` | 근거 기여 작업 `{"eval_set_id", "max_queries", "k", "max_new"}` → 지우기 기여 · 어텐션 · 인용 · 정답 근거 일치율 |
| POST | `/api/interp/inside` | 내부 신호 작업 `{… "layers", "name"}` → 층별 탐침 · 거절률 · 환각 AUROC(내부 vs 밖), 은닉 상태 저장 |
| POST | `/api/interp/steer` | 조종 작업 `{"name", "layer", "alphas", "max_queries"}` → 세기별 근거 뺌 · 있음 거절률 · 근거율 |
| POST | `/api/interp/sae` | 희소 특징 작업 `{"collection_id", "layer", "max_texts", "mult", "l1", "steps"}` → 설명한 분산 · L0 · 안 켜진 비율 · 특징별 글 조각 |

## 컴퓨터 사용 · 브라우저 에이전트 (`/api/computer-use`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/computer-use/overview` | 과제 · 시험용 사이트 · 허용 도메인 · 최근 실행 |
| POST | `/api/computer-use/perceive` · `/perceive/eval` | 화면 읽기 `{"site", "url", "logged_in"}` → 접근성 트리 · 요소 · 숨은 글 · 인젝션 표시 / 설명으로 요소 찾기 정확도 |
| POST | `/api/computer-use/runs` | 실행 작업 `{"task", "config": {"observe", "isolate", "allowlist", "approval"}, "max_steps", "provider", "model"}` → 걸음 · 최종 상태 · 판정(멈추면 waiting) |
| GET / POST | `/api/computer-use/runs/{id}` · `/runs/{id}/approve` | 실행 기록 / 멈춘 실행 승인 · 거부 `{"approve"}` 후 이어 가기 |
| POST | `/api/computer-use/runs/{id}/replay` | 기록한 행동을 새 사이트에서 재생 → 같은 최종 상태인가 |
| POST | `/api/computer-use/eval` | 과제 × 방어 설정 평가 작업 `{"tasks", "configs", "max_steps"}` → 성공률 · 목표 달성 · 인젝션을 따른 비율 · 걸음 |

## 코딩 에이전트 (`/api/coding`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/coding/overview` | 깬 코드 과제 목록 · 기본 대상 테스트 · 색인한 함수 수 |
| POST | `/api/coding/refresh` | 작업 공간 원본을 저장소 지금 상태로 다시(관리자) |
| POST | `/api/coding/search` · `/search/eval` | 코드 검색 `{"query", "method": "bm25"\|"symbol"\|"graph", "k"}` / 깬 코드 과제로 방법별 hit@k · MRR `{"tasks", "k"}` |
| POST / GET | `/api/coding/tasks` · `/tasks/{name}` | 깬 코드 과제 만들기 작업(관리자) `{"name", "tests", "n", "seed"}` → 과제 · 시도 · 살아남은 돌연변이 / 과제 보기 |
| POST | `/api/coding/run` | 에이전트 실행 작업(관리자) `{"tasks", "ids", "max_steps", "llm_review", "provider", "model"}` → 해결률 · 걸음 · 토큰 · diff · 리뷰 지적 |
| POST | `/api/coding/review` · `/review/eval` | diff 검사 `{"diff", "use_llm"}` / 좋은 · 나쁜 diff 로 규칙 · LLM 리뷰 정밀도 · 재현율 |

## 데이터 분석 · Text-to-SQL (`/api/analytics`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST / GET | `/api/analytics/sources` | 분석 자료 만들기 `{"name", "kind": "demo"\|"app", "n", "seed"}`(앱 기록은 이름이 app 으로 시작) / 목록(표별 행 수) |
| GET | `/api/analytics/sources/{name}/schema` · `/semantic` | 스키마 카드(설명 · 예시 값 · 개인정보 열) / 의미 계층 지표 · 차원 · 필터 |
| POST | `/api/analytics/link` | 스키마 연결 `{"source", "question"}` → 표 · 열 · 점수 |
| POST | `/api/analytics/ask` | 묻기 `{"source", "question", "mode": "sql"\|"semantic", "role", "max_tries", "full_schema", "explain", "provider", "model"}` → 시도별 SQL · 결과 · 답 · 숫자 검사 · 막대 |
| POST | `/api/analytics/run` | SQL 직접 실행(같은 가드) `{"source", "sql", "role"}` |
| POST | `/api/analytics/guard/test` | 위험 질의 시험 `{"source"}` → 기대대로 막힘 · 통과 수 |
| POST / GET | `/api/analytics/eval` · `/eval/questions` | 실행 정확도 작업 `{"source", "modes", "max_tries", "ids"}` → 방식별 · 유형별 정답률 · 연결 재현율 / 평가 질문 |

## 컨텍스트 엔지니어링 (`/api/context`)

모든 실험 요청은 `{"eval_set_id", "max_queries", "top_k", "max_chars", "max_tokens", "provider", "model", "seed"}` 를 함께 받습니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/context/options` | 배치 · 압축 방법 · 오염 막는 방법 이름 |
| POST | `/api/context/layout` | 배치 작업 `{… "orders", "needle", "needle_k", "positions"}` → 배치별 · 정답 위치별 정답률 · 입력 토큰 · 시간 |
| POST | `/api/context/long` | 긴 맥락 vs RAG 작업 `{… "limits"}` → RAG · 한도별 통째로의 정답률 · 정답 문서 들어감 |
| POST | `/api/context/cache` | 프롬프트 캐시 작업 `{… "groups", "per_group"}` → 근거 앞 / 질문 앞의 재사용 비율 · 읽기 시간(llama-server) |
| POST | `/api/context/compact` | 기록 압축 작업 `{… "strategies", "steps", "keep", "gold_at"}` → 방법별 정답률 · 맥락 글자 · 시간 |
| GET / POST / DELETE | `/api/context/notes/{session}` | 노트 읽기 `?q=&k=`(질문과 겹치는 노트만) / 쓰기 `{"text", "tags", "source"}` / 지우기 |
| POST | `/api/context/hygiene` | 맥락 오염 작업 `{… "mitigations"}` → 막는 방법별 오염률 · 정답률 |

## 추론 모델 (`/api/reasoning`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/reasoning/overview` | RLVR 과제 목록 · 풀이 저장소(과제 × 모델 × 예산 × 온도, 정답률) · 검증기 |
| POST | `/api/reasoning/budget` | 예산 곡선 작업 `{"tasks", "splits", "max_per_type", "budgets", "provider", "model", "tol"}` → 예산별 정답률 · 생각 토큰 · 시간 · 예산 강제 비율 · 유형별 꺾이는 점 |
| POST | `/api/reasoning/route` | 생각 라우팅 작업 `{… "budget", "router": "rule"\|"llm"}` → 늘 끔 · 늘 켬 · 라우터 · 이상적 정답률 · 토큰 · 시간 |
| POST | `/api/reasoning/sample` | 여러 번 풀기 작업 `{… "budget", "temperature", "n", "verifiers"}` → n 별 다수결 · 검증기 고르기 · pass@n, 검증기 AUROC |
| GET | `/api/reasoning/banks/{key}` | 풀이 보기 `?task_id=&limit=` (생각 · 답 · 토큰 · 맞음) |
| POST | `/api/reasoning/trace` | 생각 과정 검사 `{"tasks", "bank"}` → 표시별 비율 · 표시된 풀이 정답률 |
| POST | `/api/reasoning/distill` | 증류 데이터 `{"tasks", "bank", "name", "include_thinking", "clean_only", "splits"}` → 후학습 SFT 데이터 |

## 실시간 음성 상담 (`/api/voice`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/voice/config` | 턴 관리 문턱 · 지연 예산(단계별) · 인식 엔진 · 합성 · 전사 저장 · 보관 기간 |
| POST / GET / DELETE | `/api/voice/calls` · `/calls/{id}` | 통화 만들기 `{"collection_id", "mode": "auto"\|"assist", "customer", "product_model"}`(AS 상담 기록과 짝) / 목록(보관 기간 지난 기록 지움) · 한 건 / 삭제 |
| POST | `/api/voice/calls/{id}/audio` | 16kHz PCM16 조각(본문) `?speaking=` → 사건 partial(이어질 말) · final(고객 턴 · 감정 · 인식 시간 · 표기 복원) · barge_in |
| POST | `/api/voice/calls/{id}/say` | 글로 말하기 `{"text", "role": "customer"\|"agent"}` |
| POST | `/api/voice/calls/{id}/respond` | NDJSON — 자동 응답: plan · sources · sentence(글 · 읽는 글 · 합성 파일 · 시각) · done(단계별 시간 · 예산 · 검증 · 이관) / 상담원 보조: triage · evidence(근거 · 확인할 질문) · suggestion |
| POST | `/api/voice/calls/{id}/barge` · `/suggestions/{n}/feedback` | 끼어들기 기록 `{"turn", "spoken_chars", "sentence"}` / 추천 채택 `{"action": "adopted"\|"edited"\|"ignored", "text"}` |
| POST | `/api/voice/calls/{id}/end` | 종료 `{"summarize", "ticket", "provider", "model"}` → 양식 요약 · 항목별 전사 일치 · 티켓 |
| POST / GET | `/api/voice/stt/transcribe` · `/stt/sets` · `/stt/eval` | 파일 하나 인식(표기 복원 · 운율) / 음성 평가 세트(파일 + 정답 전사) / 평가 작업 `{"set", "engines", "collection_id"}` → 글자 오류율 · 용어 정확도 · 실시간 계수 |
| POST / GET | `/api/voice/tts/preview` · `/tts/{name}` | 문장 · 읽는 글 · 합성 / 합성 파일(mp3) |
| POST | `/api/voice/emotion/score` · `/emotion/eval` | 불만 점수 · 이관 / 라벨 문장 평가(정밀도 · 재현율) |
| GET | `/api/voice/report` | 통화 기록: 단계별 지연 p50 · p95 · 예산 안 비율 · 끼어들기 · 이관 · 추천 채택 · 요약 검증 · 인식 실시간 계수 |

## 온디바이스 · 엣지 (`/api/edge`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/edge/profiles` · `/overview` | 기기 프로필 · 벡터 정밀도 / 팩 · 기록 상태 수 · GGUF 파일 |
| POST | `/api/edge/recommend` | 조합 추천 `{"profile", "budget_gb", "n_chunks", "ctx"}` → 예산 안 조합(recall × 품질 · 파레토) · 검색만 · 가까운 초과 조합 · LLM 후보 |
| GET / POST / DELETE | `/api/edge/packs` · `/packs/{name}` | 팩 목록 · 인덱스 / 새 판 만들기 작업 `{"name", "index_id", "precision", "product_model", "doc_type", "doc_ids", "since_days", "include_cache"}` / 삭제(관리자) |
| POST | `/api/edge/packs/{name}/search` · `/eval` | 팩으로 검색(자주 묻는 답 포함) / 평가 작업 `{"eval_set_id", "k", "max_queries", "server"}` → 팩 · 서버 hit@k, 범위 안만 |
| GET | `/api/edge/capabilities` | 오프라인 기능 범위 `?pack=&profile=&llm_file=&device_id=` → 기기에서 · 연결될 때 · 안 됨과 이유 |
| POST | `/api/edge/ask` | 기기에서 묻기 흉내 `{"pack", "question", "provider", "model", "device_id", "online", "k", "use_llm"}` → faq · answer · sources · defer(대기열 번호) |
| GET | `/api/edge/packs/{name}/delta` | 판 증분 `?from_version=&to_version=&content=` → 보낼 청크 · 지울 청크 번호 · 크기 · 지문 확인 |
| GET / POST / DELETE | `/api/edge/devices` · `/devices/{id}` | 기기 목록(판 뒤처짐 · 오래 연결 안 됨 · 대기열 · 위반 수) / 등록 · 고치기 / 삭제 |
| POST | `/api/edge/devices/{id}/sync` | 동기화 `{"pack", "apply"}` → 증분 · 기기 상태 · 대기열 수 |
| POST | `/api/edge/privacy/preview` · `/devices/{id}/upload` | 전송 정책 미리 보기 / 올리기 `{"events", "policy", "prepare", "include_queued"}` → 저장 수 · 서버가 찾은 위반 |
| GET / POST | `/api/edge/events` · `/events/process` | 올라온 기록 / 미룬 요청 처리 작업(질문은 서비스 답변, 그 밖은 담당자 확인) |

## RLVR (`/api/rlvr`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/rlvr/overview` | 과제 목록 · 보상 항목 · 학습한 정책(곡선 · 해킹 감시) |
| POST / GET | `/api/rlvr/tasks` · `/tasks/{name}` | 과제 만들기 `{"name", "collection_id", "graph": "legal", "n_per_type"}` → 학습 / 시험 · 유형별 수 · 예 |
| POST | `/api/rlvr/score` | 보상 보기 `{"tasks", "task_id", "text"}` → 보상 · 항목별 기여 · 맞음 |
| POST | `/api/rlvr/env/check` | 환경-실제 차이 `{"tasks", "n"}` → 근거 겹침 · 집계 같음 |
| POST | `/api/rlvr/train` | GRPO 작업(관리자) `{"name", "tasks", "steps", "group", "lr", "beta", "max_new", "temperature"}` |
| POST | `/api/rlvr/eval` | 평가 작업 `{"tasks", "models", "splits", "max_per_split", "redteam"}` → 학습 / 시험 · 유형별 정답률 · 레드팀 · 외움 표시 |

## 고객 AS 상담 (`/api/as`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/as/setup` | 예시 자료 상태 / 준비 작업 `{"model_id"?, "index": true}` (가상 제품 매뉴얼 · FAQ 컬렉션, BM25 + 의미 인덱스) |
| POST / GET | `/api/as/sessions` | 상담 만들기 `{"collection_id"?, "customer", "product_model", "channel"}` / 목록(`?status=`) |
| GET | `/api/as/sessions/{id}` | 상담 · 대화 |
| POST | `/api/as/sessions/{id}/message` | multipart: `text`, `images`(최대 3), `audio`(STT_URL 필요), `provider`?, `model`? — 두 번째 문의부터 앞 대화로 질문을 풀어 씀(대화 · 메모리 C1) → `reply` · `steps`(AS1~AS7, 풀어 썼으면 '맥락 재작성') · `triage` · `photo` · `sources` · `verify`(근거 일치 · 코드 일치) · `guard` · `mismatch` · `handoff` · `ticket` · `cached` · `trace_id` |
| POST | `/api/as/sessions/{id}/feedback` | `{"resolved", "satisfaction": 1~5, "comment"}` — 미해결이면 티켓 |
| GET / PATCH | `/api/as/tickets` · `/tickets/{id}` | 이관 티켓(`?status=`) / 상태 `{"status": "open"·"in_progress"·"done", "note"}` |
| GET | `/api/as/metrics` | 해결률 · 이관률 · 만족도 · 의도별(`?days=30`) |
| POST | `/api/as/eval/triage` · `/eval/photo` · `/eval/e2e` | 실측 작업: 분류(제로샷 vs 학습) / 사진 코드 읽기 `{"hard", "repeats"}` / 문의 세트 종단 `{"guard_mode", "filter_model", "limit"}` |
| GET | `/api/as/eval/runs` · `/eval/runs/{id}` | 실측 기록 |
