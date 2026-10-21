from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # 저장소 루트 (app/core/config.py 기준)
APP_DIR = BASE_DIR / "app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LLM Engineering Atlas"
    # 화면의 문서 링크가 가리키는 저장소 (docs/*.md 를 GitHub 에서 연다)
    repo_url: str = "https://github.com/yeop88/llm-engineering-atlas"
    data_dir: Path = BASE_DIR / "data"
    database_url: str | None = None

    # Hugging Face 액세스 토큰 (gated 모델 다운로드용, 예: google/embeddinggemma-300m)
    hf_token: str | None = None

    # 선택형 접근 토큰. 비우면 인증 없음(로컬 혼자 쓰기). 서버 · 사내망에 올릴 때는 꼭 설정 (app/core/auth.py)
    api_token: str | None = None
    auth_cookie_days: int = 14
    auth_cookie_secure: bool = False  # HTTPS 뒤에서만 쿠키를 보내려면 true
    # 사용자별 토큰 · 그룹 · 역할 (권한별 검색 · 감사 로그용). API_TOKEN 은 모든 문서를 보는 관리자 토큰으로 남는다.
    # 예: [{"name": "hr-kim", "token": "…", "groups": ["hr"], "role": "user"}] — 그룹이 붙은 문서는 그 그룹 사용자만 검색된다
    api_users: list[dict[str, Any]] = []
    # 요청 기록(트레이스 · 감사 로그) 보관 일수. 0 = 지우지 않음. 지울 때도 해시 사슬은 남은 첫 행부터 다시 검사한다
    trace_retention_days: int = 0
    # 모델별 단가(원 또는 달러, 100만 토큰당 [입력, 출력]) — 비용 대시보드용. 로컬 모델은 비워 두면 0
    llm_prices: dict[str, list[float]] = {}
    # 출력 정책 · 개인정보 가리기를 답변에 적용 (보안 · 가드레일 맵). off = 검사만 하고 기록, mask = 개인정보만 가림, enforce = 위반 시 수정 · 거절
    guard_mode: str = "mask"
    # 문서 수집 소스(폴더)로 허용하는 상위 경로들. 비우면 data/inbox 만 — 서버의 아무 폴더나 읽지 못하게
    ingest_roots: list[Path] = []
    # 라이브러리 업그레이드를 감지하면 시작할 때 회귀 세트를 자동으로 다시 잰다(평가 · 관측 E2). 임베딩 · 검색만이라 LLM 은 쓰지 않는다
    regression_on_upgrade: bool = False
    # 정기 점검(평가 · 관측): 몇 시간마다 다시 돌릴지(0 = 끔). 레드팀은 로컬 LLM 으로 37문항 약 2~6분, 드리프트 · 회귀는 임베딩만
    watch_redteam_hours: float = 0
    watch_redteam_mode: str = "enforce"
    watch_drift_hours: float = 0
    watch_drift_collection_id: int | None = None  # 비우면 모든 요청 기록
    watch_regression_hours: float = 0
    # 정기 점검 경보를 보낼 주소(POST JSON). 비우면 화면(요청 기록 · 비용)에만 표시
    alert_webhook: str | None = None
    # 고객 프로필(대화 · 메모리 C4: 보유 제품 · 지난 문의 요약) 보관 일수. 0 = 지우지 않음. 개인정보는 넣지 않지만 오래 두지 않는다
    profile_retention_days: int = 90
    # 고객 AS 상담(AS1 · AS7): 음성 인식 서버(OpenAI 호환 /audio/transcriptions, 예: whisper.cpp server)와 티켓을 보낼 외부 접수 시스템 주소
    stt_url: str | None = None
    stt_model: str = "whisper-1"
    as_ticket_webhook: str | None = None
    # 규제 대응(RC1 · RC7): 국가법령정보 공동활용 API 키(open.law.go.kr 에서 신청한 이메일 아이디). 비우면 법령 판 받기 · 개정 감시를 끔
    law_api_oc: str = ""
    # 규제 대응(RC6): 서비스 답변에 붙이는 AI 응답 고지(인공지능 기본법 제31조 — 사전 고지 · 생성물 표시). 비우면 고지를 붙이지 않음
    ai_notice: str = "AI 가 자료를 찾아 작성한 답변입니다. 법률 자문이 아니며, 사람의 검토를 요청할 수 있습니다."
    # 규제 대응(RC8): 통제 감사(증적 모으기)를 몇 시간마다 다시 돌릴지(0 = 끔). LLM 없이 기록만 본다
    watch_audit_hours: float = 0
    # 에이전트 상호운용(IO5): 세션 · 위임 하나가 쓸 수 있는 도구 호출 수 · 시간(초) · 비용(달러, 0 = 상한 없음)
    interop_max_calls: int = 20
    interop_max_seconds: float = 120
    interop_max_cost: float = 0
    # 실행 도구 샌드박스(IO2): Docker 가 있으면 이 이미지로 네트워크 없이, 없으면 격리가 약한 별도 프로세스로(화면에 표시)
    sandbox_image: str = "python:3.13-slim"
    sandbox_timeout: float = 10
    # 외부 MCP 서버 · A2A 상대 에이전트: [{"name", "url", "token"?}] (JSON). 이 앱 자신도 넣어 시험할 수 있다
    mcp_servers: list[dict[str, Any]] = []
    a2a_peers: list[dict[str, Any]] = []
    # 엔터프라이즈 플랫폼(PF1): 사용자 · 테넌트당 분당 요청 상한(0 = 끔), 개별 상한 {"사용자" 또는 "tenant:이름": n}
    rate_limit_per_min: int = 0
    rate_limit_overrides: dict[str, int] = {}
    # 장애 대응(PF6): 기본 LLM 이 멈추면 차례로 넘길 대체 모델 [{"provider", "model", "base_url"?}]
    llm_fallbacks: list[dict[str, Any]] = []
    # 데이터 플라이휠(FW7): 배포 감시 주기(시간, 0 = 끔) — 나빠지면 자동 롤백. 좋을 때 다음 비율로 자동 진행할지(기본은 사람이)
    flywheel_watch_hours: float = 0
    flywheel_auto_advance: bool = False
    # 멀티에이전트(MA6): 쉬운 작성을 맡길 소형 모델(OpenAI 호환). 비우면 기본 LLM 이 모두 쓴다
    small_llm_model: str | None = None
    small_llm_base_url: str | None = None
    # 멀티모달 출력(MA8): 음성 합성 서버(OpenAI 호환 /audio/speech). 비우면 글 · 차트 · 그림만
    tts_url: str | None = None
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"

    # 라이브러리(sentence-transformers · transformers · torch) 버전이 지난 점검 때와 다르면 시작할 때 내려받은 모델을 자동 점검.
    # 모델을 하나씩 올려 보므로 CPU 에서는 몇 분 걸린다 — 기본은 끄고 화면에서 '점검 권장'만 알린다.
    compat_check_on_upgrade: bool = False

    # auto | cpu | cuda | mps
    device: str = "auto"
    # auto | float32 | bfloat16  (EmbeddingGemma 계열은 float16 미지원)
    dtype: str = "auto"
    # 메모리에 동시에 올려둘 최대 모델 수 (초과 시 가장 오래 사용 안 한 모델부터 언로드)
    max_loaded_models: int = 3
    default_batch_size: int = 16

    # ── 벡터 DB ─────────────────────────────────────────────────────────────
    # 기본 저장소: qdrant | pgvector | mariadb  (인덱스마다 따로 고를 수도 있음)
    vector_store: str = "qdrant"
    # Qdrant: URL 이 없으면 서버 없이 로컬 파일 모드(data/qdrant)로 동작
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    # PostgreSQL + pgvector (docker compose --profile pgvector up -d)
    pgvector_url: str | None = None  # 예: postgresql://embedding:embedding@localhost:5433/embedding_lab
    # MariaDB 11.7+ VECTOR (docker compose --profile mariadb up -d)
    mariadb_url: str | None = None  # 예: mysql://embedding:embedding@localhost:3307/embedding_lab
    # 지식 그래프의 Cypher 실행(Text2Cypher K6)용 Neo4j. 비우면 앱 DB 의 내장 그래프만(이웃 확장 · 커뮤니티는 동작)
    neo4j_url: str | None = None  # 예: bolt://localhost:7687 (docker compose --profile neo4j up -d)
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    # 두 번째 Cypher 엔진 FalkorDB (docker compose --profile falkordb up -d). 예: redis://localhost:6380
    falkordb_url: str | None = None
    # Cypher 를 돌릴 엔진: neo4j | falkordb — 화면 · API 에서 요청마다 바꿀 수 있고, 비우면 설정된 쪽(둘 다면 neo4j)
    graph_engine: str = ""
    # 벡터 수가 이 이하인 인덱스는 근사(HNSW) 대신 정확 검색 — 평가 결과가 근사 오차에 흔들리지 않게
    vector_exact_max: int = 20000
    # 근사 검색 탐색 폭 (클수록 정확, 느림). 실제로는 max(이 값, top_k × 4)
    vector_ef_search: int = 200

    # ── 문서 검색 ────────────────────────────────────────────────────────────
    max_upload_mb: int = 100
    # 영상 프레임 추출: 몇 초마다 한 장, 최대 몇 장. 장면이 바뀌지 않은 프레임은 거른다(app/stages/multimodal/ingest.py).
    video_frame_interval: float = 2.0
    video_max_frames: int = 240
    index_batch_size: int = 32  # 인덱스 구축 시 한 번에 인코딩·저장할 청크 수
    reranker_max_length: int = 1024  # 리랭커 입력(질의+문서) 최대 토큰. 길수록 정확하지만 느림

    # ── LLM (평가 질문 생성 등) ──────────────────────────────────────────────
    # openai = OpenAI 호환 API(OpenAI, vLLM, Ollama, LM Studio 등) | anthropic = Claude API. 비우면 키가 있는 쪽을 쓴다
    llm_provider: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_model: str | None = None  # 예: Ollama 는 qwen3:8b 처럼 서버에 받아 둔 모델 이름
    # 모델 이름 → 서버 주소. llama-server 는 서버 하나에 모델 하나라, 소형 · 양자화 모델을 다른 포트에 띄워 라우팅의 빠른 경로에
    # 쓰려면 모델마다 주소가 필요하다. 예: {"gemma-4-e4b-q2": "http://127.0.0.1:8082/v1"} (없는 모델은 OPENAI_BASE_URL)
    openai_model_urls: dict[str, str] = {}
    # 로컬 GGUF 파일 폴더 — 양자화 화면이 파일 목록 · 크기를 보여 주고 llama-server 실행 명령을 만들 때 쓴다(선택)
    llm_models_dir: Path | None = None
    # 후학습(P3~P7): LoRA SFT · DPO 의 기본 모델(Hub id) — CPU 에서도 돌도록 작은 모델. GGUF 변환은 llama.cpp 의 convert_hf_to_gguf.py
    posttrain_base_model: str = "Qwen/Qwen3-0.6B"
    llama_convert_script: Path | None = None
    # 서빙 실측(S5): llama-server 실행 파일 — 있으면 앱이 KV 캐시 · 추측 디코딩 설정별로 서버를 직접 띄워 비교한다(빈 포트 18100~)
    llama_server_bin: Path | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    llm_timeout: float = 120.0
    # Qwen3 계열처럼 '생각' 모드가 있는 모델에 생각을 끄라고 요청 (OpenAI 호환 로컬 서버만, 공식 OpenAI API 에는 보내지 않음)
    llm_disable_thinking: bool = True
    # 답변 근거 검증 방식: lexical(글자 겹침, 기본) · semantic(임베딩 유사도) · hybrid(둘 중 하나라도 통과).
    # 답변 평가 · 연결 비교 · 보상이 모두 이 방식을 쓴다. 사람 판정과의 일치도(/rag/verify)를 보고 고른다.
    answer_verify_method: str = "lexical"
    verify_model: str = "nlpai-lab/KURE-v1"  # 의미 검증용 임베딩 모델(카탈로그의 hf_id)
    verify_semantic_ok: float = 0.80  # 잠정값 — 라벨로 훑은 최적 문턱으로 바꿀 것
    verify_semantic_weak: float = 0.65
    # 질문 관련성: 답변 문장이 질문에 답하는가(근거에 있어도 질문과 상관없는 문장은 틀린 답). 질문-문장 의미 유사도(VERIFY_MODEL)
    # 기준값 0.68 = 법률 답변 문장 28개 사람 판정으로 고른 잠정값(카파 0.72, 같은 라벨로 고르고 쟀으므로 낙관적) — 라벨이 늘면 다시 고른다
    answer_relevance: bool = True
    verify_relevance_ok: float = 0.68

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def datasets_dir(self) -> Path:
        return APP_DIR / "stages" / "embedding" / "datasets"

    @property
    def user_datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def inbox_dir(self) -> Path:
        """문서 수집 소스의 기본 허용 폴더(INGEST_ROOTS 를 비우면 여기만)."""
        return self.data_dir / "inbox"

    @property
    def media_dir(self) -> Path:
        """이미지 · 영상 원본과 추출한 프레임. 문서마다 doc-<id>/ 폴더 — 문서를 지울 때 폴더째 지우면 되게."""
        return self.data_dir / "media"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.data_dir, settings.user_datasets_dir, settings.upload_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings
