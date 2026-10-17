# REST API

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
| POST | `/api/collections/{id}/documents` | 파일 업로드 (multipart `files`, 여러 개) → `added`, `skipped` |
| GET / DELETE | `/api/documents/{id}` | 본문 보기 / 삭제(청크·벡터 함께) |
| POST | `/api/collections/{id}/chunk-preview` | 청킹 미리보기 `{"method", "size", "overlap", ...}` → 통계·예시 |
| POST | `/api/collections/{id}/chunk-sets` | 청크 세트 생성 (백그라운드 작업) |
| GET | `/api/chunk-sets/{id}/chunks?offset=&limit=&document_id=` | 청크 목록 (BM25 토큰 포함) |
| DELETE | `/api/chunk-sets/{id}` | 청크 세트와 그 인덱스 삭제 |
| POST | `/api/indexes` | `{"chunk_set_id", "model_id", "store": "qdrant", "truncate_dim": null}` → 인덱스 구축 작업 |
| POST | `/api/indexes/{id}/rebuild` · DELETE `/api/indexes/{id}` | 다시 구축 / 삭제 |
| POST | `/api/collections/{id}/search` | 검색 비교 (아래) |

```http
POST /api/collections/1/search
{"query": "공문서는 어떤 문자로 작성하나요?",
 "configs": [
   {"label": "BM25", "chunk_set_id": 1, "mode": "bm25", "top_k": 5},
   {"label": "하이브리드+리랭커", "index_id": 2, "mode": "hybrid", "fusion": "rrf",
    "candidates": 50, "reranker_id": 40, "rerank_top": 30, "top_k": 5, "doc_ids": null}]}
```

응답의 각 결과에는 `results[]`(문서·쪽·조문 제목·본문·점수·순위), `timings_ms`, `query_tokens` 가 들어 있습니다.

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
| POST | `/api/benchmarks` | `{"model_ids": [...], "dataset": "...", "truncate_dim": null, "batch_size": null, "unload_after": false, "sweep_dims": [768, 256, 64]}` → 작업. `sweep_dims`가 있으면 결과의 모델별 `dim_sweep`에 차원별 지표 포함 |
| GET | `/api/jobs?kind=` · `/api/jobs/{id}` | 작업 상태 (progress 0~1, message, result) |
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
