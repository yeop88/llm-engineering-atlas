"""RAG 답변 생성: 검색 → 근거 번호를 인용한 LLM 답변(스트리밍) → 근거 검증."""

import json
import random
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core import crud, llm
from app.core.auth import current_user
from app.core.db import ChunkSet, Collection, EmbeddingModel, EvalSet, SessionLocal, VectorIndex
from app.core.jobs import Job, jobs
from app.core.vectorstores import StoreUnavailable
from app.pipeline import serve  # 가드레일 · 요청 기록을 끼운 서비스 답변(입력 방어 · 권한 · 정책 · 개인정보 · 트레이스)
from app.pipeline.search import run_search  # 검색 향상(enhance) 등 다음 단계를 끼워 넣는 연결점
from app.stages.guardrails import acl, pii
from app.stages.rag import answer, service
from app.stages.rag.schemas import AnswerEvalRequest, AnswerRequest

router = APIRouter(prefix="/api", tags=["rag-answer"])


def _event(kind: str, **data: Any) -> str:
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


@router.post("/collections/{collection_id}/answer")
def generate_answer(collection_id: int, body: AnswerRequest, request: Request) -> StreamingResponse:
    """NDJSON 스트림: search → delta(여러 번) → verify → guard → judge(선택) → done. 오류는 error 이벤트.

    입력 방어 · 권한 · 근거 격리 · 출력 정책 · 개인정보 가리기 · 요청 기록은 연결 계층(pipeline/serve.py)이 한다 —
    AS 상담 · 레드팀 · A/B 실험과 같은 흐름. 개인정보는 흘려보내는 도중 문장 단위로 가린다(끝난 뒤 가리면 화면에 이미 나간 뒤라)."""
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = current_user(request)
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}
    search_cfg["acl_groups"] = acl.effective_groups(user, body.config.acl_groups)
    client = request.client.host if request.client else ""

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
                p = serve.prepare(db, body.question, search_cfg, user=user, mode=body.guard_mode,
                                  compress_keep=body.compress.keep if body.compress else None,
                                  max_context_chars=body.max_context_chars, images=body.images, max_images=body.max_images)  # fmt: skip
                timings["search_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            except (service.RagError, StoreUnavailable, ValueError) as exc:
                yield _event("error", message=f"검색 실패: {exc}")
                return
            yield _event(
                "search",
                sources=p.public_sources(),
                timings_ms=p.search_meta.get("timings_ms"),
                llm=cfg.public(),
                enhance=p.search_meta.get("enhance"),  # 검색 향상을 켰다면 LLM 이 만든 변형을 답변 화면에서도 확인할 수 있게
                guard_input=p.guard.get("input"),
                restricted=p.search_meta.get("restricted"),
            )
            if p.blocked:
                fin = serve.finish(db, p, "", cfg, client=client)
                yield _event("guard", **fin["guard"], answer=fin["answer"])
                yield _event("done", answer=fin["answer"], timings=timings, trace_id=fin["trace_id"], blocked=True, notice=fin["notice"])
                return
            if not p.sources:
                yield _event(
                    "error",
                    message="검색 결과가 없습니다." if not p.guard.get("restricted") else "볼 수 있는 문서에서 검색 결과가 없습니다.",
                )
                return
            if p.images:
                timings["images"] = len(p.images)
            final: dict[str, Any] = {}
            masker = pii.StreamMasker() if p.mode != "off" else None
            try:
                for ev in llm.chat_stream(cfg, p.system, p.prompt, body.max_tokens, body.temperature, images=p.images or None):
                    if ev.get("done"):
                        final = ev
                    elif masker is None:
                        yield _event("delta", text=ev["delta"])
                    elif out := masker.feed(ev["delta"]):
                        yield _event("delta", text=out)
                if masker is not None and (tail := masker.flush()):
                    yield _event("delta", text=tail)
            except llm.LLMError as exc:
                yield _event("error", message=str(exc))
                return
            text = final.get("text", "")
            timings["llm_s"] = final.get("seconds", 0)
            timings["ttft_s"] = final.get("ttft_s")
            fin = serve.finish(db, p, text, cfg, usage=final.get("usage"), llm_seconds=timings["llm_s"], client=client)
            check = fin["verify"]
            yield _event("verify", **check)
            # 정책으로 고쳤거나 거절했으면(enforce) 화면의 답을 바꿔 보여 준다 — 개인정보는 이미 흘려보낼 때 가렸다
            yield _event("guard", **fin["guard"], answer=fin["answer"] if fin["guard"].get("changed") else None)
            judged = None
            if body.judge and check["sentences"]:
                try:
                    judged = answer.verify_llm(cfg, body.question, p.context, [s["text"] for s in check["sentences"]])
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
                {"answer": fin["answer"], "summary": summary, "usage": final.get("usage"), "timings": timings, "trace_id": fin["trace_id"],
                 "sources": [{"chunk_id": s["chunk_id"], "filename": s["filename"]} for s in p.sources]},
                timings["search_ms"] + timings["llm_s"] * 1000,
            )  # fmt: skip
            yield _event(
                "done",
                answer=fin["answer"],
                usage=final.get("usage"),
                tokens_per_second=final.get("tokens_per_second"),
                timings=timings,
                run_id=run.id,
                trace_id=fin["trace_id"],
                notice=fin["notice"],  # AI 응답 고지(규제 대응 RC6) — 화면이 답 아래 같은 자리에 보인다
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
