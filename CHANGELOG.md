# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

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
