# 아키텍처

## 코드 구조 — 흐름도의 단계 = 패키지

```
app/
  main.py            앱 생성, 시작 시 DB 마이그레이션 · 카탈로그 seed · 중단된 작업 정리, 라우터 등록(공통 → 단계 순서 → 화면)
  core/              모든 단계가 함께 쓰는 기반 (단계를 모른다 — 예외: 모델 카탈로그용 1 임베딩)
    config.py          설정(.env), 경로(BASE_DIR · APP_DIR)
    db.py · migrate.py SQLAlchemy 모델 · Alembic 자동 적용
    crud.py            모델 카탈로그 DB 헬퍼, 실행 이력 기록(record_run), 중단 작업 정리
    schemas.py         공용 스키마만(LLMRef · BulkDelete) — 단계의 요청 스키마는 각 단계의 schemas.py
    jobs.py            백그라운드 작업 큐(스레드 풀) + 작업 기록(job_records, 재시작해도 남음)
    auth.py            선택형 접근 토큰(API_TOKEN = 관리자) · 사용자별 토큰 · 그룹 · 역할(API_USERS), /api/me
    graphstore.py      지식 그래프 저장소: 앱 DB 노드 · 관계(원본) + Cypher 엔진(Neo4j · FalkorDB)으로 옮기기 · 읽기 전용 Cypher(EXPLAIN 쿼리 종류 · GRAPH.RO_QUERY)
    tracing.py         요청 기록(Trace): 단계별 시간 · 토큰 · 비용 · 검색 신호 · 검사 결과, 해시 체인(감사 무결성) · 보관 기간 정리
    runtime.py         디바이스 · dtype · 시스템 정보 · 메모리 표본
    stats.py           부트스트랩 신뢰구간 · 짝지은 비교
    llm.py · llm_api.py LLM 클라이언트(OpenAI 호환 · Claude, 스트리밍 · 그림 입력) · 연결 API
    korean.py          Kiwi 형태소 · 문장 분리 · 명사구
    media_store.py     이미지 · 영상 프레임 · 원본 파일(sha 별) 위치(data/media/doc-<id>/, data/uploads/) · 안전한 경로 해석
    vectorstores/      VectorStore 인터페이스 + Qdrant · pgvector · MariaDB (작은 인덱스는 정확 검색)
    system_api.py      작업 · 실행 이력 · 시스템 정보 API
  stages/            LLM 시스템 엔지니어링 맵의 단계 — 뒤 단계가 앞 단계를 가져다 쓴다
    <단계>/            로직 모듈 + schemas.py(요청 스키마) + api.py 또는 <주제>_api.py(HTTP API)
    embedding/         1 · 데이터 임베딩: catalog · hub · compat(호환성 점검) · model_manager · benchmark · public_benchmarks · projection, datasets/
    rag/               2 · RAG 검색: parsers · chunking · bm25 · fusion · service(검색·리랭킹) · evaluation · answer · verify · legal · public_corpus
    rerank/            3 · 리랭킹: llm_rerank(목록형) · evaluate
    search_lab/        4 · 검색 향상: enhance(질의 재작성 · HyDE · 다중 질의)
    finetune/          5 · 파인튜닝: data · trainer · service
    routing/           6 · 라우팅: routers(규칙 · 확신도 · LLM) · learned(학습 라우터) · service(라우터 채점)
    distill/ quant/    7a 지식 증류 · 7b 양자화
    agent/ rl/         8a 에이전트 · 8b 강화학습
    multimodal/        M · 멀티모달: ingest(이미지 · 영상 수집, 프레임 추출 · 같은 장면 제외)
    apps/              A · 의미 응용: 추천 · 분류 · 군집 · 중복 · 이상 · 키워드, presets/
    docintel/          문서 처리 맵(D1~D7): sources(폴더 수집) · parsing(점검 · OCR) · layout(표 · 그림) · clean(머리말 · 중복 · 판) ·
                       meta(메타 · 필터) · incremental(바뀐 문서만 재색인) · quality(청크 품질 · 근거 보존)
    guardrails/        보안 · 가드레일 맵(G1~G7): injection · pii · acl · policy · audit · license · redteam, presets/
    evalops/           평가 · 관측 맵(E1~E8): sets(버전 · 검토) · regression · monitor(대시보드) · feedback · drift · ab · loop ·
                       watch(레드팀 · 드리프트 · 회귀 정기 점검과 경보)
    conversation/      대화 · 메모리 맵(C1~C6): memory(규칙 사실 목록) · rewrite(후속 질문 풀어 쓰기) · clarify(되묻기) ·
                       compress(긴 대화 · 인계 요약) · profile(고객 프로필) · vocab(컬렉션의 제품 · 코드) · chat(한 턴) · evaluate, presets/
    kg/                지식 그래프 · GraphRAG 맵(K1~K8): ontology · extract(정형 + LLM 쟁점) · fusion(쟁점 합치기) · build ·
                       text2cypher · graphrag(이웃 확장 · 커뮤니티 요약 · 전체 질문) · evaluate, presets/(온톨로지 · 역량 질문)
    compliance/        규제 대응 맵(RC1~RC8): lawapi(국가법령정보 판) · corpus(조항 · 개정 비교) · scope(적용 규칙) · risk(등급) ·
                       register(처리 근거 · 파기) · explain(결정 기록) · reviews(사람 검토) · impact(영향 평가) · graph(조항-통제) ·
                       audit(통제 증적), catalog + presets/(규제 · 기능 · 규칙 · 통제 · 기준표 · 의무 질문)
    interop/           에이전트 상호운용 맵(IO1~IO6): tools(도구 · 범위 · 역할 정책) · mcp(MCP 서버 · 클라이언트) · sandbox(Docker 격리 실행) ·
                       a2a(에이전트 카드 · 받은 작업 · 맡기기 · 결과 검증) · limits(호출 · 시간 · 비용 상한) · audit(추적 id · 외부 결과 정리)
    longrun/           장기 실행 맵(LR1~LR7): actions(행동 · 보상 · 대체 · 멱등 발송) · plans(템플릿 · LLM 계획 · 계획 검사) ·
                       runner(실행 · 체크포인트 · 재시도 · 재계획 · 승인 대기 · 범위 · 되돌리기 · 중단 표시) · verify(완료 조건)
    multiagent/        멀티에이전트 맵(MA1~MA8): orchestrator(규칙 계획 · 칠판 · 흐름) · retrieval(Self-RAG · 비전 리랭킹) ·
                       analysis(코드 → 샌드박스 계산 · 차트) · writer(난이도별 모델) · critic(통과 · 수정 · 반려) · output(차트 · 그림 · 음성)
    flywheel/          데이터 플라이휠 맵(FW1~FW7): triage(실패 분류 · 추이) · review(검토 순서 · 평가 / 학습 분배 · 누수) ·
                       release(처방 · 게이트 · 단계적 배포 · 감시 · 롤백 — pipeline.search.default_config 가 pick 을 부름)
    platform/          엔터프라이즈 플랫폼 맵(PF1~PF7): gateway(속도 제한 · 사용량) · tenancy(테넌트 격리 — restrict 가 부름) ·
                       registry(프롬프트 버전 · 기능 플래그 — serve 가 부름) · resilience(차단기 · 대체 사슬) · chargeback(비용 배분 · 예산)
    serving/           서빙 맵(S1~S7): launcher(llama-server 설정별로 띄우기 · 메모리) · bench(동시 부하 · 디코딩 설정 비교) ·
                       budget(실측 후보 · 목표 안 최고 · 파레토 · 운영 준수) · resources(캐시 · 모델 · 장치 현황)
    posttrain/         후학습 맵(P1~P7): data(모으기 · 선별 · 누수) · trainer(LoRA SFT · DPO · 병합, transformers + peft) ·
                       local_llm(학습한 모델을 OpenAI 호환 끝점으로) · export(GGUF · 양자화)
    rlvr/              RLVR 맵(RV1~RV6): tasks(검증 가능한 과제 · 정답 확인) · env(기록 → 재생 · 환경-실제 차이) ·
                       reward(항목별 보상 · 해킹 감시) · policy(GRPO, posttrain.trainer 를 씀)
    edge/              온디바이스 · 엣지 맵(ED1~ED6): devices(기기 프로필 · 조합 추천) · pack(기기용 팩 · 압축 · 정확 검색 · 평가) ·
                       offline(기능 범위 · 미룸) · sync(판 증분 · 지문 확인 · 기기 상태) · privacy(전송 정책 · 서버 재검사)
    computer_use/      컴퓨터 사용 · 브라우저 에이전트 맵(CU1~CU6): sites(시험용 사이트 상태 기계) · browser(접근성 트리 · 행동 · 지문) ·
                       agent(행동 하나 · 상태 확인 · 승인 · 방어 설정 · 재생) · tasks(과제 · 최종 상태 판정 · 인젝션을 따랐나)
    coding/            코딩 에이전트 맵(CD1~CD6): index(함수 단위 색인 · BM25 · 기호 · 호출 그래프) · workspace(저장소 복사본 · 도구 · 돌연변이 과제) ·
                       agent(계획 · 걸음마다 도구 하나 · 테스트 피드백) · review(규칙 · LLM 리뷰), presets/
    analytics/         데이터 분석 · Text-to-SQL 맵(DA1~DA7): source(분석용 SQLite · 예시 자료) · schema(스키마 카드 · 연결 · 의미 계층) ·
                       agent(SQL 생성 · 실행 검증 · 해석 · 숫자 검사) · guard(읽기 전용 · 허가 콜백 · 상한) · evaluate(실행 정확도), presets/
    context/           컨텍스트 엔지니어링 맵(CX1~CX6): layout(배치 · 바늘 위치 · 긴 맥락 vs RAG · 프롬프트 캐시) ·
                       compact(기록 압축 · 세션 노트) · hygiene(맥락 오염 시험 · 막는 방법)
    reasoning/         추론 모델 맵(RS1~RS6): solve(예산 강제 · 풀이 저장소) · budget(예산 곡선 · 꺾이는 점 · 생각 라우터) ·
                       select(다수결 · 검증기 고르기 · pass@n · AUROC) · trace(생각 검사 · 증류 데이터) — 과제 · 환경은 rlvr
    voice/             실시간 음성 상담 맵(VC1~VC7): audio(16kHz · 운율) · turn(말소리 감지 · 끝점 · 끼어들기) · stt(엔진 · 용어 사전 · 표기 복원 · 오류율) ·
                       fastrag(지연 예산 · 문장 스트리밍) · speech(읽기 규칙 · 합성) · emotion(불만 · 이관) · assist(추천 · 채택률) · summary(양식 · 전사 일치), presets/
    as_service/        고객 AS 상담 맵(AS1~AS8): triage(의도 · 긴급도 · 코드) · photo(사진 코드 읽기) · flow(상담 흐름 · 캐시 · 티켓 · 지표) ·
                       setup(예시 매뉴얼), presets/
    registry/          맵 · 단계 설명(데이터만, 다른 앱 모듈을 불러오지 않음)
      model.py           Map · Page · Stage 구조와 문서 경로 규칙
      maps/<맵>.py       맵 1개 = 파일 1개: MAP(흐름 · 원칙 · 예시) + STAGES
      __init__.py        MAP_MODULES 순서로 모으기 · 조회(map_stages · map_flow · stage_for_nav)
  pipeline/          단계 연결 계층 — 단계들을 이어 붙이는 진입점
    search.py          run_search: 2 RAG 검색(+3 리랭킹)에 4 검색 향상을 끼움. 모든 검색 API 가 여기를 거침.
                       restrict: 권한(G3) · 메타 필터(D6) → 허용 문서(doc_ids)
    serve.py           서비스 답변: prepare(입력 방어 → 검색 → 근거 검사 · 격리 → 프롬프트) / finish(검증 → 출력 정책 · 개인정보 → 요청 기록),
                       answer_once — 답변 화면 · AS 상담 · A/B · 레드팀이 모두 거침
    flow.py · api.py   연결 실행기(4 → 1 → 2 → 3 → 6 → 7·8 → 답변), 연결 비교(/api/flow/*)
    schemas.py         경로 · 연결 설정(FlowPath · FlowConfig · RoutingConfig · 라우터 평가 요청)
  web/               화면 (자세히: guides/ui.md)
    pages.py           라우트 · 사이드바 · 위치 표시 · 빠른 이동 색인 — 레지스트리의 Page 로 만든다. 단계 밖 화면만 COMMON_PAGES, 예전 주소 넘김(REDIRECTS)
    templates/         base(사이드바 · 위쪽 바 · 서랍 · 대화상자) · dashboard · history · stage + <영역>/<화면>.html, maps/, settings/
    templates/_ui/     공용 매크로(page_header · field · empty · flow_box)
    static/js/lib/     공용 스크립트: common.js(api · html`` · ui.* · Ctx · 선택기) · shell.js(화면 뼈대 동작) · charts.js
    static/js/<영역>/<화면>.js   화면 스크립트 — 템플릿과 같은 구조(templates/rag/answer.html ↔ static/js/rag/answer.js)
tests/               app/ 와 같은 구조: core/ · pipeline/ · web/ · stages/<단계>/, 공용 helpers.py · conftest.py,
                     구조 규칙 test_architecture.py · 문서 test_docs.py
```

