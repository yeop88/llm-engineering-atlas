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
from app.stages.analytics import api as analytics_api  # noqa: E402
from app.stages.apps import api as apps_api  # noqa: E402
from app.stages.architecture import api as architecture_api  # noqa: E402
from app.stages.as_service import api as as_api  # noqa: E402
from app.stages.bigmodel import api as bigmodel_api  # noqa: E402
from app.stages.coding import api as coding_api  # noqa: E402
from app.stages.compliance import api as compliance_api  # noqa: E402
from app.stages.compress import api as compress_api  # noqa: E402
from app.stages.computer_use import api as computer_use_api  # noqa: E402
from app.stages.context import api as context_api  # noqa: E402
from app.stages.conversation import api as conversation_api  # noqa: E402
from app.stages.distill import api as distill_api  # noqa: E402
from app.stages.docintel import api as docintel_api  # noqa: E402
from app.stages.edge import api as edge_api  # noqa: E402
from app.stages.embedding import benchmarks_api, compat, models_api, playground_api  # noqa: E402
from app.stages.embedding.model_manager import get_manager  # noqa: E402
from app.stages.evalops import api as evalops_api  # noqa: E402
from app.stages.finetune import api as finetune_api  # noqa: E402
from app.stages.flywheel import api as flywheel_api  # noqa: E402
from app.stages.guardrails import api as guardrails_api  # noqa: E402
from app.stages.inference import api as inference_api  # noqa: E402
from app.stages.interop import api as interop_api  # noqa: E402
from app.stages.interp import api as interp_api  # noqa: E402
from app.stages.kg import api as kg_api  # noqa: E402
from app.stages.lineage import api as lineage_api  # noqa: E402
from app.stages.longrun import api as longrun_api  # noqa: E402
from app.stages.memory import api as memory_api  # noqa: E402
from app.stages.model_routing import api as model_routing_api  # noqa: E402
from app.stages.multiagent import api as multiagent_api  # noqa: E402
from app.stages.omni import api as omni_api  # noqa: E402
from app.stages.personalize import api as personalize_api  # noqa: E402
from app.stages.platform import api as platform_api  # noqa: E402
from app.stages.posttrain import api as posttrain_api  # noqa: E402
from app.stages.provenance import api as provenance_api  # noqa: E402
from app.stages.quant import api as quant_api  # noqa: E402
from app.stages.rag import answer_api, collections_api, eval_api, verify_api  # noqa: E402
from app.stages.reasoning import api as reasoning_api  # noqa: E402
from app.stages.rerank import api as rerank_api  # noqa: E402
from app.stages.rl import api as rl_api  # noqa: E402
from app.stages.rlvr import api as rlvr_api  # noqa: E402
from app.stages.routing import api as routing_api  # noqa: E402
from app.stages.serving import api as serving_api  # noqa: E402
from app.stages.tokenizer import api as tokenizer_api  # noqa: E402
from app.stages.training import api as training_api  # noqa: E402
from app.stages.voice import api as voice_api  # noqa: E402
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
            flywheel_api.run_watch()  # 배포 감시 · 자동 롤백(FW7, FLYWHEEL_WATCH_HOURS)
            platform_api.run_watch()  # 테넌트 예산 경보(PF7)
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
# 속도 제한(플랫폼 PF1)을 먼저 등록해야 안쪽에서 돈다 — 미들웨어는 나중에 등록한 것이 바깥이라, 인증이 사용자를 정한 뒤 센다
app.middleware("http")(platform_api.middleware)
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
    flywheel_api,  # 데이터 플라이휠 — 실패 분류 · 검토 · 게이트 · 단계적 배포
    platform_api,  # 엔터프라이즈 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용
    serving_api,  # 서빙 — 동시 부하 · 디코딩 설정 실측 · 예산 · 자원 현황
    posttrain_api,  # 후학습 — 데이터 · LoRA SFT · DPO · 병합 · 평가 · GGUF
    rlvr_api,  # RLVR — 검증 가능한 과제 · 환경 · 보상 · GRPO · 일반화
    edge_api,  # 온디바이스 · 엣지 — 기기 추천 · 기기용 팩 · 오프라인 · 동기화 · 국소 개인정보 처리
    voice_api,  # 실시간 음성 상담 — 인식 · 턴 관리 · 짧은 지연 RAG · 합성 · 감정 · 상담원 보조 · 통화 요약
    reasoning_api,  # 추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류
    context_api,  # 컨텍스트 엔지니어링 — 배치 · 긴 맥락 vs RAG · 압축 · 캐시 · 노트 · 오염 방지
    analytics_api,  # 데이터 분석 · Text-to-SQL — 스키마 연결 · 의미 계층 · 실행 검증 · 해석 · 권한 · 실행 정확도
    coding_api,  # 코딩 에이전트 — 코드 검색 · 계획 · 패치 · 테스트 실행 · 리뷰 · 해결률
    computer_use_api,  # 컴퓨터 사용 · 브라우저 에이전트 — 화면 이해 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가
    interp_api,  # 해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지
    memory_api,  # 장기 메모리 — 기억 추출 · 저장 · 연결 · 검색 · 갱신 · 통합 · 망각 · 계층 · 여러 세션 평가
    compress_api,  # 프롬프트 · KV 압축 — 토큰 · 질문 압축 · 주의 싱크 · 중요 토큰 KV · KV 양자화 · 압축 평가
    omni_api,  # 옴니채널 — 채널 통합 · 실시간 음성 · 영상 장면 · 턴 융합 · 이어 가기 · 비동기 메시지 · 채널별 형식 · 평가
    bigmodel_api,  # 적은 메모리로 큰 모델 — 메모리 계획 · 층 단위 스트리밍 · 전문가 오프로드 · 페이지 KV · 연속 배칭 · 극저비트 · 여러 기기
    inference_api,  # 추론 최적화 — 워크로드 측정 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트
    model_routing_api,  # 모델 라우팅 — 분류 · 위험 · 품질 하한 · 예산 · 후보 점수 · 승격 · 보정 · 채점
    provenance_api,  # 데이터 계보 · 근거 — 요청 → 청크 → 문서 · 판, 주장 · 근거 · 표시 일치, 부딪힘, 주장 단위 평가
    lineage_api,  # 기반 모델 계보 — GGUF 머리말 · HF 설정 · 모델 카드로 계열 · 구조 · 맥락 · 모달리티 · 라이선스
    tokenizer_api,  # 토크나이저 · 표현 공간 — 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 설정 비용
    architecture_api,  # Transformer · MoE 구조 — 층별 어텐션 · KV · FFN/전문가 · 바이트, KV 곡선, 맥락 길이별 미리 채우기
    training_api,  # 학습 생애주기 — 모델 하나의 데이터 · 학습 · 평가 · 배포 기록을 잇는 원장, 학습 데이터 감사
    personalize_api,  # 개인화 · 적응 — 동의 범위별 선호 · 행동 신호 → 프로필 → 응답 형식, 사실 보존 검사
    flow_api,  # 단계 연결 실행 — 단계 API 다음, 화면 앞
    pages,
):
    app.include_router(module.router)
