from functools import lru_cache
from pathlib import Path

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
    # 벡터 수가 이 이하인 인덱스는 근사(HNSW) 대신 정확 검색 — 평가 결과가 근사 오차에 흔들리지 않게
    vector_exact_max: int = 20000
    # 근사 검색 탐색 폭 (클수록 정확, 느림). 실제로는 max(이 값, top_k × 4)
    vector_ef_search: int = 200

    # ── 문서 검색 ────────────────────────────────────────────────────────────
    max_upload_mb: int = 100
    # 영상 프레임 추출: 몇 초마다 한 장, 최대 몇 장. 장면이 바뀌지 않은 프레임은 거른다(app/stages/multimodal/media.py).
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