### 의존 방향과 배치 규칙 (`tests/test_architecture.py` 가 검사)

- `web · *_api → pipeline → stages → core`. 단계끼리는 흐름도 앞 단계만 가져다 씁니다(예: `rag` 는 `embedding.model_manager`, `finetune` 은 `rag.evaluation`). 앞 단계 화면에서 뒤 단계 기능을 켜야 하면(2 RAG 검색에서 4 검색 향상) 단계끼리 직접 부르지 않고 API 가 `pipeline` 을 부릅니다 — 단계 내부 로직은 `pipeline` 을 모릅니다. 예외로 `core` 의 모델 CRUD 는 1 임베딩의 모델 관리자 · 카탈로그 · 스키마를 씁니다.
- 요청 스키마는 그 단계의 `schemas.py` 에. 여러 단계 설정을 묶는 스키마(경로 · 연결)는 `pipeline/schemas.py`. `core/schemas.py` 는 공용만(80줄 미만 · 단계 import 없음).
- 레지스트리는 데이터만 — 앱의 다른 모듈을 불러오지 않습니다(화면 · 문서 생성이 무거운 모델 코드를 끌고 오지 않게). `maps/` 의 모든 파일이 `MAP_MODULES` 에 있어야 합니다.
- 화면 스크립트는 정적 파일로. 템플릿에는 서버 값 한 줄 설정(`const MODEL_ID = {{ model_id }};`)만 인라인으로 두고, `static/js/` 의 화면 파일은 짝이 되는 템플릿이 있어야 합니다(한 화면을 나누면 `<화면>_<부분>.js`).
- 테스트는 `app/` 와 같은 구조. 최상위에는 `conftest.py` · `helpers.py` · `test_architecture.py` · `test_docs.py` 만.
- 운영 맵 패키지는 LLM 맵 단계 뒤 순서: `docintel` → `guardrails` → `evalops` → `conversation` → `as_service`(AS 는 앞의 넷과 LLM 맵 단계를 씀) → `kg`(RAG 검색 · 서비스 답변 위에 그래프를 얹음). `rag` 는 이들을 모르므로 가드레일 · 기록은 `pipeline/serve.py` 가 붙입니다.
- 화면: 모든 화면은 `ui.page_header`, 이름표는 입력란과 연결, 삭제 확인은 `ui.confirm`(브라우저 `confirm()` 금지), 인라인 style · 손으로 부르는 `esc()` 는 늘리지 않음, 화면 링크는 새 주소로 — [화면 가이드](ui.md).

