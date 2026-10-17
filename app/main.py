import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# huggingface_hub import 전에 설정해야 적용된다
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.config import BASE_DIR, get_settings  # noqa: E402
from app.crud import seed_catalog  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.routers import apps, benchmarks, llm, models, pages, playground, rag, rag_eval  # noqa: E402
from app.services.jobs import jobs  # noqa: E402
from app.services.model_manager import get_manager  # noqa: E402
from app.services.runtime import sampler  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.hf_token:
        os.environ.setdefault("HF_TOKEN", settings.hf_token)
    init_db()
    with SessionLocal() as db:
        added = seed_catalog(db)
    log.info("카탈로그 seed: %d개 모델 추가", added)
    sampler.start()
    yield
    sampler.stop()
    jobs.shutdown()
    get_manager().unload_all()


app = FastAPI(
    title=get_settings().app_name,
    description="오픈소스 임베딩 모델 카탈로그 관리 · 다운로드 · 테스트 · 벤치마크",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.include_router(models.router)
app.include_router(playground.router)
app.include_router(benchmarks.router)
app.include_router(rag.router)
app.include_router(rag_eval.router)
app.include_router(apps.router)
app.include_router(llm.router)
app.include_router(pages.router)
