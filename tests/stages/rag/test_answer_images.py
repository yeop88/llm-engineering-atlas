"""그림 근거 답변: 제공자별 그림 입력 형식 · 근거 이미지 첨부."""

from app.core import llm
from app.core.db import SessionLocal
from app.stages.rag import answer
from tests.helpers import wait_job


def test_image_content_formats():
    img = b"\xff\xd8fake"
    oa = llm._user_content("openai", "질문", [img])
    assert oa[0] == {"type": "text", "text": "질문"} and oa[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    an = llm._user_content("anthropic", "질문", [img])
    assert an[0]["type"] == "image" and an[0]["source"]["media_type"] == "image/jpeg" and an[-1]["text"] == "질문"
    assert llm._user_content("openai", "질문", None) == "질문"


def test_attach_images(client, tmp_path):
    from PIL import Image

    cid = client.post("/api/collections", json={"name": "그림 근거"}).json()["id"]
    p = tmp_path / "빨간사각형.png"
    Image.new("RGB", (1600, 900), (220, 30, 30)).save(p)
    client.post(f"/api/collections/{cid}/documents", files=[("files", (p.name, p.read_bytes(), "image/png"))])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 1}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.core.db import Chunk

        c = db.scalars(select(Chunk).where(Chunk.chunk_set_id == cs["id"])).first()
        srcs = [{"text": "글 근거", "chunk_id": None}, {"text": c.text, "chunk_id": c.id, "media": {"url": "x"}}]
        images, note = answer.attach_images(db, srcs)
    assert len(images) == 1 and images[0][:2] == b"\xff\xd8" and "[2] = 첨부 그림 1" in note
    from io import BytesIO

    assert max(Image.open(BytesIO(images[0])).size) <= answer.IMAGE_MAX_SIDE  # 크게 보내지 않는다
    client.delete(f"/api/collections/{cid}")
