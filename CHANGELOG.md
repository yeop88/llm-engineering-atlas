# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고, 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### 추가
- **벤치마크 시각화** (Chart.js 4.5.1, cdnjs + SRI): 성능 vs 속도 버블(파레토 최적 표시), Recall@k 선 그래프, 언어 그룹별 막대, 모델 프로필 레이더(최대 3개, 최근 STS 결과 결합), STS 정답 vs 코사인 작은 산점도, 쿼리별 순위 표 색칠
- 색각이상 검증을 통과한 8색 범주 팔레트(라이트/다크 각각)와 차트 색 토큰, `docs/visualization.md`
- **Matryoshka 차원 스윕**: 벤치마크 한 번에 여러 차원을 평가(전체 차원으로 1회 인코딩 후 잘라서 재정규화), "차원별 성능" 곡선(절대값 / 전체 대비 %, MRL 미학습 모델은 ◆ 표시, 표 보기)
- **임베딩 지도** (플레이그라운드 탭): PCA / t-SNE 2D 투영, 최대 3개 모델 나란히 비교, `그룹: 문장` 입력, 의미 쌍 연결선, 원래 차원 기준 정렬도(쌍 코사인·차이·짝 찾기 정확도) 표 — `POST /api/projection`
- **이력 추세 차트**: 같은 데이터셋 벤치마크 실행들의 모델별 대표 지표 추이 (차원을 줄인 실행은 제외)
- **내보내기**: 벤치마크 결과를 표·차트 포함 단일 HTML 리포트 / 원본 JSON 으로 저장, 모든 차트 카드에 PNG 저장 버튼 (임베딩 지도 포함)
- **대시보드 차트**: 메모리 사용량(5초 간격, 최근 10분 — 서버 측 샘플러), 최근 벤치마크 모델별 대표 지표 막대
- **삭제 기능**
  - 모델: 행별 삭제, 체크박스 다중 선택 삭제(로컬 캐시 함께 삭제 옵션). 삭제한 기본 카탈로그 모델은 재시작 시 다시 추가되지 않으며 "삭제한 기본 모델 복원"으로 되돌릴 수 있음 (`catalog_exclusions` 테이블)
  - 이력: 행별 삭제, 다중 선택 삭제, 전체 삭제(종류 필터 범위) — 실수 방지를 위해 API 는 `confirm=true` 필요
  - 벤치마크: 결과 화면의 "이 결과 삭제", 이전 벤치마크 목록의 행별·선택·전체 삭제(선택한 데이터셋 범위 또는 전체)
- API: `POST /api/projection`, `POST /api/models/bulk-delete`, `GET /api/catalog/exclusions`, `POST /api/catalog/restore`, `GET /api/runs/summary`, `POST /api/runs/bulk-delete`, `DELETE /api/runs?confirm=true&kind=&dataset=`, `GET /api/runs?dataset=`, `GET /api/benchmarks/trend`, `GET /api/system/metrics`, 벤치마크 요청의 `sweep_dims`
- 의존성: `scikit-learn`(t-SNE), `peft`·`einops`(Jina v5 등 원격 코드 모델), `psutil`
- 파비콘 (콘솔 404 제거)
- `LICENSE`(MIT) — 프로젝트 소스·문서에만 적용, 임베딩 모델은 각 모델의 라이선스를 따름을 README·LICENSE에 명시

### 변경
- 대시보드의 "2026년 신규 공개 모델" 섹션을 **용도별 추천 모델**로 교체: 바로 사용 / 최근 공개 / 경량·CPU / 한국어 / 멀티모달 / 고성능·GPU 탭, 모델 상태에 맞는 다운로드·로드·테스트 버튼 제공. 카탈로그 태그와 메타데이터로 자동 분류하므로 모델을 추가해도 그대로 반영
- '최근 공개' 배지를 고정 태그 대신 공개일(최근 180일) 기준으로 계산

### 수정
- SQLite 에서 읽은 시각에 시간대가 빠져 화면에 UTC 가 현지 시각처럼(한국 기준 9시간 이르게) 표시되던 문제 — 모든 시각을 UTC 표시(`+00:00`)와 함께 반환
- Jina Embeddings v5 계열 로드 실패: `peft`·`einops` 추가, 카탈로그에 `default_task=retrieval` 로드 옵션 설정
- 카탈로그: Voyage 4 Nano 기본 차원 1024 → **2048** (MRL 2048/1024/512/256), Matryoshka 지원 누락 보완(Jina v5 Text Small/Nano/Omni, Granite Embedding 311M R2, pplx-embed v1 — Granite 97M R2는 미지원)
- Nomic Embed v1.5/v2가 transformers 5.x와 호환되지 않는 문제를 카탈로그 메모와 문서에 명시
- `docs/model-verification.md`: 대체 모델 정보 검증과 9개 모델 실측 벤치마크 추가

### 제거
- 카탈로그의 `new` 태그와 모델 목록의 "2026 신규" 태그 필터 (기존 DB의 `new` 태그는 시작 시 자동 정리)

## [0.1.0] - 2026-10-17

### 추가
- FastAPI 기반 임베딩 모델 관리·테스트 웹 앱 (Embedding Lab) 최초 공개
- **모델 카탈로그** (2026-10 기준, 37개): EmbeddingGemma 2(2026-10-06 공개), Nemotron-3-Embed, Harrier-OSS v1, Jina v5, Qwen3-VL-Embedding, pplx-embed, Voyage 4 Nano, Granite R2, LFM2.5, Qwen3-Embedding, BGE-M3, KURE 등
- Hugging Face Hub 실시간 검색, 메타데이터 자동 추출(프롬프트·차원·라이선스·trust_remote_code)로 모델 가져오기
- 백그라운드 다운로드(바이트 단위 진행률, ONNX/GGUF 등 불필요 파일 제외), 로컬 캐시 크기 표시·삭제
- 모델 로드/언로드, 최대 로드 수 초과 시 LRU 자동 언로드, 텍스트/멀티모달 프로필 분리 로드
- 모델별 query/document 프롬프트(prompt_name 또는 prefix)와 encode kwargs 자동 적용
- 플레이그라운드: 다중 모델 검색 비교, 유사도 행렬(히트맵), 임베딩 확인, Matryoshka 차원 축소
- 멀티모달 텍스트→이미지 검색 (EmbeddingGemma 2, Qwen3-VL-Embedding, Jina v5 Omni, CLIP)
- 벤치마크: 내장 한/영/교차언어 검색 셋, 한/영 STS 셋, 사용자 JSON 업로드, 언어별·쿼리별 분석
- SQLite 실행 이력 저장, 대시보드(시스템·메모리·로드 상태)
- pytest 테스트 (가짜 모델로 다운로드 없이 API·지표 검증)
