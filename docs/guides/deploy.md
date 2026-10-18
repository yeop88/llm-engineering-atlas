# 배포 · 운영 — Docker, 접근 토큰, 작업 기록, 모델 호환성 점검, 새 모델 후보

혼자 로컬에서 `uv run uvicorn` 으로 쓰는 것이 기본입니다. 이 문서는 사내 서버 · 팀이 함께 쓰는 서버에 올릴 때 필요한 것을 모았습니다.

## 1. Docker 로 실행

```bash
cp .env.example .env              # API_TOKEN 등 설정 (아래 2)
docker compose --profile app up -d --build                       # 앱 + Qdrant (CPU)
TORCH_EXTRA=cu130 docker compose --profile app up -d --build     # NVIDIA GPU (docs/guides/gpu.md)
docker compose --profile app --profile pgvector up -d            # pgvector 도 함께
```

- 이미지: `python:3.14-slim-trixie` + uv 0.12.0(로컬과 같은 버전 — `uv.lock` 해석이 달라지지 않게). 의존성 층을 코드보다 먼저 설치해, 코드만 바꾸면 torch(수 GB) 층은 다시 받지 않습니다.
- 볼륨: `app_data`(→ `/app/data`: SQLite · 업로드 · 공개 자료 캐시 · 미디어), `hf_cache`(→ 내려받은 모델). 이미지를 다시 만들어도 실험 기록과 모델이 남습니다.
- 컨테이너 안에서는 Qdrant 를 `http://qdrant:6333`(서비스 이름)으로 찾습니다. pgvector · MariaDB 주소는 `PGVECTOR_URL_IN_DOCKER` · `MARIADB_URL_IN_DOCKER` 로 바꿀 수 있습니다.
- 상태 확인: `GET /api/health`(인증 없이 열림, 정보 없음) — Docker `HEALTHCHECK` 가 씁니다.
- 로컬 LLM(llama-server)은 컨테이너 밖에서 돌리는 것을 권장합니다(GPU · Vulkan 드라이버). 컨테이너에서 호스트로는 `OPENAI_BASE_URL=http://host.docker.internal:8081/v1`.
- `.dockerignore` 가 `.env` · `data/` · `.venv` · 테스트를 뺍니다 — 비밀과 대용량이 이미지에 섞이지 않게.

## 2. 접근 토큰 (`API_TOKEN`)

`0.0.0.0` 으로 열면 같은 망의 누구나 모델을 내려받고 컬렉션 · 이력을 지울 수 있습니다. `.env` 에 토큰을 넣으면 전부 막힙니다.

```ini
API_TOKEN=길고-추측하기-어려운-값      # 예: python -c "import secrets; print(secrets.token_urlsafe(32))"
AUTH_COOKIE_DAYS=14
AUTH_COOKIE_SECURE=true                # HTTPS 리버스 프록시 뒤라면
```

| 접근 | 방법 |
|---|---|
| 화면 | `/login` 에서 토큰 입력 → 쿠키(HttpOnly · SameSite=Lax). 상단 '로그아웃' |
| API · 스크립트 | `Authorization: Bearer <토큰>` 헤더 |
| 열린 경로 | `/login` · `/logout` · `/static/*` · `/api/health` |

- 쿠키에는 토큰이 아니라 토큰의 HMAC 을 담습니다(쿠키가 새도 토큰은 드러나지 않음). 토큰을 바꾸면 모든 로그인이 풀립니다.
- 비교는 `secrets.compare_digest`(시간 차로 토큰을 알아내지 못하게), 로그인 후 이동은 같은 사이트 경로만(열린 리디렉션 방지).
- 사용자 · 권한 구분은 없습니다(토큰 하나). 여러 사람의 권한을 나눠야 하면 앞단(리버스 프록시 · SSO)에서 처리하세요.

## 3. 작업 기록 (재시작해도 남음)

다운로드 · 벤치마크 · 평가 같은 백그라운드 작업은 메모리의 스레드 풀에서 돌지만, 상태 · 진행률 · 결과를 DB(`job_records`, 마이그레이션 0008)에도 남깁니다.

