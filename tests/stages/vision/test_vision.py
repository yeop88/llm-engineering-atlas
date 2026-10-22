"""이미지 · VL(VL1~VL7): 입력 확인(위치 정보 지우기) · 표시창 · 호스 영역 · 꺾임 · 읽기용 보정 분리 · 근거 영역 · API.

규칙 부분(영역 · 꺾임)은 정답을 아는 시험 사진으로 실제 값을 본다. 비전 LLM 이 필요한 곳(표시창 읽기 · 'VLM 하나에' 비교)은
photo.read_code · llm.chat 를 가짜로 바꿔, 흐름(잘라 읽기 · 코드 맞춤 · 영역 번호)이 이어지는지만 본다.
"""

import io
import json

from PIL import Image

from app.core import llm
from app.stages.as_service import photo
from app.stages.vision import pipeline, see, synth
from tests.helpers import wait_job


def test_find_display_clean_and_hard():
    for hard, far in ((False, False), (False, True), (True, True)):
        ious = []
        for s in range(100, 106):
            im, t = synth.make("E4", seed=s, hard=hard, far=far)
            d = see.find_display(im)
            ious.append(synth.iou(d["box"], t["display"]) if d else 0.0)
        # 사진마다 정한 어둠 기준 · 주축 상자 — 고정 기준(55)일 때는 반사 · 기울기 사진에서 하나도 못 찾았다
        assert sum(ious) / len(ious) > 0.85, (hard, far, ious)


def test_display_angle_measured():
    im, t = synth.make("d80", seed=101, hard=True)
    d = see.find_display(im)
    assert d and abs(d["angle"] + t["angle"]) < 1.5


def test_hose_kink_rule():
    ok = 0
    for s in range(100, 110):
        im, t = synth.make("E4", seed=s, kinked=s % 2 == 0)
        h = see.find_hose(im)
        ok += bool(h) and h["kinked"] == t["kinked"]
    assert ok >= 9


def test_enhance_only_for_reading():
    """회귀: 반사 누르기 · 선명하게를 사진 전체에 쓰면 호스 꺾임 정답률이 100% → 40% 로 떨어졌다 — 나눠서는 보정 전 그림으로 꺾임을 본다."""
    ok = 0
    for s in range(100, 110):
        im, t = synth.make("E4", seed=s)
        r = pipeline.split(None, im, pipeline.CODES)
        ok += r["kinked"] == t["kinked"]
    assert ok >= 9
    assert "선명하게" in see.enhance(Image.new("RGB", (40, 40), (250, 250, 250)))[1]


def test_inspect_input_removes_gps():
    ex = Image.Exif()
    ex.get_ifd(0x8825)[1] = "N"
    ex.get_ifd(0x8825)[2] = (37.0, 30.0, 0.0)
    buf = io.BytesIO()
    Image.new("RGB", (2400, 1200)).save(buf, "JPEG", exif=ex.tobytes())
    im, info = see.inspect_input(buf.getvalue())
    assert info["gps_removed"] and max(im.size) <= see.MAX_SIDE and info["resized"]
    assert not im.getexif()  # 줄인 그림에는 EXIF 가 남지 않는다


def test_ground_sentences_to_regions():
    regions = [{"label": "표시창 d80", "box": [0, 0, 1, 1], "for": "code"}, {"label": "배수 호스 꺾임", "box": [2, 2, 3, 3], "for": "hose"}]
    g = pipeline.ground("D80 은 배기 막힘입니다. 배수 호스를 펴 주세요. 필터를 청소하세요.", regions, "d80")
    assert [x["regions"] for x in g] == [[1], [2], []]


def test_api_look_without_reading(client):
    r = client.post("/api/vision/look", data={"code": "E4", "seed": "100", "hard": "true", "read": "false"}).json()
    assert r["display"] and r["code"] is None and r["overlay"].startswith("data:image/png;base64,")
    assert r["truth"]["code"] == "E4" and any(x["for"] == "hose" for x in r["regions"])
    assert (
        client.post("/api/vision/look", files={"file": ("x.png", b"not an image", "image/png")}, data={"read": "false"}).status_code == 400
    )
    assert client.get("/api/vision/sample.png?code=OE&seed=1").headers["content-type"] == "image/png"


def _fake_read(seen):
    def read(lcfg, image, known=None):
        seen.append(Image.open(io.BytesIO(image)).size)
        return {"code": "d80", "raw_code": "D8O", "snapped": True, "display": "D8O", "seen": True}

    return read


def test_api_look_reads_crop(client, scripted_llm, monkeypatch):
    seen = []
    monkeypatch.setattr(photo, "read_code", _fake_read(seen))
    r = client.post("/api/vision/look", data={"code": "d80", "seed": "102", "far": "true", "read": "true"}).json()
    assert r["code"] == "d80" and r["snapped"] and r["read_on"] == "표시창"
    # 잘라 키운 표시창만 읽힌다 — 짧은 변이 320px 쯤(사진 전체 800×600 이 아니다)
    assert seen and min(seen[0]) >= 300 and seen[0] != (800, 600)


def test_api_answer(client, rag_collection, scripted_llm, monkeypatch):
    monkeypatch.setattr(photo, "read_code", _fake_read([]))
    r = client.post("/api/vision/answer", data={"question": "이 표시가 뜨는데 어떻게 하나요?", "collection_id": str(rag_collection["cid"]),
                                                "code": "d80", "seed": "3"}).json()  # fmt: skip
    assert "d80" in r["question"] and r["answer"] and r["grounding"]


def test_api_evaluate(client, scripted_llm, monkeypatch):
    monkeypatch.setattr(photo, "read_code", _fake_read([]))
    monkeypatch.setattr(
        llm, "chat", lambda *a, **k: {"text": json.dumps({"code": "E4", "hose_visible": True, "hose_kinked": False}), "seconds": 0.0}
    )
    r = wait_job(client, client.post("/api/vision/evaluate", json={"n": 1}).json(), 1200)["result"]
    assert set(r["by_condition"]) >= {"깨끗", "전체"} and r["by_condition"]["전체"]["n"] == 4 and r["run_id"]


def test_page(client):
    assert client.get("/vision/look").status_code == 200
