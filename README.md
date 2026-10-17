# LLM Engineering Atlas

**Global LLM system engineering lab · Korean-first** — 데이터 임베딩부터 RAG 검색, 리랭킹, 라우팅, 소형·대형 모델까지 LLM 시스템의 각 단계를 실험·측정하고, 마지막에 단계들을 부분·전체로 연결해 보는 웹 실험실입니다. 다국어로 동작하며, 한국어(HWP 문서·형태소 검색·법령 구조 등)에 특화되어 있습니다.

```
[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]
                                        ↓
[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]
                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
```

각 단계를 **따로 실험하고 숫자로 검증**합니다. 평가 세트 · 부트스트랩 신뢰구간 · 짝지은 비교로 "정말 좋아졌는가"를 판정하고, 실측 결과(잘된 것과 안 된 것, 정정 기록까지)를 문서에 남깁니다. 단계마다 화면 위에 그 단계의 **원리 · 왜 하는가 · 어떻게** 가 있고, 메뉴도 흐름도 순서입니다.

(이전 이름: Embedding Lab — 오픈소스 임베딩 모델을 관리 · 테스트 · 벤치마크하는 도구에서 출발했습니다.)

## 단계별 기능

| 단계 | 상태 | 이 앱에서 할 수 있는 것 |
|---|---|---|
| **맵** | ✅ | 전체 흐름도와 단계 상태, 단계 소개(`/stages/<단계>`), 부분 · 전체 연결 계획 |
| **1 데이터 임베딩** | ✅ | 2026-10 기준 임베딩 모델 37개 · 리랭커 11개 카탈로그(EmbeddingGemma 2 포함), Hub 검색 · 다운로드 · LRU 로드, 플레이그라운드(검색 비교 · 유사도 행렬 · 임베딩 지도 · Matryoshka), 벤치마크(내장 · 공개 한국어 6종 · 내 데이터셋, 95% 신뢰구간 · 1위 대비 유의성, 차트) |
| **2 RAG 검색** | ✅ | HWP · HWPX · PDF · DOCX 등 업로드, 청킹 5종(법령 · 판결문 구조 포함), 벡터 인덱스(Qdrant 기본 · pgvector · MariaDB, 작은 인덱스는 정확 검색), 한국어 형태소 BM25 · 하이브리드(RRF), 평가 세트(LLM 질문 생성 · 직접 입력) · 조합 평가, 근거 번호를 인용하는 LLM 답변(스트리밍)과 문장별 환각 검증 · 답변 일괄 평가 |
| **3 리랭킹** | 🟡 | 검색 · 평가 · 답변에서 리랭커 선택(고도화 예정) |
| **4 검색 향상** | ✅ | 질의 재작성 · HyDE · 다중 질의(원 질의와 RRF 융합, LLM 변형 캐시), 검색 설정 `enhance` 로 검색 · 평가 · 답변 어디서든 적용, 기법별 나란히 비교 · 평가 세트 비교 (문맥 청크는 예정) |
| **5 파인튜닝** | ✅ | 컬렉션 지문으로 학습 쌍 생성(LLM 질문 · ICT, 평가 근거 누수 방지), 대조 학습, 카탈로그 자동 등록, 학습 전후 짝지은 비교 · 다시 비교, 실행 기록(모델 카드) |
| **6~8 라우팅 · 증류 · 양자화 · 에이전트 · 강화학습** | ⬜ | 원리 · 왜 · 계획 (예정) |
| 멀티모달 | 🟡 | 텍스트로 이미지 검색(EmbeddingGemma 2 · Qwen3-VL-Embedding · Jina v5 Omni · CLIP) |
| 의미 응용 | ✅ | 추천(MMR) · 분류(제로샷 · 학습, 분류기 저장/예측 API) · 군집 · 중복/표절 · 이상/신종 탐지 · 키워드/요약 |
| 공통 | ✅ | LLM 연결(로컬 llama.cpp · OpenAI 호환 · Claude API, 기본 Gemma 4 E4B), 모든 실행 이력 · 추세 · 내보내기, 대시보드 |

✅ 구현됨 · 🟡 기초 있음 · ⬜ 예정 — 단계 정의와 상태는 `app/stages/registry.py` 한 곳에서 관리합니다.

## 기술 스택 (2026-10 최신 안정 버전)

Python 3.14.6 · FastAPI 0.143.3 · Uvicorn 0.54.0 · Starlette 1.8 · Pydantic 2.14 · SQLAlchemy 2.1.5 · Alembic 1.20 · sentence-transformers 6.1.0 (+ train: datasets 5.1 · accelerate 1.15) · transformers 5.20.1 · PyTorch 2.14.1 (CPU / CUDA 12.6·13.0 / ROCm 7.2) · huggingface-hub 1.33.0 · pyarrow 26 · httpx 0.28 · Qdrant 1.19 (qdrant-client 1.19) · pgvector 0.8.7 (PostgreSQL 18) · MariaDB 13.0 · Kiwi 0.24 (한국어 형태소) · Jinja2 · Chart.js 4.5.1 (CDN) · pytest 9.1 · ruff 0.17 · uv 0.12

로컬 LLM(선택): llama.cpp `llama-server` b11669(v0.7.0, Vulkan) + Gemma 4 E4B QAT q4_0 — [docs/guides/llm.md](docs/guides/llm.md)

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

### 처음 써보기 (흐름도 순서)

1. **1 임베딩 → 모델**에서 `EmbeddingGemma 2` 를 받아 로드하고, **플레이그라운드**에서 다른 모델과 검색 결과를 비교합니다. **벤치마크**에서 공개 한국어 벤치마크를 가져와 신뢰구간과 함께 평가합니다.
2. **2 RAG → 컬렉션**에서 HWP · PDF 문서를 올리고 청크 세트 → 벡터 인덱스 → 검색 비교 → **⑤ 평가** 탭(평가 세트 · 조합 평가) 순서로 진행합니다.
3. (선택) 로컬 LLM 을 켜고([docs/guides/llm.md](docs/guides/llm.md)) **2 RAG → 답변 생성**에서 근거를 인용한 답변과 환각 검증을 봅니다.
4. **4 검색 향상**에서 구어체 질문을 넣어 질의 재작성 · HyDE · 다중 질의가 결과를 어떻게 바꾸는지 보고, 평가 세트로 효과를 잽니다.
5. **5 파인튜닝**에서 임베딩 모델을 컬렉션에 맞게 학습하고 전후를 비교합니다.
6. **맵**에서 전체 흐름과 다음 단계를 확인합니다.

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
