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
    max_loaded_models: int = 2
    default_batch_size: int = 16

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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.data_dir, settings.user_datasets_dir, settings.upload_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings
