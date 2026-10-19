"""멀티모달 미디어 문서: 이미지 · 영상 업로드 → 프레임 추출(같은 장면 제외) → 청크 · 색인(이미지 인코딩) → 텍스트로 검색."""

import io

import av
import pytest
from PIL import Image

from app.core import media_store
from app.core.config import get_settings
from tests.helpers import model_id, wait_job

RED, GREEN, BLUE = (220, 20, 20), (20, 200, 20), (20, 20, 220)


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def _video(colors: list[tuple], fps: int = 1) -> bytes:
    """초당 fps 장, colors 순서대로 단색 프레임을 담은 mp4 (FFmpeg 내장 mpeg4 인코더 — 어느 PyAV 휠에도 있음)."""
    buf = io.BytesIO()
    with av.open(buf, mode="w", format="mp4") as out:
        st = out.add_stream("mpeg4", rate=fps)
        st.width, st.height, st.pix_fmt = 64, 64, "yuv420p"
        for c in colors:
            for pkt in st.encode(av.VideoFrame.from_image(Image.new("RGB", (64, 64), c))):
                out.mux(pkt)
        for pkt in st.encode():
            out.mux(pkt)
    return buf.getvalue()


@pytest.fixture
def media_collection(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "video_frame_interval", 1.0)
    cid = client.post("/api/collections", json={"name": "미디어 테스트"}).json()["id"]
    files = [
        ("files", ("빨간_사과.png", _png(RED), "image/png")),
        ("files", ("바다-풍경.png", _png(BLUE), "image/png")),
        # 빨강 4초(같은 장면 → 1장만) 뒤 초록 2초 → 프레임 2장
        ("files", ("드론 영상.mp4", _video([RED] * 4 + [GREEN] * 2), "video/mp4")),
        ("files", ("메모.txt", "회의는 매주 월요일 오전 10시에 합니다.".encode(), "text/plain")),
        ("files", ("깨진.png", b"not an image", "image/png")),
    ]
    up = client.post(f"/api/collections/{cid}/documents", files=files).json()
    yield cid, up
    client.delete(f"/api/collections/{cid}")


def test_ingest_images_and_video(client, media_collection):
    cid, up = media_collection
    added = {d["filename"]: d for d in up["added"]}
    assert set(added) == {"빨간_사과.png", "바다-풍경.png", "드론 영상.mp4", "메모.txt"}
    assert up["skipped"][0]["filename"] == "깨진.png" and "열 수 없습니다" in up["skipped"][0]["reason"]
    video = added["드론 영상.mp4"]
    items = video["meta"]["media_items"]
    assert [it["t"] for it in items] == [0.0, 4.0] and video["meta"]["media"]["skipped_same_scene"] == 4  # 빨강 3장 + 초록 1장
    assert items[1]["label"] == "드론 영상 0:04" and "프레임 2장" in video["warning"]
    assert added["빨간_사과.png"]["title"] == "빨간 사과"  # 파일 이름이 검색 가능한 글이 된다
    # 같은 파일을 다시 올리면 중복으로 건너뛴다
    again = client.post(f"/api/collections/{cid}/documents", files=[("files", ("다시.png", _png(RED), "image/png"))]).json()
    assert not again["added"] and "이미 있는" in again["skipped"][0]["reason"]


def test_index_and_search_by_text(client, media_collection):
    cid, up = media_collection
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    detail = client.get(f"/api/collections/{cid}").json()
    stats = next(s for s in detail["chunk_sets"] if s["id"] == cs["id"])["stats"]
    assert stats["n_media"] == 4  # 이미지 2 + 프레임 2 (텍스트 청크는 제외)

    mm = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": model_id(client, "google/embeddinggemma-2")}).json()
    done = wait_job(client, mm["job"])
    assert done["status"] == "done" and done["result"]["n_images"] == 4 and "warning" not in done["result"]

    def top(index_id, query):
        r = client.post(
            f"/api/collections/{cid}/search", json={"query": query, "configs": [{"mode": "dense", "index_id": index_id, "top_k": 2}]}
        )
        return r.json()["results"][0]["results"]

    red = top(mm["id"], "빨간색 사진")
    assert {x["filename"] for x in red} == {"빨간_사과.png", "드론 영상.mp4"}  # 그림 내용(색)으로 찾는다
    frame = next(x for x in red if x["filename"] == "드론 영상.mp4")
    assert frame["media"]["t"] == 0.0 and frame["media"]["source_url"].endswith("/media")
    green = top(mm["id"], "초록색 사진")[0]
    assert green["filename"] == "드론 영상.mp4" and green["media"]["t"] == 4.0
    img = client.get(green["media"]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert client.get(frame["media"]["source_url"]).headers["content-type"] == "video/mp4"

    # 텍스트 전용 모델: 이미지는 파일 이름으로만 색인되고 경고가 붙는다
    txt = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": model_id(client, "nlpai-lab/KURE-v1")}).json()
    res = wait_job(client, txt["job"])["result"]
    assert res["n_images"] == 0 and "텍스트 전용" in res["warning"]
    assert top(txt["id"], "빨간 사과")[0]["filename"] == "빨간_사과.png"


def test_media_path_is_confined_and_deleted(client, media_collection):
    cid, up = media_collection
    with pytest.raises(media_store.MediaError):
        media_store.resolve("../app.db")  # 미디어 폴더 밖은 내주지 않는다
    doc = next(d for d in up["added"] if d["filename"] == "드론 영상.mp4")
    folder = media_store.doc_dir(doc["id"])
    assert len(list(folder.glob("frame-*.jpg"))) == 2
    client.delete(f"/api/documents/{doc['id']}")
    assert not folder.exists()
    assert client.get(f"/api/documents/{doc['id']}/media").status_code == 404