### 확장 체크리스트

**새 단계 (구현)** — 예: 리랭킹 고도화 · 라우팅 · 에이전트처럼 화면 · API 가 있는 단계

1. `app/stages/<단계>/` — 로직 모듈, `schemas.py`(요청 스키마), `api.py`(라우터, 블로킹 작업은 `def` 또는 `jobs.submit`)
2. `app/main.py` 라우터 목록(흐름도 순서), DB 가 필요하면 `core/db.py` 모델 + Alembic 리비전
3. 화면: `app/web/templates/<단계>/<화면>.html`(`ui.page_header`) + `app/web/static/js/<단계>/<화면>.js` — [화면 가이드](ui.md)
4. 레지스트리: `app/stages/registry/maps/<맵>.py` 의 단계 항목(상태 · `pages` · 원리 · 왜 · 어떻게 · 할 일). `pages` 의 `Page(nav, 주소, 이름, 설명, 템플릿)` 한 줄로 라우트 · 사이드바 · 위치 표시 · 빠른 이동이 생깁니다
5. 테스트: `tests/stages/<단계>/test_<주제>.py` (가짜 모델 · `tests/helpers.py` · 공용 픽스처 `scripted_llm` · `rag_collection`)
6. 문서: `docs/stages/<맵>/<번호>-<이름>/<단계>.md` 상세 · 실측, `uv run python scripts/gen_docs.py`, `CHANGELOG.md`, `docs/guides/api.md`

