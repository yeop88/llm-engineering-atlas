"""생성 미디어(GM7 · GM8): 출처 세 겹(매니페스트 · 보이는 표시 · 워터마크)이 다시 저장 · JPEG · 자르기 뒤 남는지, 다른 열쇠 · 무늬 없는 그림에서
거짓으로 찾지 않는지, 매니페스트를 고치면 드러나는지 · 자동 품질 검사가 결함 없는 샷은 통과시키고 넣은 결함은 맞는 검사로 잡는지 · API.

그림은 이미지 맵의 시험 그림(가전 앞판), 샷은 비디오 맵의 합성기 — 생성 모델 없이 검사 · 출처 규칙만 본다.
"""

import base64
import io
import json

import pytest
from PIL import Image, PngImagePlugin

from app.stages.genmedia import provenance as pv
from app.stages.genmedia import qa
from app.stages.vision import synth as vsynth

KEY = "test-key-1"


@pytest.fixture(scope="module")
def marked() -> tuple[Image.Image, bytes]:
    im, _ = vsynth.make("E4", seed=3)
    return im, pv.embed(im, KEY, pv.manifest("세탁기 표시창", "test-gen"))


@pytest.mark.parametrize("attack", ["none", "png_resave", "jpeg70", "crop70"])
def test_watermark_survives(marked, attack):
    d = pv.detect(pv.attack(marked[1], attack), KEY)
    assert d["watermark"], d
    # 메타데이터는 그대로일 때만 남는다 — 다른 도구로 다시 저장하면 사라진다(그래서 워터마크가 함께 필요)
    assert d["metadata"] is (attack == "none")


def test_no_false_detection(marked):
    im, data = marked
    assert not pv.detect(data, "other-key")["watermark"]
    buf = io.BytesIO()
    im.save(buf, "PNG")
    assert not pv.detect(buf.getvalue(), KEY)["watermark"]


def test_manifest_hash_and_prompt_privacy(marked):
    d = pv.detect(marked[1], KEY)
    assert d["manifest_intact"] is True
    assert "세탁기" not in json.dumps(d["manifest"], ensure_ascii=False)  # 지시문은 해시만
    m = dict(d["manifest"]) | {"generator": "바꾼 생성기"}
    info = PngImagePlugin.PngInfo()
    info.add_text("ai_manifest", json.dumps(m, ensure_ascii=False))
    buf = io.BytesIO()
    Image.open(io.BytesIO(marked[1])).save(buf, "PNG", pnginfo=info)
    assert pv.detect(buf.getvalue(), KEY)["manifest_intact"] is False


def test_qa_clean_and_defects():
    clean = qa.run_checks(qa.shot(400, None))
    assert clean["pass"], clean
    checks = {"missing": "prompt", "style": "style", "flicker": "temporal", "jump": "temporal"}
    for defect, check in checks.items():
        c = qa.run_checks(qa.shot(400, defect))
        assert not c[check]["ok"] and not c["pass"], (defect, c)


def test_api(client):
    r = client.post("/api/genmedia/provenance/embed", data={"key": KEY, "prompt": "p", "generator": "g"})
    assert r.status_code == 200, r.text
    png = r.json()["png"]
    assert png.startswith("data:image/png;base64,") and r.json()["manifest"]["ai_generated"] is True
    data = base64.b64decode(png.split(",", 1)[1])
    d = client.post("/api/genmedia/provenance/detect", data={"key": KEY}, files={"file": ("a.png", data, "image/png")}).json()
    assert d["watermark"] and d["metadata"]
    assert (
        client.post("/api/genmedia/provenance/embed", data={"key": KEY}, files={"file": ("x.png", b"not image", "image/png")}).status_code
        == 400
    )
    s = client.post("/api/genmedia/qa/sample", data={"seed": 400, "defect": "flicker"}).json()
    assert not s["temporal"]["ok"] and len(s["frames"]) == 8
    assert client.post("/api/genmedia/qa/sample", data={"defect": "bad"}).status_code == 422
    e = client.post("/api/genmedia/qa/evaluate", data={"n": 2}).json()
    assert e["clean_pass"] == 1.0 and e["run_id"]
    p = client.post("/api/genmedia/provenance/evaluate", data={"n": 2}).json()
    assert p["attacks"]["none"]["watermark"] == 1.0 and p["false_detection"] == 0.0 and p["run_id"]
    assert client.get("/genmedia/check").status_code == 200
