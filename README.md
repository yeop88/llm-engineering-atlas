# LLM Engineering Atlas

**Global LLM system engineering lab · Korean-first** — 데이터 임베딩부터 RAG 검색, 리랭킹, 라우팅, 소형·대형 모델까지 LLM 시스템의 각 단계를 실험·측정하고, 마지막에 단계들을 부분·전체로 연결해 보는 웹 실험실입니다. 다국어로 동작하며, 한국어(HWP 문서·형태소 검색·법령 구조 등)에 특화되어 있습니다.

```
[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]
                                        ↓
[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]
                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
```

(이전 이름: Embedding Lab — 2026년 10월 기준으로 공개된 **오픈소스 임베딩 모델을 관리·다운로드·테스트·벤치마크**하는 도구에서 출발했습니다.)
2026-10-06 공개된 Google **EmbeddingGemma 2**(텍스트·이미지·오디오·비디오 멀티모달)를 포함해 임베딩 모델 37개와 리랭커 11개가 기본 카탈로그로 등록되어 있고, Hugging Face Hub에서 원하는 모델을 검색해 추가할 수 있습니다.

문서를 올려 **청킹 전략 × 임베딩 모델 × 벡터 DB(Qdrant · pgvector · MariaDB) × 하이브리드 검색 × 리랭커** 조합을 직접 만들어 비교하는 문서 검색(RAG) 기능도 들어 있습니다. HWP·HWPX 한글 문서와 법령·판결문 구조 청킹을 지원합니다.

## 주요 기능

메뉴는 흐름도 순서입니다: **맵** · **1 임베딩**(모델 · Hub 검색 · 플레이그라운드 · 벤치마크) · **2 RAG**(컬렉션 · 답변 생성 · LLM 연결) · **3 리랭킹** · **4 검색 향상** · **5 파인튜닝** · **6~8 라우팅 · 모델**(라우팅 · 지식 증류 · 양자화 · 에이전트 · 강화학습) · 곁가지 **멀티모달** · **의미 응용** · **이력**. 단계마다 화면 위에 그 단계의 **원리 · 왜 하는가 · 어떻게(이 앱에서)** 가 나오고, `/stages/<단계>` 에서 아직 구현하지 않은 단계의 계획까지 볼 수 있습니다.

| 영역 | 기능 |
|---|---|
| 문서 검색 (RAG) | PDF·DOCX·HWP·HWPX 등 업로드, 청킹 전략 5종(법령·판결문 구조 포함) 미리보기·비교, 벡터 인덱스(Qdrant 기본 / pgvector / MariaDB), 의미·한국어 형태소 BM25·하이브리드(RRF) 검색, 리랭커, 최대 4개 설정 나란히 비교, 평가 세트·조합 평가, 근거 인용 LLM 답변과 환각 검증 |
| 파인튜닝 | 컬렉션 지문으로 학습 쌍 생성(LLM 질문 · ICT, 평가 근거 누수 방지), 대조 학습, 카탈로그 자동 등록, 학습 전후 짝지은 비교, 실행 기록(모델 카드) |
| LLM 연결 | 로컬 LLM(llama.cpp `llama-server` 등 OpenAI 호환, 기본 Gemma 4 E4B)과 Claude API, 생각 모드 끄기·스트리밍, 연결 시험 화면 |
| 의미 기반 응용 | 콘텐츠 추천(취향 벡터·MMR), 텍스트 분류(제로샷·학습·교차검증·분류기 저장/예측 API, 감성분석·문의 라우팅), 클러스터링(K-means·계층·HDBSCAN, 군집 키워드·대표 문장), 중복 제거(완전 중복·의역 구분)·문장 단위 표절 검사, 이상·신종 탐지(스팸·해킹 징후, 탐지기 저장/판정 API), 키워드 추출·추출 요약 |
| 모델 카탈로그 | 임베딩·리랭커 구분, 제공사·공개일·파라미터·차원(Matryoshka)·컨텍스트·라이선스·언어·모달리티 관리, 필터/정렬, 즐겨찾기, 프롬프트·로드 옵션 편집 |
| Hub 연동 | 실시간 검색, 메타데이터 자동 추출(프롬프트, trust_remote_code, gated 등), 원클릭 등록, 통계 동기화 |
| 다운로드 | 백그라운드 다운로드 + 바이트 진행률, ONNX/GGUF 등 불필요 파일 제외, 캐시 용량 표시/삭제 |
| 로드 관리 | 로드/언로드, 최대 로드 수 초과 시 LRU 언로드, 텍스트/멀티모달 프로필 분리 |
| 플레이그라운드 | 여러 모델 검색 결과 나란히 비교, 유사도 행렬 히트맵, 임베딩 벡터/통계 확인, MRL 차원 축소 |
| 멀티모달 | 텍스트로 이미지 검색 (EmbeddingGemma 2, Qwen3-VL-Embedding, Jina v5 Omni, CLIP) |
| 벤치마크 | 내장 한/영/교차언어 검색·STS 데이터셋, 사용자 데이터셋 업로드, nDCG/MRR/Recall · Spearman, 언어별·쿼리별 분석, 차트(성능 vs 속도·Recall@k·언어별·레이더·STS 산점도) |
| 이력 · 관리 | 모든 테스트 실행 기록(SQLite), 벤치마크 추세 차트, HTML 리포트·JSON·PNG 내보내기, 모델·이력·벤치마크 선택/전체 삭제, 삭제한 기본 모델 복원 |
| 대시보드 | 용도별 추천 모델, 메모리 사용량 차트, 최근 벤치마크 차트, 로드 상태 |