**새 맵** — 1. `app/stages/registry/maps/<맵>.py` 에 `MAP`(흐름 묶음 · 원칙 · 예시) + `STAGES` 2. `registry/__init__.py` 의 `MAP_MODULES` 에 한 줄 3. `uv run python scripts/gen_docs.py` (화면 `/maps/<맵>` · 개요 · 단계 문서가 생김). 전용 화면이 필요할 때만 `template` 을 지정하고 템플릿을 만듭니다.

**새 화면만** — 레지스트리 단계의 `pages` 에 `Page` 한 줄 + 템플릿 + 같은 경로의 화면 스크립트. 주소 규칙은 `/<단계>/<화면>`(화면이 하나면 `/<단계>`).

### 문서와 코드 맞추기

코드를 바꾼 커밋에 문서도 함께 고칩니다. 1.0 정리 때 파일을 옮기고 화면 주소를 바꾼 뒤 문서를 덜 고쳐 어긋남이 쌓였던 경험으로, 자주 빠뜨리는 것을 정리했습니다.

| 바꾼 것 | 함께 고칠 곳 |
|---|---|
| 파일 · 폴더 이동, 이름 변경 | 그 경로를 적은 모든 문서 · 주석, 위 코드 구조 그림 — `git grep -n "<예전 경로>" -- . ':!CHANGELOG.md' ':!docs/records'` 로 남은 곳 찾기 |
| 단계 설명 · 상태 · 화면 (레지스트리) | `uv run python scripts/gen_docs.py` (생성 문서), README 단계별 기능 표 |
| 화면 주소 | `app/web/pages.py` 의 `REDIRECTS`(예전 주소 넘기기), README '화면 구성' |
| 화면 이름 · 사이드바 위치 | 문서의 '사이드바 → …' 안내, README '처음 써보기' |
| 화면 뼈대 · 공통 부품 | [화면 가이드](ui.md) |
| API | [API](api.md) |
| 설정 · 의존성 · DB 스키마 | `.env.example` · README 기술 스택 · Alembic 리비전과 아래 모델 목록 |
| 실측 결론 | 그 단계 문서의 '실측' 절, 잘못된 결론은 정정 기록 |