- 예전에는 서버를 다시 켜면 몇 시간 걸린 측정 결과가 사라졌습니다(실행 이력에 남기지 않는 작업도 있음).
- 진행률은 5초에 한 번만 기록합니다(DB 쓰기가 계산을 느리게 하지 않게). 결과는 끝날 때 한 번. JSON 으로 바꿀 수 없는 결과면 상태만 남깁니다.
- 재시작 때 끝나지 않은 작업은 `interrupted`(중단됨) 로 표시합니다. 계산은 이어 할 수 없으니 다시 실행하세요.
- `/api/jobs` 는 메모리 + DB 기록을 합쳐 보여 주고(`limit`, 최대 500), `/api/jobs/{id}` 는 메모리에 없으면 DB 에서 찾습니다.

## 4. 모델 호환성 점검

sentence-transformers · transformers · torch 를 올리면 `trust_remote_code` 모델의 코드가 깨지거나, 프롬프트 이름이 바뀌거나, dtype 기본값이 달라져 NaN 이 나올 수 있습니다. 벤치마크를 몇 시간 돌린 뒤에 알면 늦으므로, 모델마다 문장 몇 개로 확인합니다.

**모델 화면 → 호환성 점검** (`POST /api/models/compat-check`, 본문에 모델 id 목록을 주면 그것만)

| 항목 | 문제로 보는 경우 |
|---|---|
| 로드 | 예외 |
| 차원 | 실제 출력 차원 ≠ 카탈로그 `dim` |
| 수치 | NaN · inf, 정규화 후 길이 ≠ 1 |
| 프롬프트 | 카탈로그의 `query_prompt` · `document_prompt` 가 모델에 정의돼 있지 않음(조용히 무시되어 점수만 떨어지는 경우) |
| 상식 | 관련 문서가 무관한 문서보다 가깝지 않음(한국어 · 영어 한 쌍씩), 리랭커는 관련 점수가 더 높지 않음 |

- 기본은 **내려받아 둔 모델만** 점검합니다(점검 때문에 수 GB 를 내려받지 않게). 점검하려고 올린 모델은 끝나면 내립니다.
- 결과는 실행 이력(`kind=compat`)에 라이브러리 버전과 함께 남습니다. 지난 점검 때와 버전이 다르면 모델 화면에 '점검 권장'이 뜨고, `COMPAT_CHECK_ON_UPGRADE=true` 면 시작할 때 자동으로 점검합니다(CPU 에서는 몇 분 — 기본은 꺼짐).

## 5. 새 모델 후보 (카탈로그 갱신)

카탈로그는 손으로 고른 목록이라 새 모델이 나와도 모르고 지나가기 쉽습니다. **Hub 화면 → 카탈로그에 없는 새 모델 후보**(`GET /api/hub/discover?days=180&min_likes=10`)가 Hub 의 인기 급상승 목록에서 찾아 줍니다.

- 질의: 한국어 임베딩 · 다국어 임베딩 · 특징 추출 · 한국어 리랭커 · 리랭커 (각 trending 상위 60개)
- 거르기: 최근 `days` 일 안에 공개, 좋아요 `min_likes` 이상, 이미 카탈로그에 있거나 지운 모델 제외, GGUF · ONNX · MLX · NVFP4 같은 변환본 제외(PyTorch 로 못 올림 — 원본이 따로 있음)
- 점수 = log(1+좋아요) + 최근 가산(최대 2) + 한국어 가산(1.5). Hub 호출이 여러 번이라 1시간 캐시(`force=true` 로 새로 고침)
- **자동으로 추가하지 않습니다.** '상세'로 프롬프트 · 차원 · `trust_remote_code` · 라이선스를 확인하고 '추가' — 카탈로그 기본 목록(`catalog.py`)에 넣을 때는 Hub 설정 파일로 스펙을 확인하는 규칙을 그대로 따릅니다.
