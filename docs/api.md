# REST API

서버 실행 후 http://127.0.0.1:8000/docs (Swagger UI)에서 모든 엔드포인트를 직접 호출해 볼 수 있습니다.

## 모델

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/models?q=&modality=&tag=&status=&sort=` | 목록. status: `cached`/`loaded`/`favorite`, sort: `release_date`/`downloads`/`name`/`dim` |
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
