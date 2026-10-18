"""8a 에이전트 API: 질문 하나를 에이전트로 풀며 단계를 스트리밍(NDJSON). 평가는 연결 실행의 연결 비교(에이전트 경로)로 한다."""

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core import crud, llm
from app.core.db import SessionLocal
from app.core.schemas import AgentRunRequest
from app.core.vectorstores import StoreUnavailable
from app.pipeline.search import run_search
from app.stages.agent import agent
from app.stages.rag import legal
from app.stages.rag.service import RagError

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _event(kind: str, **data: Any) -> str:
    return json.dumps({"type": kind, **data}, ensure_ascii=False, default=str) + "\n"


@router.post("/run")
def run(body: AgentRunRequest) -> StreamingResponse:
    """단계가 끝날 때마다 한 줄씩 보낸다 — 로컬 LLM 으로 단계마다 수 초~수십 초라, 끝까지 기다리게 하면 멈춘 것처럼 보인다."""
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    search_cfg = body.config.model_dump()

    def stream() -> Iterator[str]:
        started = time.perf_counter()
        with SessionLocal() as db:
            try:
                lookup_fn = legal.lookup_fn_for(db, legal.chunk_set_of(db, search_cfg)) if body.agent.lookup else None
                for ev in agent.run(cfg, body.question, lambda q: run_search(db, q, search_cfg)["results"], db=db,
                                    max_steps=body.agent.max_steps, top_k=body.agent.top_k, max_chars=body.agent.max_chars,
                                    lookup_fn=lookup_fn):  # fmt: skip
                    if ev["type"] == "final":
                        keep = ("chunk_id", "document_id", "filename", "page", "heading", "text")
                        ev = ev | {"sources": [{k: s.get(k) for k in keep} for s in ev["sources"]]}
                        run_ = crud.record_run(db, "agent", [cfg.model], f"에이전트 · {body.question[:60]}", body.model_dump(),
                                               {"answer": ev["answer"], "steps": ev["steps"], "verify": ev["verify"], "citations": ev.get("citations")},
                                               (time.perf_counter() - started) * 1000)  # fmt: skip
                        ev["run_id"] = run_.id
                    yield _event(ev.pop("type"), **ev)
            except (RagError, StoreUnavailable, ValueError, llm.LLMError) as exc:
                yield _event("error", message=str(exc))

    return StreamingResponse(stream(), media_type="application/x-ndjson")
