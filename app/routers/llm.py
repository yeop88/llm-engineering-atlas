"""LLM 설정 확인·연결 시험."""

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas import LLMTestRequest
from app.services import llm

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/status")
def llm_status() -> dict:
    return llm.status()


@router.post("/test")
async def llm_test(body: LLMTestRequest) -> dict:
    try:
        cfg = llm.resolve(body.provider, body.model)
        res = await run_in_threadpool(llm.chat, cfg, "간결하게 한국어로 답하세요.", body.prompt, 200)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"config": cfg.public(), **res}
