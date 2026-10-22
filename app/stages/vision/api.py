"""이미지 · Vision-Language API (VL1~VL7). 영역 · 꺾임은 규칙이라 바로, 읽기 · 답하기 · 비교는 비전 LLM 을 부른다."""

import base64
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config
from app.stages.vision import pipeline, see, synth
from app.stages.vision.schemas import EvalIn

router = APIRouter(prefix="/api/vision", tags=["vision"])
DB = Annotated[Session, Depends(get_db)]


def _image(
    file: UploadFile | None, code: str | None, seed: int, hard: bool, far: bool
) -> tuple[Any, dict[str, Any], dict[str, Any] | None]:
    if file is not None:
        try:
            im, info = see.inspect_input(file.file.read())
        except Exception as exc:  # noqa: BLE001 — 그림이 아닌 파일
            raise HTTPException(400, f"그림을 열 수 없습니다: {type(exc).__name__}") from exc
        return im, info, None
    im, truth = synth.make(code or "E4", seed=seed, hard=hard, far=far)
    return im, {"format": "합성", "size": list(im.size), "gps_removed": False}, truth


def _lcfg(provider: str | None, model: str | None) -> llm.LLMConfig:
    return llm.resolve(provider or None, model or None)


@router.get("/sample.png")
def sample(code: str = "E4", seed: int = 0, hard: bool = False, far: bool = False) -> Response:
    im, _ = synth.make(code[:4], seed=seed, hard=hard, far=far)
    return Response(pipeline.png(im), media_type="image/png")


@router.post("/look")
def look(file: Annotated[UploadFile | None, File()] = None, code: Annotated[str | None, Form(max_length=4)] = None, seed: Annotated[int, Form()] = 0,
         hard: Annotated[bool, Form()] = False, far: Annotated[bool, Form()] = False, read: Annotated[bool, Form()] = True,
         provider: Annotated[str | None, Form()] = None, model: Annotated[str | None, Form()] = None) -> dict:  # fmt: skip
    """VL1~VL5 · VL7: 입력 확인 → 표시창 · 호스 영역 · 꺾임 → (read 면) 표시창만 읽기 → 영역 그림."""
    im, info, truth = _image(file, code, seed, hard, far)
    known = pipeline.CODES
    r = pipeline.split(_lcfg(provider, model) if read else None, im, known)
    img = r.pop("image")
    return {"input": info, "truth": truth, "display": r["display"], "hose": r["hose"], "kinked": r["kinked"], "steps": r["steps"], "code": r.get("code"),
            "raw_code": r.get("raw_code"), "snapped": r.get("snapped"), "read_on": r.get("read_on"), "regions": r["regions"], "seconds": r["seconds"],
            "overlay": "data:image/png;base64," + base64.b64encode(see.overlay(img, r["regions"])).decode()}  # fmt: skip


@router.post("/answer")
def answer(question: Annotated[str, Form(min_length=1, max_length=500)], collection_id: Annotated[int, Form()], db: DB,
           file: Annotated[UploadFile | None, File()] = None, code: Annotated[str | None, Form(max_length=4)] = None, seed: Annotated[int, Form()] = 0,
           hard: Annotated[bool, Form()] = False, far: Annotated[bool, Form()] = False,
           provider: Annotated[str | None, Form()] = None, model: Annotated[str | None, Form()] = None) -> dict:  # fmt: skip
    """VL6 · VL7: 사진에서 읽은 것(코드 · 호스 꺾임)을 질문에 붙여 서비스 답변(매뉴얼 근거) → 답 문장마다 기댄 영역."""
    im, info, truth = _image(file, code, seed, hard, far)
    lcfg = _lcfg(provider, model)
    r = pipeline.split(lcfg, im, pipeline.CODES)
    img = r.pop("image")
    seen = []
    if r.get("code"):
        seen.append(f"표시창 오류 코드 {r['code']}")
    if r["kinked"] is not None:
        seen.append("배수 호스가 꺾여 있음" if r["kinked"] else "배수 호스는 곧음")
    q = question + (f" (사진에서 확인: {', '.join(seen)})" if seen else "")
    cfg = default_config(db, collection_id)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 청크 세트가 없습니다")
    t0 = time.perf_counter()
    out = serve.answer_once(db, q, {k: v for k, v in cfg.items() if not k.startswith("_")}, lcfg, max_tokens=500, kind="vision")
    text = out.get("answer") or ""
    return {"question": q, "answer": text, "sources": out.get("sources") or [], "regions": r["regions"], "grounding": pipeline.ground(text, r["regions"], r.get("code")),
            "code": r.get("code"), "kinked": r["kinked"], "truth": truth, "answer_seconds": round(time.perf_counter() - t0, 1), "input": info,
            "overlay": "data:image/png;base64," + base64.b64encode(see.overlay(img, r["regions"])).decode()}  # fmt: skip


@router.post("/evaluate", status_code=202)
def evaluate(body: EvalIn) -> dict:
    lcfg = _lcfg(body.llm.provider if body.llm else None, body.llm.model if body.llm else None)

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = pipeline.evaluate(lcfg, body.n, progress=job.update)
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(
                db, "vision_eval", [lcfg.model], "VLM 하나에 vs 나눠서", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("vision_eval", f"VLM 하나에 vs 나눠서 · {lcfg.model}", work).to_dict()