테스트가 잡아 주는 것: 생성 문서가 레지스트리와 같은지 · 상대 링크와 제목 앵커(`tests/test_docs.py`), 문서에 적은 `app/…` · `tests/…` · `docs/…` 경로가 있는지와 화면 주소가 지금 주소인지(`scripts/check_docs.py`, 테스트에 포함), 구조 · 화면 규칙(`tests/test_architecture.py`), 화면 안 링크(`tests/web`). 문장으로 쓴 설명은 검사가 못 보므로 예전 이름으로 검색해 확인합니다. 문서에 일부러 예전 이름을 적는 줄에는 `<!-- 예전 이름 -->` 을 붙입니다.

## 요청 흐름

```
브라우저 (Jinja2 페이지 + 바닐라 JS)
   │  fetch /api/*
   ▼
FastAPI 라우터 ── core/system_api · llm_api / stages/*/…_api / web/pages
   │
   ├─ core/crud · db ─────────── 앱 DB (SQLite 기본, Alembic): 모델 · 실행 이력 · 컬렉션 · 평가 세트 · 파인튜닝 …
   ├─ stages/embedding/hub ───── Hugging Face Hub API, 로컬 캐시(~/.cache/huggingface/hub)
   ├─ stages/embedding/model_manager ─ SentenceTransformer · CrossEncoder 인스턴스 (메모리, LRU)
   ├─ core/jobs ──────────────── 백그라운드 작업 (다운로드 · 벤치마크 · 인덱스 · 평가 · 학습)
   └─ core/llm ───────────────── 로컬 LLM(OpenAI 호환) · Claude API
```

