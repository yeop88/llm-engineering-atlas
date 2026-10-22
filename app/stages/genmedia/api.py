"""생성 미디어 API (GM7 · GM8). 생성은 하지 않는다 — 생성물(올린 그림 · 시험 샷)을 검사하고 출처 · 워터마크를 붙이고 확인한다."""

import base64
import io
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from app.core import crud
from app.core.db import get_db
from app.stages.genmedia import provenance, qa
from app.stages.vision import synth as vsynth

router = APIRouter(prefix="/api/genmedia", tags=["genmedia"])
DB = Annotated[Session, Depends(get_db)]


def _img(file: UploadFile | None, seed: int) -> Image.Image:
    if file is None:
        im, _ = vsynth.make("E4", seed=seed)  # 올린 그림이 없으면 시험 그림(이미지 맵의 가전 앞판)
        return im
    try:
        return Image.open(io.BytesIO(file.file.read())).convert("RGB")
    except Exception as exc:  # noqa: BLE001 — 그림이 아닌 파일
        raise HTTPException(400, f"그림을 열 수 없습니다: {type(exc).__name__}") from exc


@router.post("/provenance/embed")
def embed(key: Annotated[str, Form(min_length=4, max_length=100)], prompt: Annotated[str, Form(max_length=2000)] = "",
          generator: Annotated[str, Form(max_length=100)] = "unknown", visible: Annotated[bool, Form()] = True,
          file: Annotated[UploadFile | None, File()] = None, seed: Annotated[int, Form()] = 0) -> dict:  # fmt: skip
    """GM8: 매니페스트(지시문은 해시만) · 보이는 'AI 생성' 표시 · 보이지 않는 워터마크를 붙인 PNG(data URL)."""
    m = provenance.manifest(prompt, generator)
    data = provenance.embed(_img(file, seed), key, m, visible)
    return {"manifest": m, "png": "data:image/png;base64," + base64.b64encode(data).decode(), "bytes": len(data)}


@router.post("/provenance/detect")
def detect(key: Annotated[str, Form(min_length=4, max_length=100)], file: Annotated[UploadFile, File()]) -> dict:
    return provenance.detect(file.file.read(), key)


@router.post("/provenance/evaluate")
def evaluate_provenance(db: DB, n: Annotated[int, Form(ge=1, le=60)] = 12) -> dict:
    """그림 n 장 × 공격(다시 저장 · JPEG 90/70/50 · 반으로 줄이기 · 70% 자르기) → 겹마다 남은 몫, 무늬 없는 그림 · 다른 열쇠의 거짓 검출."""
    t0 = time.perf_counter()
    imgs = [vsynth.make("E4", seed=1000 + s, hard=s % 2 == 0, far=s % 3 == 0)[0] for s in range(n)]
    rows = {a: {"watermark": 0, "metadata": 0} for a in provenance.ATTACKS}
    false_hits, z_null = 0, []
    for im in imgs:
        data = provenance.embed(im, "eval-key", provenance.manifest("시험", "eval"))
        for a in provenance.ATTACKS:
            d = provenance.detect(provenance.attack(data, a), "eval-key")
            rows[a]["watermark"] += d["watermark"]
            rows[a]["metadata"] += d["metadata"]
        buf = io.BytesIO()
        im.save(buf, "PNG")
        for d in (provenance.detect(buf.getvalue(), "eval-key"), provenance.detect(data, "other-key")):
            false_hits += d["watermark"]
            z_null.append(d["watermark_z_shift"])
    res = {"n": n, "attacks": {a: {k: round(v / n, 3) for k, v in r.items()} for a, r in rows.items()}, "false_detection": round(false_hits / (2 * n), 3),
           "null_z_max": round(max(z_null), 2), "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
    res["run_id"] = crud.record_run(db, "genmedia_provenance", [], "출처 · 워터마크가 남는지", {"n": n}, res, res["seconds"] * 1000).id
    return res


@router.post("/qa/sample")
def qa_sample(
    seed: Annotated[int, Form()] = 400, defect: Annotated[str, Form(pattern="^(none|missing|style|flicker|jump)$")] = "none"
) -> dict:
    """GM7: 시험 샷 하나(결함을 넣거나 빼고) → 검사 결과와 프레임(data URL)."""
    s = qa.shot(seed, None if defect == "none" else defect)
    c = qa.run_checks(s)
    frames = []
    for f in s["frames"]:
        buf = io.BytesIO()
        f.save(buf, "PNG")
        frames.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    return c | {"wanted": s["wanted"], "frames": frames}


@router.post("/qa/evaluate")
def evaluate_qa(db: DB, n: Annotated[int, Form(ge=1, le=60)] = 20) -> dict:
    t0 = time.perf_counter()
    res = qa.evaluate(n)
    res["seconds"] = round(time.perf_counter() - t0, 1)
    res["run_id"] = crud.record_run(db, "genmedia_qa", [], "생성물 자동 검사(결함 넣은 시험 샷)", {"n": n}, res, res["seconds"] * 1000).id
    return res
