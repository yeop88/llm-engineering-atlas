# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### 추가
- **LLM 연동**: OpenAI 호환 API(OpenAI·vLLM·Ollama·LM Studio)와 Claude API 를 httpx 로 직접 호출, 재시도·JSON 추출·토큰 사용량, 설정 상태·연결 시험 API — `docs/llm.md`
- **벤치마크 신뢰구간**: 질문·문장쌍 부트스트랩 95% 구간, 1위와의 짝지은 부트스트랩 비교(차이·p값·유의 여부), 결과 표에 표시 — `docs/benchmarks.md`
- **의미 기반 응용** 메뉴와 공통 기반: 입력 소스(직접 입력·예시 데이터 / 컬렉션 문서·청크), 임베딩 캐시, 학습 모델 저장 테이블(`app_models`, 마이그레이션 0003)
- **콘텐츠 추천**: 👍/👎·관심사로 취향 벡터, MMR 다양성, 추천 이유, 예시 기사 30건 — `docs/apps.md`
- **텍스트 분류**: 제로샷(라벨 설명) · 퓨샷 학습(로지스틱 회귀·중심점·kNN), 5겹 교차검증·혼동행렬·틀린 예시, 분류기 저장·예측 API, 예시(상품 리뷰 감성 45건, 고객·AS 문의 50건)
- **클러스터링**: K-means(실루엣 자동 군집 수)·계층·HDBSCAN, 군집별 명사 키워드(c-TF-IDF)·대표 문장·응집도, 정답 라벨과 ARI·순도, 강조형 군집 지도, CSV 내보내기
- **중복·표절 검사**: 대표(리더) 방식 중복 그룹화(연쇄 묶임 방지)·완전 중복/의역 구분·이웃 유사도 분포·중복 제거 목록 내보내기, 문장 단위 표절 검사(복사/의역/독창, 출처별 집계, 컬렉션을 참고 문서로), 예시(FAQ 30건, 보고서 표절)
- **이상·신종 탐지**: kNN 거리·LOF·Isolation Forest·중심점 경계, 교차 적합 점수의 컨포멀 분위수로 임계값 보정, 정상 대 이상 분류기로 처음 보는 유형 감지, 정상 / 알려진 유형 / 신종 판정과 평가(재현율·오탐률·AUC·혼동 행렬), 학습 데이터 안 이상치 찾기, 탐지기 저장·판정 API, 예시(문자 스팸, 보안 이벤트 로그)
- **키워드·요약**: 형태소 명사구 후보 + 문서 벡터 유사도 + MMR 키워드 추출(겹치는 표현 제외, CSV), 문장 그래프 중심성(중앙값 보정 LexRank) 추출 요약·의미 대표성·압축률, 예시(사내 문서 6건, 18문장 기사)
- 모델에 정의된 작업 프롬프트(분류·군집·유사도) 자동 사용 — EmbeddingGemma 2 감성 분류 60% → 87%
- **문서 검색(RAG) 파이프라인**
  - 컬렉션 · 문서 업로드: PDF · DOCX · **HWP 5.x(자체 바이너리 파서) · HWPX** · TXT · MD · HTML · CSV · JSON, 중복(SHA-256) 자동 제외, 원문 페이지 보관
  - 청킹 전략 5종: 재귀 · 고정 · 문장(Kiwi) · **법률 구조(조문·항·판결문 구획, 조문 제목 보존)** · 페이지, 미리보기(길이 분포·예시), 문서 제목·조문 제목을 붙여 임베딩
  - 벡터 인덱스: **Qdrant(기본, 서버 없으면 로컬 파일 모드)** · PostgreSQL pgvector(차원별 vector/halfvec/정확 검색 자동 선택) · MariaDB VECTOR 어댑터, 진행률·남은 시간 표시
  - 검색: 의미 · 한국어 형태소 BM25 · 하이브리드(RRF / 가중합), 리랭커 재정렬, 문서 필터, 단계별 소요 시간, 최대 4개 설정 나란히 비교
  - 문서 삭제 시 모든 인덱스의 벡터 정리, 청크 세트 이후 문서 변경 감지
- **리랭커** 카탈로그 11종(BGE Reranker v2 M3·한국어판, Qwen3-Reranker 0.6B/4B, mxbai-rerank-v2, Nemotron Rerank 등), 모델 종류(임베딩/리랭커) 구분·필터, Hub 가져오기 시 자동 판별
- **가속기별 설치**: `uv sync --extra cpu | cu126 | cu130 | rocm`(ROCm 은 Linux), CUDA/ROCm 빌드·GPU 정보 표시, `DEVICE=rocm` 지원
- `docker-compose.yml`: Qdrant 1.19.2, pgvector 0.8.7(PostgreSQL 18), MariaDB 13.0.2
- **Alembic 마이그레이션**: 시작 시 자동 적용, 기존 v0.1.0 DB 는 기준 리비전으로 표시 후 업그레이드
- 문서: `docs/rag.md`, `docs/gpu.md`