## 문서 검색 (RAG) 구성

```
업로드 ─ stages/rag/parsers ─▶ Document(pages)            ── 앱 DB (SQLite 기본, Alembic 관리)
            │
   ChunkSet(전략) ─ rag/chunking + core/korean(Kiwi 형태소) ─▶ Chunk(text, tokens)
            │
   VectorIndex(모델·저장소) ─ ModelManager.encode(document) ─▶ core/vectorstores/{qdrant|pgvector|mariadb}
            │
검색 ─ encode(query) → store.search ┐
     └ rag/bm25 (청크 세트별 메모리 캐시) ┴ rag/fusion(RRF/가중합) → ModelManager.rerank(CrossEncoder) → 결과
```

## 서비스 답변 흐름 (`pipeline/serve.py`)

```
질문 ─ G1 입력 방어 ─ 검색(run_search: G3 권한 · D6 메타 필터 → doc_ids) ─ G1 근거 속 지시 검사 · <근거> 격리 ─ LLM
     ─ 2 RAG 검증(근거 일치 · 질문 관련성 · 번호) ─ G4 출력 정책 · G2 개인정보 가리기 ─ E3 요청 기록(Trace, 해시 체인 G5)
```

- `GUARD_MODE`(요청마다 `guard_mode` 로 덮어쓰기): `off` 검사 · 기록만 / `mask` 개인정보 가림(기본) / `enforce` 인젝션 질문 차단 · 근거 속 지시 문장 빼기 · 정책 위반 수정 · 거절.
- 스트리밍 답변은 문장 단위로 모아 가립니다(`pii.StreamMasker`) — 번호가 조각으로 나뉘어 새지 않게.
- 화면마다 방어를 따로 붙이지 않는 이유: 한 곳만 빠져도 그 길로 샙니다. 답변 화면 · AS 상담 · A/B 실험 · 레드팀이 모두 같은 `prepare` / `finish` 를 거칩니다.
- 앱 안의 주기 스레드(`main._periodic`, 1분)가 주기가 된 수집 소스(D1)와 정기 점검(레드팀 · 드리프트 · 회귀, `WATCH_*_HOURS`)을 작업으로 띄우고, 하루 한 번 보관 기간이 지난 요청 기록을 지웁니다.

## DB 모델

