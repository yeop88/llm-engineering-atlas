# Embedding Lab

2026년 10월 기준으로 공개된 **오픈소스 임베딩 모델을 관리·다운로드·테스트·벤치마크**하는 FastAPI 웹 애플리케이션입니다.
2026-10-06 공개된 Google **EmbeddingGemma 2**(텍스트·이미지·오디오·비디오 멀티모달)를 포함해 37개 모델이 기본 카탈로그로 등록되어 있고, Hugging Face Hub에서 원하는 모델을 검색해 추가할 수 있습니다.

## 주요 기능

| 영역 | 기능 |
|---|---|
| 모델 카탈로그 | 제공사·공개일·파라미터·차원(Matryoshka)·컨텍스트·라이선스·언어·모달리티 관리, 필터/정렬, 즐겨찾기, 프롬프트·로드 옵션 편집 |
| Hub 연동 | 실시간 검색, 메타데이터 자동 추출(프롬프트, trust_remote_code, gated 등), 원클릭 등록, 통계 동기화 |
| 다운로드 | 백그라운드 다운로드 + 바이트 진행률, ONNX/GGUF 등 불필요 파일 제외, 캐시 용량 표시/삭제 |
| 로드 관리 | 로드/언로드, 최대 로드 수 초과 시 LRU 언로드, 텍스트/멀티모달 프로필 분리 |
| 플레이그라운드 | 여러 모델 검색 결과 나란히 비교, 유사도 행렬 히트맵, 임베딩 벡터/통계 확인, MRL 차원 축소 |
| 멀티모달 | 텍스트로 이미지 검색 (EmbeddingGemma 2, Qwen3-VL-Embedding, Jina v5 Omni, CLIP) |
| 벤치마크 | 내장 한/영/교차언어 검색·STS 데이터셋, 사용자 데이터셋 업로드, nDCG/MRR/Recall · Spearman, 언어별·쿼리별 분석, 차트(성능 vs 속도·Recall@k·언어별·레이더·STS 산점도) |
| 이력 · 관리 | 모든 테스트 실행 기록(SQLite), 벤치마크 추세 차트, HTML 리포트·JSON·PNG 내보내기, 모델·이력·벤치마크 선택/전체 삭제, 삭제한 기본 모델 복원 |
| 대시보드 | 용도별 추천 모델, 메모리 사용량 차트, 최근 벤치마크 차트, 로드 상태 |

## 기술 스택 (2026-10 최신 안정 버전)

Python 3.14.6 · FastAPI 0.143.3 · Uvicorn 0.54.0 · Starlette 1.8 · Pydantic 2.14 · SQLAlchemy 2.1.5 · sentence-transformers 6.1.0 · transformers 5.20.1 · PyTorch 2.14.1 · huggingface-hub 1.33.0 · Jinja2 · Chart.js 4.5.1 (CDN) · pytest 9.1 · ruff 0.17 · uv 0.12

> huggingface-hub 2.x가 나와 있지만 sentence-transformers 6.1이 `<2.0`을 요구하므로 1.x 최신을 사용합니다.

## 빠른 시작

시스템에 Python이 없어도 됩니다. [uv](https://docs.astral.sh/uv/)가 Python 3.14를 자동으로 받아 가상환경을 만듭니다.

```powershell
# 1) uv 설치 (없다면)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) 의존성 설치
uv sync

# 3) (선택) 설정
copy .env.example .env      # gated 모델용 HF_TOKEN 등

# 4) 실행
uv run uvicorn app.main:app --reload --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. API 문서는 http://127.0.0.1:8000/docs 에 있습니다.

### 처음 써보기

1. **모델** 화면에서 `all-MiniLM-L6-v2`(87MB)를 다운로드 → 로드해 동작을 확인합니다.
2. `EmbeddingGemma 2`(1.5GB)를 받아 **플레이그라운드 → 검색 비교**에서 함께 선택해 결과를 비교합니다.
3. **벤치마크**에서 `한/영 미니 검색 벤치마크`로 여러 모델을 한 번에 평가합니다.
4. **멀티모달**에서 이미지 몇 장을 올리고 텍스트로 검색합니다.

## 문서

- [docs/architecture.md](docs/architecture.md) — 구조와 동작 방식
- [docs/models.md](docs/models.md) — 카탈로그 모델 목록과 선택 가이드
- [docs/model-verification.md](docs/model-verification.md) — 대체 모델 정보 검증 결과와 실측 벤치마크
- [docs/benchmarks.md](docs/benchmarks.md) — 벤치마크 지표와 데이터셋 형식
- [docs/visualization.md](docs/visualization.md) — 벤치마크 차트 읽는 법
- [docs/multimodal.md](docs/multimodal.md) — 이미지/오디오/비디오 임베딩
- [docs/api.md](docs/api.md) — REST API
- [docs/troubleshooting.md](docs/troubleshooting.md) — 문제 해결

## 개발

```bash
uv run pytest -q             # 테스트 (실제 모델 다운로드 없음)
uv run ruff check app tests  # 린트
uv run ruff format app tests # 포맷
```

변경 사항은 [CHANGELOG.md](CHANGELOG.md)에 기록합니다.

## 라이선스

**이 프로젝트의 소스 코드와 문서는 [MIT License](LICENSE)로 배포됩니다.**

**임베딩 모델의 라이선스는 이와 별도입니다.**
- 이 저장소에는 모델 가중치나 모델 코드가 포함되어 있지 않습니다. 앱은 사용자가 요청할 때 Hugging Face Hub에서 모델을 내려받아 로컬에서 실행할 뿐 재배포하지 않습니다.
- 각 모델은 제공자가 정한 고유 라이선스를 따르며, MIT 라이선스가 모델에 적용되지 않습니다. 모델을 사용하기 전에 해당 모델 카드의 라이선스를 직접 확인하세요. 카탈로그의 라이선스 표기([docs/models.md](docs/models.md), 앱의 모델 화면)는 참고용이며 변경될 수 있습니다.
- 특히 다음 모델은 상업적 사용이 제한되거나 별도 조건이 있습니다.

| 라이선스 | 해당 모델 (카탈로그 기준) |
|---|---|
| CC-BY-NC-4.0 (비상업) | Jina Embeddings v3, v5 Text Small/Nano, v5 Omni Small |
| NVIDIA Custom (비상업) | Llama-Embed-Nemotron 8B |
| Gemma Terms of Use (동의 필요, gated) | EmbeddingGemma 300M |
| LFM Open License v1.0 | LFM2.5-Embedding 350M |
| OpenMDW-1.1 | Nemotron-3-Embed 1B / 8B |

그 밖의 모델은 대부분 Apache-2.0 또는 MIT이지만, 역시 모델별로 확인하세요.
