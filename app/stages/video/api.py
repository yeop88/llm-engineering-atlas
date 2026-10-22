"""비디오 이해 API (VD1~VD8). 색인 · 시간 계산은 바로, 대표 프레임 읽기 · LLM 비교는 비전 · 글 LLM 을 부른다."""

import io
import time
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core import crud, llm
from app.core.db import SessionLocal
from app.core.jobs import Job, jobs
from app.stages.as_service import photo
from app.stages.omni import video as om_video
from app.stages.video import index, media, synth
from app.stages.video.schemas import AskIn, EvalIn

router = APIRouter(prefix="/api/video", tags=["video"])


def _lcfg(ref: Any) -> llm.LLMConfig:
    return llm.resolve(ref.provider if ref else None, ref.model if ref else None)


@router.get("/sample/{seed}/frame.png")
def sample_frame(seed: int, t: float = 0.0) -> Response:
    p = synth.plan(seed)
    fr = synth.frames(p)
    im = min(fr, key=lambda x: abs(x[0] - t))[1]
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


@router.post("/index")
def build_index(file: Annotated[UploadFile | None, File()] = None, seed: Annotated[int | None, Form()] = None, fps: Annotated[float, Form(gt=0, le=10)] = 2.0,
                describe: Annotated[bool, Form()] = False, provider: Annotated[str | None, Form()] = None,
                model: Annotated[str | None, Form()] = None) -> dict:  # fmt: skip
    """영상 파일 또는 시험 영상(seed) → 컷 · 트랙 · 소리 사건 색인. describe 면 장면마다 대표 프레임을 비전 LLM 으로 읽는다(VD3)."""
    t0 = time.perf_counter()
    truth = None
    if file is not None:
        try:
            frames, snd, info = media.decode(file.file.read(), fps)
        except Exception as exc:  # noqa: BLE001 — 손상 · 미지원 코덱
            raise HTTPException(400, f"영상을 읽을 수 없습니다: {type(exc).__name__}: {str(exc)[:120]}") from exc
        palette = {}  # 실제 영상: 색 탐지는 시험 영상용이라 끈다 — 컷 · 소리 · 대표 프레임만
    elif seed is not None:
        p = synth.plan(seed)
        frames, snd, info = (
            synth.frames(p),
            synth.audio_track(p),
            {"duration": p["duration"], "fps": p["fps"], "audio": True, "synthetic": True},
        )
        palette = None
        truth = synth.truth_events(p)
    else:
        raise HTTPException(400, "영상 파일이나 시험 영상 번호(seed)를 주세요")
    idx = index.build(frames, snd, palette)
    if describe:
        lcfg = llm.resolve(provider or None, model or None)
        for k in idx["keyframes"]:
            im = min(frames, key=lambda x: abs(x[0] - k["t"]))[1]
            k["desc"] = om_video.describe(lcfg, photo.jpeg(im), None)
    return {"info": info, "events": idx["events"], "tracks": [{k: v for k, v in tr.items() if k != "path"} | {"points": len(tr["path"])} for tr in idx["tracks"]],
            "cuts": idx["cuts"], "keyframes": idx["keyframes"], "log": index.log_text(idx), "truth": truth, "seconds": round(time.perf_counter() - t0, 2)}  # fmt: skip


@router.post("/ask")
def ask(body: AskIn) -> dict:
    """VD6 · VD8: 질문 → (대상 · 사건 종류 · 연산 · 기준 사건) → 색인 계산 · 근거 사건 · 클립 구간. llm 을 주면 기록 전체를 LLM 에 준 답도."""
    idx = {"events": body.events}
    out = index.answer(idx, body.q)
    if body.llm is not None:
        out["llm"] = index.llm_answer(_lcfg(body.llm), idx, body.q)
    return out


@router.post("/evaluate", status_code=202)
def evaluate(body: EvalIn) -> dict:
    lcfg = _lcfg(body.llm) if body.compare_llm else None

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = index.evaluate(body.n, lcfg, job.update)
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(
                db, "video_eval", [lcfg.model] if lcfg else [], "영상 시간 질문(합성)", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("video_eval", f"영상 시간 질문 · {body.n}개", work).to_dict()