| 테이블 | 모델 | 내용 |
|---|---|---|
| `embedding_models` · `catalog_exclusions` | EmbeddingModel · CatalogExclusion | 모델 카탈로그 |
| `verify_labels` | VerifyLabel | 답변 검증 사람 판정 |
| `test_runs` · `job_records` | TestRun · JobRecord | 실행 이력 · 작업 기록 |
| `collections` · `documents` · `chunk_sets` · `chunks` · `vector_indexes` | Collection · Document · ChunkSet · Chunk · VectorIndex | RAG 자료 · 청크 · 인덱스. 문서 메타(`meta`)에 종류 · 부서 · 제품 모델 · 날짜 · 권한(acl) · 판 · 원본 · 바뀐 시각 |
| `eval_sets` | EvalSet | 평가 세트(+ 버전 · 회귀 지정 · 기준선 · 변경 이력, 0010) |
| `finetune_runs` · `preference_pairs` · `app_models` | FinetuneRun · PreferencePair · AppModel | 파인튜닝 · 선호 쌍 · 의미 응용 모델 |
| `traces` | Trace | 요청 기록 · 감사 로그(0010) |
| `experiments` | Experiment | A/B 실험(0010) |
| `answer_cache` | AnswerCache | AS 의미 캐시(0010) |
| `as_sessions` | AsSession | AS 상담 · 티켓(0010) |
| `ingest_sources` | IngestSource | 폴더 수집 소스(0010) |
| `profiles` | Profile | 고객 프로필 — 보유 제품 · 지난 문의 요약(0011) |
| `kg_nodes` · `kg_edges` | KgNode · KgEdge | 지식 그래프 노드 · 관계 — (graph, label, key) · (graph, src, dst, type) 유일(0012) |
| `compliance_records` | ComplianceRecord | 규제 대응의 사람 판단 — 위험 등급 · 처리 근거 등록 · 영향 평가 · 사람 검토 요청(0013) |
| `interop_tasks` · `tool_calls` | InteropTask · ToolCall | A2A 위임 작업(멱등 키 · 시도) · 도구 호출 · 위임 감사(추적 id · 외부 결과)(0014) |
| `lr_runs` · `lr_steps` | LrRun · LrStep | 장기 실행 업무(계획 · 범위 · 기록 · 판정) · 단계 체크포인트(결과 · 시도 · 멱등 키 · 승인자)(0015) |
| `fw_versions` · `fw_reviews` | FwVersion · FwReview | 플라이휠 버전(설정 · 게이트 · 배포 비율 · 기록) · 사람 검토(판정 · 분배 · 누수)(0016) |
| `pf_tenant_collections` · `pf_prompts` · `pf_flags` · `pf_budgets` | PfTenantCollection · PfPrompt · PfFlag · PfBudget | 컬렉션 테넌트 · 프롬프트 버전 · 기능 플래그 · 테넌트 월 예산(0017) |
| `edge_devices` · `edge_events` | EdgeDevice · EdgeEvent | 기기(받은 팩 · 판 · 마지막 동기화) · 기기가 올린 기록 · 피드백 · 미룬 요청(서버 재검사 위반)(0018) |
| `voice_calls` | VoiceCall | 음성 상담 통화(턴: 전사 · 운율 · 감정 · 단계별 지연, 추천과 채택, 끼어들기 · 이관 사건, 요약)(0019) |

마이그레이션은 `migrations/versions/0001_initial` … `0019_voice` 입니다.

## 검색 저장 방식

- 청크 id 를 벡터 DB 의 포인트 id 로 쓰고, 문서 id 를 함께 저장해 문서 필터에 씁니다. 벡터 DB 쪽 이름은 `el_vi_{인덱스 id}` 입니다.
- BM25 는 문서 쪽 가중치를 미리 계산한 희소 행렬(scipy)로 메모리에 두고, 청크 수·최대 id 가 바뀌면 다시 만듭니다.
- 청크 세트 생성·인덱스 구축은 백그라운드 작업(`jobs`)이고, 실패하면 상태가 `error` 로 남아 화면에서 다시 구축할 수 있습니다.

## 모델 상태

| 상태 | 의미 | 판단 근거 |
|---|---|---|
| 등록됨 | 카탈로그(DB)에 있음 | `embedding_models` 테이블 |
| 다운로드됨 | 로컬 HF 캐시에 파일 있음 | `scan_cache_dir()` (5초 캐시) |
| 로드됨 | 메모리에 SentenceTransformer 인스턴스 존재 | `ModelManager._models` |