### 변경
- `MAX_LOADED_MODELS` 기본값 2 → 3 (임베딩 + 리랭커 동시 사용)
- 실행 이력 데이터셋 필터를 SQLite 전용 함수에서 DB 공통 JSON 연산으로 변경 (PostgreSQL·MariaDB 앱 DB 대비)

## [0.1.0] - 2026-10-17

첫 공개 릴리스입니다.

### 추가

**모델 관리**
- 2026-10 기준 오픈소스 임베딩 모델 카탈로그 37개: EmbeddingGemma 2(2026-10-06 공개), Nemotron-3-Embed, Harrier-OSS v1, Jina Embeddings v5, Qwen3-VL-Embedding, pplx-embed, Voyage 4 Nano, Granite Embedding R2, LFM2.5-Embedding, Qwen3-Embedding, BGE-M3, KURE, CLIP 등. 스펙은 각 모델 카드·설정 파일 기준
- Hugging Face Hub 실시간 검색과 메타데이터 자동 추출(프롬프트·차원·라이선스·trust_remote_code)로 모델 가져오기, Hub 통계 동기화
- 백그라운드 다운로드(바이트 단위 진행률, ONNX/GGUF 등 불필요 파일 제외), 로컬 캐시 크기 표시·삭제
- 로드/언로드, 최대 로드 수 초과 시 LRU 자동 언로드, 텍스트/멀티모달 프로필 분리 로드(EmbeddingGemma 2 텍스트 전용 270M 경로 지원)
- 모델별 query/document 프롬프트(prompt_name 또는 prefix)와 encode kwargs 자동 적용, 실제 임베딩 차원 자동 보정
- 모델 행별·다중 선택 삭제(로컬 캐시 함께 삭제 옵션), 삭제한 기본 카탈로그 모델 기억 및 복원

**테스트**
- 플레이그라운드: 여러 모델 검색 결과 나란히 비교, 유사도 행렬 히트맵, 임베딩 벡터·통계 확인, Matryoshka 차원 축소
- 임베딩 지도: PCA / t-SNE 2D 투영, 최대 3개 모델 비교, `그룹: 문장` 입력, 의미 쌍 연결선, 원래 차원 기준 정렬도(쌍 코사인·차이·짝 찾기 정확도)
- 멀티모달 텍스트→이미지 검색 (EmbeddingGemma 2, Qwen3-VL-Embedding, Jina v5 Omni, CLIP)

**벤치마크**
- 내장 데이터셋: 한/영/교차언어 검색(쿼리 30, 문서 33), 한/영 STS(문장쌍 24). 사용자 JSON 데이터셋 업로드
- 지표: nDCG@10, MRR@10, Recall@1/3/5/10, Spearman/Pearson, 처리 속도. 언어 그룹별·쿼리별 분석
- Matryoshka 차원 스윕: 한 번 인코딩으로 여러 차원을 평가
- 차트(Chart.js 4.5.1): 성능 vs 속도(파레토 최적), Recall@k, 언어 그룹별 막대, 모델 프로필 레이더, STS 산점도, 차원별 성능 곡선, 이력 추세. 색각이상 검증을 통과한 라이트/다크 팔레트
- 결과 내보내기: 표·차트를 담은 단일 HTML 리포트, 원본 JSON, 차트별 PNG
- 벤치마크 결과 행별·선택·전체(데이터셋 범위) 삭제

**대시보드 · 이력**
- 용도별 추천 모델(바로 사용 / 최근 공개 / 경량·CPU / 한국어 / 멀티모달 / 고성능·GPU)과 상태별 빠른 동작 버튼
- 메모리 사용량 차트(5초 간격, 최근 10분), 최근 벤치마크 차트, 시스템·로드 상태
- 모든 실행 이력 저장(SQLite), 이력 행별·선택·전체(종류 범위) 삭제

**기타**
- REST API 와 Swagger 문서(`/docs`), 문서 8종(`docs/`)
- 대체 임베딩 모델 정보 검증과 9개 모델 실측 결과(`docs/model-verification.md`)
- pytest 테스트 28개 (가짜 모델로 다운로드 없이 API·지표 검증)
- MIT 라이선스 (프로젝트 코드·문서에만 적용, 모델은 각자의 라이선스를 따름)

### 알려진 제한
- Nomic Embed Text v1.5 / v2 는 원격 코드가 transformers 5.x 와 호환되지 않아 로드되지 않습니다.
- 오디오·비디오 임베딩용 `sentence-transformers[audio,video]` extra 는 Python 3.14 + numpy 2.5 환경에서 의존성 해석이 안 되어 기본 설치에서 제외했습니다. UI 는 텍스트→이미지 검색까지 지원합니다.
- 차트는 Chart.js 를 CDN 에서 불러오므로 오프라인에서는 차트 대신 표만 표시됩니다.
- 내장 벤치마크 데이터셋은 소형이라 상위 모델 간 차이가 작게 나옵니다. 실제 선택에는 도메인 데이터셋을 업로드해 평가하세요.

[Unreleased]: https://github.com/yeop88/embedding-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yeop88/embedding-lab/releases/tag/v0.1.0
