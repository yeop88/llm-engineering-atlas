"""앱 시작 시 Alembic 마이그레이션 적용.

v0.1.0 은 create_all 로 테이블을 만들었으므로, 마이그레이션 기록(alembic_version)이 없는데
테이블이 이미 있으면 기준 리비전(0001)으로 표시(stamp)한 뒤 나머지를 적용한다.
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from app.config import BASE_DIR

BASELINE = "0001"


def _config(connection) -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False  # 앱 로깅 설정을 덮어쓰지 않음
    return cfg


def upgrade_to_head(engine: Engine) -> None:
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        cfg = _config(conn)
        if "alembic_version" not in tables and "embedding_models" in tables:
            command.stamp(cfg, BASELINE)
        command.upgrade(cfg, "head")