다운로드 없이 바로 로드해도 SentenceTransformer가 필요한 파일을 자동으로 받습니다. "다운로드" 버튼은 진행률을 보며 미리 받아 두는 용도입니다.

## 모델 로딩 (`ModelManager`)

- 키: `"{hf_id}::{profile}"` — profile은 `text` 또는 `multimodal`.
  - EmbeddingGemma 2는 `text` 프로필에서 `config_kwargs={"vision_config": None, "audio_config": None}`로 270M 텍스트 경로만 올리고, `multimodal` 프로필에서는 비전 인코더를 포함합니다. 두 프로필은 같은 체크포인트라 **같은 벡터 공간**입니다.
- dtype: `DTYPE=auto`이면 CUDA+bf16 지원 시 bfloat16, 그 외 float32. float16은 명시적으로 지정할 때만 사용합니다.
- `MAX_LOADED_MODELS`를 넘으면 가장 오래 사용하지 않은 모델부터 언로드합니다.
- 같은 모델을 동시에 두 번 로드하지 않도록 키별 락을 씁니다. 인코딩도 모델별 락으로 직렬화합니다.
- DB에서 모델 설정(프롬프트, 로드 kwargs 등)을 바꾸면 `ModelSpec`이 달라지므로 다음 사용 시 자동으로 다시 로드됩니다.
- 로드 후 실제 임베딩 차원을 DB에 반영하고, 토크나이저에 최대 길이가 없으면 카탈로그의 `max_seq_len`으로 제한합니다.

## 프롬프트 적용 규칙

`ModelManager.encode(..., role)`의 role이 `query`/`document`일 때:

1. `query_prompt`/`document_prompt`(prompt_name)가 모델의 `prompts`에 있으면 `prompt_name=`으로 전달
2. 없으면 경고를 남기고 무시
3. `query_prefix`/`document_prefix`가 있으면 텍스트 앞에 직접 붙임
4. `query_kwargs`/`document_kwargs`를 encode에 추가 전달 (예: Jina v3의 `task`)

`plain`은 아무것도 적용하지 않습니다(모델의 `default_prompt_name`은 SentenceTransformer가 자동 적용). 유사도 행렬과 STS 벤치마크는 기본적으로 `plain`을 씁니다.

## 백그라운드 작업

`jobs.submit(kind, title, fn)` → ThreadPoolExecutor(2 workers). 계산은 메모리에서 돌고 상태 · 진행률 · 결과는 DB(`job_records`)에도 남깁니다 — 재시작하면 끝나지 않은 작업은 '중단됨'으로 표시합니다(파인튜닝 · 평가 세트 생성도 같이 정리). 벤치마크 결과는 완료 시 `test_runs`에 저장됩니다. 다운로드 진행률은 `snapshot_download(tqdm_class=...)`의 바이트 진행 바를 가로채 계산합니다.

## 데이터 저장 위치

| 데이터 | 위치 |
|---|---|
| 벡터 (Qdrant 로컬 모드) | `data/qdrant` (서버/pgvector/MariaDB 는 각 DB) |
| DB 마이그레이션 | `migrations/` (Alembic) |
| 앱 DB | `data/app.db` (`DATA_DIR`) |
| 업로드 원본 (sha 별, 다시 파싱 · OCR 용) | `data/uploads/<sha 앞 2글자>/` |
| 폴더 수집 기본 위치 | `data/inbox` (`INGEST_ROOTS` 로 더 허용) |
| AS 예시 자료 · 레드팀 공격 세트 | `app/stages/as_service/presets/` · `app/stages/guardrails/presets/` |
| 사용자 데이터셋 | `data/datasets/*.json` |
| 내장 데이터셋 | `app/stages/embedding/datasets/*.json` |
| 의미 응용 예시 데이터 | `app/stages/apps/presets/*.json` |
| 학습한 모델 | `data/finetuned/ft-{실행 번호}/` (모델 · train_pairs.jsonl · README.md 기록) |
| 모델 파일 | `~/.cache/huggingface/hub` (`HF_HOME`/`HF_HUB_CACHE`로 변경) |
