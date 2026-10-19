# 문제 해결

### `Python was not found`
이 PC에는 시스템 Python이 없습니다. 모든 명령을 `uv run ...`으로 실행하세요. uv가 `.python-version`(3.14)에 맞는 Python을 자동으로 사용합니다.

### `alembic` 명령이 "애플리케이션 제어 정책에서 차단" 오류로 실행되지 않음
Windows 의 앱 제어 정책(Smart App Control 등)이 가상환경의 `alembic.exe` 를 막는 경우입니다. `uv run python -m alembic ...` 처럼 모듈로 실행하세요. 앱은 시작할 때 마이그레이션을 직접 적용하므로 평소에는 명령을 칠 필요가 없습니다.

### 재부팅 뒤 `uv run` 이 `os error 4551`("애플리케이션 제어 정책에서 이 파일을 차단했습니다")
같은 정책이 가상환경의 실행 파일들(`python.exe` · `uvicorn.exe` · `pytest.exe` — uv 가 만든 서명 없는 작은 실행기)을 막는 경우입니다. 2026-10-19 재부팅 뒤 실제로 겪었습니다.

- **정책을 끌 수 있으면**: Windows 보안 → 앱 및 브라우저 컨트롤 → Smart App Control 끄기(한 번 끄면 다시 켤 수 없음). 끈 뒤에도 `uvicorn.exe` · `pytest.exe` 같은 실행기는 한동안 막힐 수 있으니 모듈로 실행합니다: `uv run python -m uvicorn app.main:app --port 8000`, `uv run python -m pytest -q`. 첫 실행 때 PyAV 같은 DLL 을 검사하느라 테스트 수집이 한 번 실패할 수 있습니다 — 다시 실행하면 됩니다.
- **끌 수 없으면**(회사 정책): uv 가 설치한 Python 본체(`%APPDATA%\uv\python\cpython-3.14-…\python.exe`)는 허용되는 경우가 있습니다. 가상환경 패키지를 **`site.addsitedir`** 로 더해 실행합니다.

  ```powershell
  & "$env:APPDATA\uv\python\cpython-3.14-windows-x86_64-none\python.exe" -c "import site, sys, runpy; site.addsitedir(r'C:\…\embedding_test\.venv\Lib\site-packages'); sys.argv=['uvicorn','app.main:app','--port','8000']; runpy.run_module('uvicorn', run_name='__main__')"
  ```

  `PYTHONPATH` 로 패키지 폴더만 넘기면 안 됩니다 — `.pth` 파일을 읽지 않아 pywin32 가 빠지고, Qdrant 로컬 모드가 `pywintypes is required for Win32Locker` 오류로 열리지 않습니다(실제로 겪음).

### Qdrant 로컬 모드 "already accessed by another instance"
`QDRANT_URL` 없이 쓰는 로컬 파일 모드는 한 프로세스만 `data/qdrant` 를 열 수 있습니다. 서버를 두 개 띄웠거나 다른 스크립트가 같은 폴더를 열고 있으면 생깁니다. 여러 프로세스(예: `--workers 2`)로 운영하려면 Qdrant 서버(`docker compose up -d`)를 쓰고 `QDRANT_URL=http://localhost:6333` 을 설정하세요.

### pgvector / MariaDB 가 "설정 안 됨" 또는 "연결 실패"
`.env` 에 `PGVECTOR_URL` / `MARIADB_URL` 을 넣고 컨테이너를 띄웠는지 확인하세요(`docker compose --profile pgvector --profile mariadb up -d`). 기본 포트는 로컬 DB 와 겹치지 않도록 5433(PostgreSQL), 3307(MariaDB)입니다. MariaDB 는 VECTOR 를 지원하는 11.7 이상이어야 합니다.

### HWP 문서가 "배포용(보호)" 또는 "HWP 5.x 만 지원" 오류
배포용 문서는 본문이 암호화되어 있어 미리보기 텍스트만 읽습니다. HWP 3.x 이하 문서는 한글에서 HWP 또는 HWPX 로 다시 저장하세요.

### gated 모델 다운로드 실패 (401/403, `GatedRepoError`)
예: `google/embeddinggemma-300m`. Hugging Face 모델 페이지에서 라이선스에 동의한 뒤 토큰을 `.env`에 `HF_TOKEN=hf_...`으로 넣고 서버를 재시작하세요. 대시보드의 "HF_TOKEN" 항목에서 설정 여부를 확인할 수 있습니다. (`google/embeddinggemma-2`는 gated가 아닙니다.)

### `trust_remote_code` 모델 로드 실패
Jina v3/v5, Nomic, GTE, pplx-embed, LFM2.5 등은 모델 저장소의 파이썬 코드를 실행합니다. 원격 코드가 최신 transformers 5.x와 맞지 않으면 `ImportError`/`AttributeError`가 납니다. 모델 상세 화면에 오류가 표시되며, 해결책은 다음과 같습니다.
- 모델 저장소에 최신 리비전이 있는지 확인하고 캐시를 삭제한 뒤 다시 받기
- 같은 계열의 transformers 네이티브 버전 사용 (예: `jinaai/jina-embeddings-v3-hf`를 Hub 검색으로 추가)

### 임베딩에 NaN이 나옴
EmbeddingGemma 계열을 float16으로 실행하면 발생합니다. `.env`에서 `DTYPE=auto`(기본) 또는 `float32`/`bfloat16`을 사용하세요.

### 메모리 부족 / 너무 느림
- `MAX_LOADED_MODELS=1`로 줄이거나 벤치마크에서 "평가 후 언로드"를 켜세요.
- 배치 크기를 줄이세요(`DEFAULT_BATCH_SIZE` 또는 벤치마크 옵션).
- CPU에서는 1B 이하 모델을 권장합니다. 대략적인 fp32 메모리는 파라미터 수 × 4바이트입니다 (0.6B ≈ 2.4GB, 4B ≈ 16GB, 8B ≈ 32GB).
- NVIDIA GPU가 있다면 CUDA용 PyTorch를 설치하세요. 예:
  ```toml
  # pyproject.toml
  [[tool.uv.index]]
  name = "pytorch-cu130"
  url = "https://download.pytorch.org/whl/cu130"
  explicit = true

  [tool.uv.sources]
  torch = { index = "pytorch-cu130" }
  ```
  그 다음 `uv sync`. (CUDA 버전은 드라이버에 맞게 선택)

### Windows 심볼릭 링크 경고
HF 캐시는 심볼릭 링크 없이도 동작합니다(파일이 복사되어 용량을 조금 더 씀). 앱은 경고를 끄도록 설정되어 있습니다. 개발자 모드를 켜면 링크를 사용합니다.

### 다운로드 진행률이 멈춘 것처럼 보임
대용량 파일은 Xet 전송 후 재구성 단계가 있어 잠시 멈춘 듯 보일 수 있습니다. 서버 로그와 대시보드의 작업 상태를 확인하세요.

### 프롬프트 경고 (`프롬프트 'xxx' 이(가) 모델에 없어 무시했습니다`)
모델 상세에서 설정한 prompt_name이 모델 설정에 없다는 뜻입니다. 모델을 로드하면 "모델 정의 프롬프트"에 사용 가능한 이름이 표시되니 그중에서 고르거나, prefix 칸에 직접 접두어를 넣으세요.
