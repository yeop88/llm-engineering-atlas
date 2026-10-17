from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LLM Engineering Atlas"
    data_dir: Path = BASE_DIR / "data"
    database_url: str | None = None

    # Hugging Face 액세스 토큰 (gated 모델 다운로드용, 예: google/embeddinggemma-300m)
    hf_token: str | None = None

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
    index_batch_size: int = 32  # 인덱스 구축 시 한 번에 인코딩·저장할 청크 수
    reranker_max_length: int = 1024  # 리랭커 입력(질의+문서) 최대 토큰. 길수록 정확하지만 느림

    # ── LLM (평가 질문 생성 등) ──────────────────────────────────────────────
    # openai = OpenAI 호환 API(OpenAI, vLLM, Ollama, LM Studio 등) | anthropic = Claude API. 비우면 키가 있는 쪽을 쓴다
    llm_provider: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_model: str | None = None  # 예: Ollama 는 qwen3:8b 처럼 서버에 받아 둔 모델 이름
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    llm_timeout: float = 120.0
    # Qwen3 계열처럼 '생각' 모드가 있는 모델에 생각을 끄라고 요청 (OpenAI 호환 로컬 서버만, 공식 OpenAI API 에는 보내지 않음)
    llm_disable_thinking: bool = True

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def datasets_dir(self) -> Path:
        return BASE_DIR / "app" / "data" / "datasets"

    @property
    def user_datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.data_dir, settings.user_datasets_dir, settings.upload_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings
