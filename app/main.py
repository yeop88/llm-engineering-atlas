import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# huggingface_hub import 전에 설정해야 적용된다
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.core import auth, llm_api, system_api, tracing  # noqa: E402
from app.core.config import APP_DIR, get_settings  # noqa: E402
from app.core.crud import mark_interrupted, seed_catalog  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.jobs import jobs  # noqa: E402
from app.core.runtime import sampler  # noqa: E402
from app.pipeline import api as flow_api  # noqa: E402
from app.stages.agent import api as agent_api  # noqa: E402
from app.stages.apps import api as apps_api  # noqa: E402
from app.stages.as_service import api as as_api  # noqa: E402
from app.stages.compliance import api as compliance_api  # noqa: E402
from app.stages.conversation import api as conversation_api  # noqa: E402
from app.stages.distill import api as distill_api  # noqa: E402
from app.stages.docintel import api as docintel_api  # noqa: E402
from app.stages.embedding import benchmarks_api, compat, models_api, playground_api  # noqa: E402
from app.stages.embedding.model_manager import get_manager  # noqa: E402
from app.stages.evalops import api as evalops_api  # noqa: E402
from app.stages.finetune import api as finetune_api  # noqa: E402
from app.stages.guardrails import api as guardrails_api  # noqa: E402
from app.stages.interop import api as interop_api  # noqa: E402
from app.stages.kg import api as kg_api  # noqa: E402
from app.stages.longrun import api as longrun_api  # noqa: E402
from app.stages.multiagent import api as multiagent_api  # noqa: E402
from app.stages.quant import api as quant_api  # noqa: E402
from app.stages.rag import answer_api, collections_api, eval_api, verify_api  # noqa: E402
from app.stages.rerank import api as rerank_api  # noqa: E402
from app.stages.rl import api as rl_api  # noqa: E402
from app.stages.routing import api as routing_api  # noqa: E402
from app.web import pages  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def _periodic(stop: threading.Event) -> None:
    """1분마다: 주기가 된 문서 수집 소스(D1) · 정기 점검(레드팀 · 드리프트 · 회귀) · 통제 감사(RC8) · 하루 한 번 보관 기간 지난 요청 기록(G5) · 고객 프로필(C4) 정리.
    스케줄러 라이브러리 없이 — 할 일이 몇 가지뿐이고, 앱이 꺼지면 같이 멈춰야 해서(따로 도는 cron 은 앱 없이 DB 를 건드린다)."""
    last_purge = 0.0
    while not stop.wait(60):
        try:
            docintel_api.run_due()
            evalops_api.run_watch()  # 레드팀 · 드리프트 · 회귀 정기 점검(설정한 주기가 됐을 때만)
            compliance_api.run_watch()  # 통제 감사(RC8, WATCH_AUDIT_HOURS)
            if (now := time.time()) - last_purge > 86400:  # 하루 한 번: 보관 기간(0 = 지우지 않음)이 지난 요청 기록 · 고객 프로필
                with SessionLocal() as db:
                    n, m = tracing.purge(db), conversation_api.profile.purge(db)
                last_purge = now
                if n or m:
                    log.info("보관 기간이 지난 요청 기록 %d건 · 고객 프로필 %d건 정리", n, m)
        except Exception:  # 주기 작업 하나가 실패해도 스레드는 살아 있게
            log.exception("주기 작업 실패")


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
    stale += longrun_api.mark_interrupted()  # 돌던 업무는 '중단됨'으로 — 마지막 체크포인트부터 이어 하게
    log.info("카탈로그 seed: %d개 모델 추가 · 중단된 작업 정리 %d건", added, stale)
    if upgraded:
        log.warning("라이브러리 버전이 지난 호환성 점검 때와 다릅니다 — 모델 화면에서 점검을 권장합니다")
        if settings.compat_check_on_upgrade:
            jobs.submit("compat", "호환성 점검 (라이브러리 업그레이드 감지)", lambda j: compat.run_all(j, reason="upgrade"))
        if settings.regression_on_upgrade:  # 업그레이드가 검색 결과를 바꿨는지 회귀 세트로 바로 확인(E2)
            jobs.submit("regression", "회귀 평가 (라이브러리 업그레이드 감지)", lambda j: evalops_api.run_regressions(j, reason="upgrade"))
    sampler.start()
    stop = threading.Event()
    threading.Thread(target=_periodic, args=(stop,), name="periodic", daemon=True).start()
    yield
    stop.set()
    sampler.stop()
    jobs.shutdown()
    get_manager().unload_all()


app = FastAPI(
    title=get_settings().app_name,
    description="Global LLM system engineering lab · Korean-first — 임베딩 → RAG → 리랭킹 → 라우팅 → 소형/대형 모델",
    version="1.4.0",
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
    docintel_api,  # 운영 맵: 문서 처리 → 보안 · 가드레일 → 평가 · 관측 → 서비스 시나리오(AS)
    guardrails_api,
    evalops_api,
    conversation_api,
    as_api,
    kg_api,  # 지식 그래프 · GraphRAG — RAG 검색 · 서비스 답변 위에 그래프를 얹는다
    compliance_api,  # 규제 대응 — 가드레일 · 평가 · 대화 · 지식 그래프의 기록을 통제 증적으로 읽는다
    interop_api,  # 상호운용 — MCP(/mcp) · A2A(/a2a) 끝점과 도구 권한 · 상한 · 감사
    longrun_api,  # 장기 실행 업무 — 계획 · 체크포인트 · 승인 · 되돌리기
    multiagent_api,  # 멀티에이전트 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 출력
    flow_api,  # 단계 연결 실행 — 단계 API 다음, 화면 앞
    pages,
):
    app.include_router(module.router)
