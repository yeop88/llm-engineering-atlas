# 문제 해결

### `Python was not found`
이 PC에는 시스템 Python이 없습니다. 모든 명령을 `uv run ...`으로 실행하세요. uv가 `.python-version`(3.14)에 맞는 Python을 자동으로 사용합니다.

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
