from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Embedding Lab"
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

    # ── 문서 검색 ────────────────────────────────────────────────────────────
    max_upload_mb: int = 100
    index_batch_size: int = 32  # 인덱스 구축 시 한 번에 인코딩·저장할 청크 수
    reranker_max_length: int = 1024  # 리랭커 입력(질의+문서) 최대 토큰. 길수록 정확하지만 느림

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
