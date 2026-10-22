"""오디오 이해 API (AU1~AU7). 나누기 · 사건 · 화자는 신호 처리라 바로, 말 구간 인식은 음성 인식(VC4)이 설정돼 있을 때만."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import crud
from app.core.db import get_db
from app.stages.audio import index, scene, synth
from app.stages.audio.schemas import EvalIn, SearchIn
from app.stages.voice import audio, stt

router = APIRouter(prefix="/api/audio", tags=["audio"])
DB = Annotated[Session, Depends(get_db)]
MAX_SECONDS = 600  # 10분 — 프레임 특징은 가볍지만 화자 군집이 조각 수의 제곱으로 는다


def _scene(name: str) -> tuple[Any, dict[str, Any]]:
    p = index.preset()
    i, sc = next(((i, s) for i, s in enumerate(p["scenes"]) if s["name"] == name), (None, None))
    if sc is None:
        raise HTTPException(404, f"예시 장면이 없습니다: {name}")
    return synth.scene(sc["parts"], seed=i)


@router.get("/preset")
def preset() -> dict:
    p = index.preset()
    return {"scenes": [s["name"] for s in p["scenes"]], "queries": p["queries"], "labels": scene.LABEL, "events": scene.EVENT_LABEL}


@router.get("/scenes/{name}.wav")
def scene_wav(name: str) -> Response:
    x, _ = _scene(name)
    return Response(audio.to_wav(x), media_type="audio/wav")


@router.post("/analyze")
def analyze(file: Annotated[UploadFile | None, File()] = None, scene_name: Annotated[str | None, Form()] = None,
            transcribe: Annotated[bool, Form()] = False, threshold: Annotated[float, Form(ge=0.5, le=12)] = 2.5) -> dict:  # fmt: skip
    """녹음 파일 또는 예시 장면 → 구간(종류 · 화자) · 사건 · 색인 항목 · 시간 순 요약. transcribe 면 말 구간마다 음성 인식."""
    t0 = time.perf_counter()
    texts: dict[tuple[float, float], str] = {}
    source = ""
    if file is not None:
        x = audio.decode(file.file.read())
        if len(x) / audio.SR > MAX_SECONDS:
            raise HTTPException(413, f"{MAX_SECONDS // 60}분 넘는 녹음은 나눠 올려 주세요")
    elif scene_name:
        x, truth = _scene(scene_name)
        texts = {(s["start"], s["end"]): s["text"] for s in truth["segments"] if s.get("text")}
        source = "정답 글(합성)"  # 합성 말은 사람 말이 아니라 인식할 수 없다 — 만들 때 적은 글을 붙이고 출처를 밝힌다
    else:
        raise HTTPException(400, "녹음 파일이나 예시 장면을 주세요")
    res = scene.analyze(x, threshold)
    stt_note = None
    if transcribe and file is not None:
        try:
            for s in res["segments"]:
                if s["type"] == "speech" and s["end"] - s["start"] >= 0.5:
                    seg = x[int(s["start"] * audio.SR) : int(s["end"] * audio.SR)]
                    texts[(s["start"], s["end"])] = stt.transcribe(seg)["text"]
            source = "음성 인식"
        except Exception as exc:  # noqa: BLE001 — 인식기가 없거나 실패해도 나누기 · 사건 결과는 돌려준다
            stt_note = f"음성 인식 실패: {type(exc).__name__}: {str(exc)[:120]}"
    items = index.describe(res, texts, source)
    return {"seconds": res["seconds"], "segments": res["segments"], "events": res["events"], "speakers": res["speakers"], "items": items,
            "summary": index.summary(items), "elapsed": round(time.perf_counter() - t0, 2), "stt_note": stt_note, "stt": stt.engines()}  # fmt: skip


@router.post("/search")
def search(body: SearchIn) -> dict:
    return {"results": index.search(body.items, body.q, body.k)}


@router.post("/evaluate")
def evaluate(body: EvalIn, db: DB) -> dict:
    """예시 장면 6개 + 규칙을 맞출 때 쓰지 않은 무작위 장면 — 프레임 정확(크기만 보는 기준선과), 사건 정밀 · 재현, 화자 순도 · 덮음, 검색 적중."""
    t0 = time.perf_counter()
    res = index.evaluate(body.held_out)
    res["seconds"] = round(time.perf_counter() - t0, 1)
    res["run_id"] = crud.record_run(db, "audio_eval", [], "오디오 이해 평가(합성 장면)", body.model_dump(), res, res["seconds"] * 1000).id
    return res
