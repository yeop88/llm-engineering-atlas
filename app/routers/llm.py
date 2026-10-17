"""LLM 설정 확인·연결 시험."""

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas import LLMTestRequest
from app.services import llm

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/status")
def llm_status() -> dict:
    return llm.status()


@router.get("/models")
def llm_models(provider: str | None = None) -> dict:
    """설정된 OpenAI 호환 서버(로컬 llama.cpp·Ollama 등)에 올라온 모델 목록."""
    s = llm.get_settings()
    cfg = (
        llm.LLMConfig("openai", s.openai_model or "", s.openai_base_url.rstrip("/"), s.openai_api_key) if provider != "anthropic" else None
    )
    if cfg is None:
        return {"provider": "anthropic", "models": [s.anthropic_model]}
    try:
        return {"provider": "openai", "base_url": cfg.base_url, "models": llm.list_models(cfg)}
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/test")
async def llm_test(body: LLMTestRequest) -> dict:
    try:
        cfg = llm.resolve(body.provider, body.model)
        res = await run_in_threadpool(llm.chat, cfg, "간결하게 한국어로 답하세요.", body.prompt, 400)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"config": cfg.public(), **res}