## 기술 스택 (2026-10 최신 안정 버전)

Python 3.14.6 · FastAPI 0.143.3 · Uvicorn 0.54.0 · Starlette 1.8 · Pydantic 2.14 · SQLAlchemy 2.1.5 · Alembic 1.20 · sentence-transformers 6.1.0 · transformers 5.20.1 · PyTorch 2.14.1 (CPU / CUDA 12.6·13.0 / ROCm 7.2) · huggingface-hub 1.33.0 · Qdrant 1.19 (qdrant-client 1.19) · pgvector 0.8.7 (PostgreSQL 18) · MariaDB 13.0 · Kiwi 0.24 (한국어 형태소) · Jinja2 · Chart.js 4.5.1 (CDN) · pytest 9.1 · ruff 0.17 · uv 0.12

> huggingface-hub 2.x가 나와 있지만 sentence-transformers 6.1이 `<2.0`을 요구하므로 1.x 최신을 사용합니다.

## 빠른 시작

시스템에 Python이 없어도 됩니다. [uv](https://docs.astral.sh/uv/)가 Python 3.14를 자동으로 받아 가상환경을 만듭니다.

```powershell
# 1) uv 설치 (없다면)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) 의존성 설치 — 가속기에 맞춰 하나 선택 (docs/guides/gpu.md)
uv sync --extra cpu        # CPU 전용
# uv sync --extra cu130    # NVIDIA GPU (CUDA 13.0, 최신 드라이버)
# uv sync --extra cu126    # NVIDIA GPU (CUDA 12.6)
# uv sync --extra rocm     # AMD GPU (Linux 전용)

# 3) (선택) 설정
copy .env.example .env      # gated 모델용 HF_TOKEN 등

# 4) (선택) 벡터 DB 서버 — 없어도 Qdrant 로컬 파일 모드로 동작
docker compose up -d                                        # Qdrant
docker compose --profile pgvector --profile mariadb up -d   # + pgvector, MariaDB

# 5) 실행 (DB 마이그레이션은 시작할 때 자동 적용)
uv run uvicorn app.main:app --reload --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. API 문서는 http://127.0.0.1:8000/docs 에 있습니다.

### 처음 써보기

1. **모델** 화면에서 `all-MiniLM-L6-v2`(87MB)를 다운로드 → 로드해 동작을 확인합니다.
2. `EmbeddingGemma 2`(1.5GB)를 받아 **플레이그라운드 → 검색 비교**에서 함께 선택해 결과를 비교합니다.
3. **벤치마크**에서 `한/영 미니 검색 벤치마크`로 여러 모델을 한 번에 평가합니다.
4. **멀티모달**에서 이미지 몇 장을 올리고 텍스트로 검색합니다.
5. **문서 검색**에서 컬렉션을 만들고 HWP·PDF 문서를 올린 뒤, 청크 세트 → 벡터 인덱스 → 검색 비교 순서로 진행합니다.

## 문서

전체 색인은 **[docs/README.md](docs/README.md)** 입니다. 문서는 흐름도의 단계 순서로 정리되어 있고, 단계마다 원리 · 왜 하는가 · 어떻게가 있습니다.

- [docs/map.md](docs/map.md) — 전체 흐름도와 각 단계의 목적 · 계획
- 단계: [1 임베딩](docs/stages/1-embedding/README.md) · [2 RAG](docs/stages/2-rag/README.md) · [3 리랭킹](docs/stages/3-rerank/README.md) · [4 검색 향상](docs/stages/4-search-lab/README.md) · [5 파인튜닝](docs/stages/5-finetune/README.md) · [6 라우팅](docs/stages/6-routing/README.md) · [7a 지식 증류](docs/stages/7a-distill/README.md) · [7b 양자화](docs/stages/7b-quant/README.md) · [8a 에이전트](docs/stages/8a-agent/README.md) · [8b 강화학습](docs/stages/8b-rl/README.md) · [멀티모달](docs/stages/multimodal/README.md) · [의미 응용](docs/stages/apps/README.md)
- 가이드: [아키텍처](docs/guides/architecture.md) · [API](docs/guides/api.md) · [LLM 연결](docs/guides/llm.md) · [GPU 설치](docs/guides/gpu.md) · [문제 해결](docs/guides/troubleshooting.md)
- 기록: [모델 검증과 실측](docs/records/model-verification.md) · [파인튜닝 실행 기록](docs/stages/5-finetune/finetune.md#실행-기록)

## 개발

```bash
uv run pytest -q             # 테스트 (실제 모델 다운로드 없음, Qdrant 는 메모리 모드)
# pgvector·MariaDB 어댑터까지 검사하려면 컨테이너를 띄우고:
# TEST_PGVECTOR_URL=postgresql://embedding:embedding@localhost:5433/embedding_lab TEST_MARIADB_URL=mysql://embedding:embedding@localhost:3307/embedding_lab uv run pytest -q
uv run python -m alembic revision --autogenerate -m "설명"   # DB 스키마 변경 시
uv run ruff check app tests  # 린트
uv run ruff format app tests # 포맷
```

변경 사항은 [CHANGELOG.md](CHANGELOG.md)에 기록합니다.

## 라이선스

**이 프로젝트의 소스 코드와 문서는 [MIT License](LICENSE)로 배포됩니다.**

**임베딩 모델의 라이선스는 이와 별도입니다.**
- 이 저장소에는 모델 가중치나 모델 코드가 포함되어 있지 않습니다. 앱은 사용자가 요청할 때 Hugging Face Hub에서 모델을 내려받아 로컬에서 실행할 뿐 재배포하지 않습니다.
- 각 모델은 제공자가 정한 고유 라이선스를 따르며, MIT 라이선스가 모델에 적용되지 않습니다. 모델을 사용하기 전에 해당 모델 카드의 라이선스를 직접 확인하세요. 카탈로그의 라이선스 표기([docs/stages/1-embedding/models.md](docs/stages/1-embedding/models.md), 앱의 모델 화면)는 참고용이며 변경될 수 있습니다.
- 특히 다음 모델은 상업적 사용이 제한되거나 별도 조건이 있습니다.

| 라이선스 | 해당 모델 (카탈로그 기준) |
|---|---|
| CC-BY-NC-4.0 (비상업) | Jina Embeddings v3, v5 Text Small/Nano, v5 Omni Small |
| NVIDIA Custom (비상업) | Llama-Embed-Nemotron 8B |
| Gemma Terms of Use (동의 필요, gated) | EmbeddingGemma 300M |
| LFM Open License v1.0 | LFM2.5-Embedding 350M |
| OpenMDW-1.1 | Nemotron-3-Embed 1B / 8B |

그 밖의 모델은 대부분 Apache-2.0 또는 MIT이지만, 역시 모델별로 확인하세요.
