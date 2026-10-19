import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# huggingface_hub import 전에 설정해야 적용된다
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.core import auth, llm_api, system_api  # noqa: E402
from app.core.config import APP_DIR, get_settings  # noqa: E402
from app.core.crud import mark_interrupted, seed_catalog  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.jobs import jobs  # noqa: E402
from app.core.runtime import sampler  # noqa: E402
from app.pipeline import api as flow_api  # noqa: E402
from app.stages.agent import api as agent_api  # noqa: E402
from app.stages.apps import api as apps_api  # noqa: E402
from app.stages.distill import api as distill_api  # noqa: E402
from app.stages.embedding import benchmarks_api, compat, models_api, playground_api  # noqa: E402
from app.stages.embedding.model_manager import get_manager  # noqa: E402
from app.stages.finetune import api as finetune_api  # noqa: E402
from app.stages.quant import api as quant_api  # noqa: E402
from app.stages.rag import answer_api, collections_api, eval_api, verify_api  # noqa: E402
from app.stages.rerank import api as rerank_api  # noqa: E402
from app.stages.rl import api as rl_api  # noqa: E402
from app.stages.routing import api as routing_api  # noqa: E402
from app.web import pages  # noqa: E402

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
        stale = mark_interrupted(db)
        upgraded = compat.needs_check_after_upgrade(db)
    log.info("카탈로그 seed: %d개 모델 추가 · 중단된 작업 정리 %d건", added, stale)
    if upgraded:
        log.warning("라이브러리 버전이 지난 호환성 점검 때와 다릅니다 — 모델 화면에서 점검을 권장합니다")
        if settings.compat_check_on_upgrade:
            jobs.submit("compat", "호환성 점검 (라이브러리 업그레이드 감지)", lambda j: compat.run_all(j, reason="upgrade"))
    sampler.start()
    yield
    sampler.stop()
    jobs.shutdown()
    get_manager().unload_all()


app = FastAPI(
    title=get_settings().app_name,
    description="Global LLM system engineering lab · Korean-first — 임베딩 → RAG → 리랭킹 → 라우팅 → 소형/대형 모델",
    version="0.7.0",
    lifespan=lifespan,
)
app.middleware("http")(auth.middleware)  # API_TOKEN 이 있을 때만 막는다
app.mount("/static", StaticFiles(directory=APP_DIR / "web" / "static"), name="static")
# 공통 → 단계 순서 (흐름도 순서) → 화면
for module in (
    auth,
    system_api,
    llm_api,
    models_api,
    playground_api,
    benchmarks_api,
    collections_api,
    eval_api,
    answer_api,
    verify_api,
    finetune_api,
    rerank_api,
    routing_api,
    quant_api,
    distill_api,
    agent_api,
    rl_api,
    apps_api,
    flow_api,  # 단계 연결 실행 — 단계 API 다음, 화면 앞
    pages,
):
    app.include_router(module.router)
