"""RAG 답변 생성: 검색 → 근거 번호를 인용한 LLM 답변(스트리밍) → 근거 검증."""

import json
import random
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core import crud, llm
from app.core.db import ChunkSet, Collection, EmbeddingModel, EvalSet, SessionLocal, VectorIndex
from app.core.jobs import Job, jobs
from app.core.vectorstores import StoreUnavailable
from app.pipeline.search import run_search  # 검색 향상(enhance) 등 다음 단계를 끼워 넣는 연결점
from app.stages.rag import answer, legal, service
from app.stages.rag.schemas import AnswerEvalRequest, AnswerRequest

router = APIRouter(prefix="/api", tags=["rag-answer"])


def _event(kind: str, **data: Any) -> str:
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


@router.post("/collections/{collection_id}/answer")
def generate_answer(collection_id: int, body: AnswerRequest) -> StreamingResponse:
    """NDJSON 스트림: search → delta(여러 번) → verify → judge(선택) → done. 오류는 error 이벤트."""
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}

    def stream() -> Iterator[str]:
        timings: dict[str, float] = {}
        with SessionLocal() as db:
            col = db.get(Collection, collection_id)
            if col is None:
                yield _event("error", message="컬렉션을 찾을 수 없습니다.")
                return
            models: list[str] = []
            try:
                if search_cfg.get("index_id"):
                    idx = db.get(VectorIndex, search_cfg["index_id"])
                    if idx is None or db.get(ChunkSet, idx.chunk_set_id).collection_id != col.id:
                        raise service.RagError("이 컬렉션의 인덱스가 아닙니다.")
                    models.append(idx.model_hf_id)
                if search_cfg.get("reranker_id") and (rr := db.get(EmbeddingModel, search_cfg["reranker_id"])):
                    models.append(rr.hf_id)
                t0 = time.perf_counter()
                res = run_search(db, body.question, search_cfg)
                timings["search_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            except (service.RagError, StoreUnavailable, ValueError) as exc:
                yield _event("error", message=f"검색 실패: {exc}")
                return
            results = answer.compress(res["results"], body.question, body.compress.keep) if body.compress else res["results"]
            context, sources = answer.build_context(results, body.max_context_chars)
            keep = ("rank", "chunk_id", "document_id", "filename", "title", "page", "heading", "text", "score", "media")
            yield _event(
                "search",
                sources=[{k: s.get(k) for k in keep} for s in sources],
                timings_ms=res.get("timings_ms"),
                llm=cfg.public(),
                enhance=res.get("enhance"),  # 검색 향상을 켰다면 LLM 이 만든 변형을 답변 화면에서도 확인할 수 있게
            )
            if not sources:
                yield _event("error", message="검색 결과가 없습니다.")
                return
            final: dict[str, Any] = {}
            images, note = answer.attach_images(db, sources, body.max_images) if body.images else ([], "")
            if images:
                timings["images"] = len(images)
            try:
                for ev in llm.chat_stream(
                    cfg, answer.SYSTEM, answer.user_prompt(body.question, context, note), body.max_tokens, body.temperature, images=images
                ):
                    if ev.get("done"):
                        final = ev
                    else:
                        yield _event("delta", text=ev["delta"])
            except llm.LLMError as exc:
                yield _event("error", message=str(exc))
                return
            text = final.get("text", "")
            timings["llm_s"] = final.get("seconds", 0)
            timings["ttft_s"] = final.get("ttft_s")
            check = answer.verify(text, sources, question=body.question)
            # 조문 · 판례 번호 검사(번호가 나온 답변만) — 번호만 바꾼 환각은 문장 검증으로 못 잡는다
            check["citations"] = legal.check_citations(text, sources, legal.lookup_fn_for(db, legal.chunk_set_of(db, search_cfg)))
            yield _event("verify", **check)
            judged = None
            if body.judge and check["sentences"]:
                try:
                    judged = answer.verify_llm(cfg, body.question, context, [s["text"] for s in check["sentences"]])
                    timings["judge_s"] = judged["seconds"]
                    yield _event("judge", **judged)
                except llm.LLMError as exc:
                    yield _event("judge", error=str(exc))
            summary = {
                "supported_ratio": check["supported_ratio"], "refused": check["refused"], "invalid_citations": check["invalid_citations"],
                "judge_supported_ratio": judged["supported_ratio"] if judged else None,
            }  # fmt: skip
            run = crud.record_run(
                db, "rag_answer", list(dict.fromkeys(models)) + [f"llm:{cfg.model}"], f"[{col.name}] {body.question}",
                body.model_dump(exclude={"question"}) | {"collection_id": col.id},
                {"answer": text, "summary": summary, "usage": final.get("usage"), "timings": timings,
                 "sources": [{"chunk_id": s["chunk_id"], "filename": s["filename"]} for s in sources]},
                timings["search_ms"] + timings["llm_s"] * 1000,
            )  # fmt: skip
            yield _event(
                "done",
                answer=text,
                usage=final.get("usage"),
                tokens_per_second=final.get("tokens_per_second"),
                timings=timings,
                run_id=run.id,
            )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/eval-sets/{set_id}/answer-eval", status_code=202)
def answer_eval(set_id: int, body: AnswerEvalRequest) -> dict:
    """평가 세트 질문마다 검색 → 답변 → 검증을 돌려 답변률·근거 인용률·문장 근거율을 집계한다 (작업)."""
    with SessionLocal() as db:
        s = db.get(EvalSet, set_id)
        if s is None or s.status != "ready":
            raise HTTPException(404, "준비된 평가 세트를 찾을 수 없습니다.")
        name, collection_id, items = s.name, s.collection_id, list(s.items)
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}
    title = f"답변 평가 · {name} · {cfg.model} · 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        rows = []
        with SessionLocal() as db:
            for i, it in enumerate(items):
                job.update(i / len(items), f"질문 {i + 1}/{len(items)}: {it['query'][:40]}")
                res = run_search(db, it["query"], search_cfg)
                row = answer.evaluate_one(cfg, it, res["results"], body.max_context_chars, body.max_tokens)
                rows.append(row | {"id": it.get("id"), "type": it.get("type"), "evidence": it.get("evidence", "")})
            summary = answer.summarize_eval(rows)
            out = {"eval_set": {"id": set_id, "name": name}, "llm": cfg.public(), "config": search_cfg, "summary": summary, "rows": rows,
                   "seconds": round(time.perf_counter() - started, 1)}  # fmt: skip
            run = crud.record_run(db, "rag_answer_eval", [f"llm:{cfg.model}"], title, body.model_dump() | {"eval_set_id": set_id, "collection_id": collection_id},
                                  out, out["seconds"] * 1000)  # fmt: skip
            out["run_id"] = run.id
        return out

    return jobs.submit("rag_answer_eval", title, work, eval_set_id=set_id).to_dict()
