"""5순위(도메인): 법령 · 판례 번호 조회와 인용 검사 · 학습 라우터 · 그림 근거 답변."""

import json

import httpx
import numpy as np
import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.stages.agent import agent
from app.stages.rag import answer, legal
from app.stages.routing import learned, service
from tests.test_rag import _model, _wait

LAW = (
    "근로기준법\n시행 2025-10-23 · 소관 고용노동부\n\n"
    "제23조(해고 등의 제한) ① 사용자는 근로자에게 정당한 이유 없이 해고, 휴직, 정직, 전직, 감봉, 그 밖의 징벌을 하지 못한다.\n"
    "제24조(경영상 이유에 의한 해고의 제한) ① 사용자가 경영상 이유에 의하여 근로자를 해고하려면 긴박한 경영상의 필요가 있어야 한다.\n"
    "제26조(해고의 예고) 사용자는 근로자를 해고하려면 적어도 30일 전에 예고를 하여야 한다.\n"
)
CASE = "해고무효확인 (대법원 2019. 3. 14. 선고 2019다12345)\n판결요지: 정당한 이유 없는 해고는 무효이다. 근로기준법 제23조 참조."


def test_parse_refs():
    refs = legal.parse_refs("근로기준법 제23조 제1항과 주택임대차보호법 3조의2, 대법원 2019다 12345 판결. 예산은 3조 원")
    got = {r["ref"] for r in refs}
    assert got == {"근로기준법 제23조 제1항", "주택임대차보호법 제3조의2", "2019다12345"}  # '3조 원'(금액)은 잡지 않는다
    # 시행령은 법령명에 붙어 있어야 한다 — '시행령'만 남으면 엉뚱한 시행령에서 찾는다
    assert [r["law"] for r in legal.parse_refs("주택임대차보호법 시행령 제28조(조정부)")] == ["주택임대차보호법 시행령"]


@pytest.fixture
def law_set(client):
    cid = client.post("/api/collections", json={"name": "법률 도구"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", ("근로기준법.txt", LAW.encode(), "text/plain")),
                                                             ("files", ("판례 2019다12345 해고무효확인.txt", CASE.encode(), "text/plain"))])  # fmt: skip
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "legal", "size": 400, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    yield cid, cs["id"]
    client.delete(f"/api/collections/{cid}")


def test_lookup_and_citations(law_set):
    _, cs_id = law_set
    with SessionLocal() as db:
        hit = legal.lookup(db, cs_id, "근로기준법 제24조")
        assert hit and hit[0]["text"].lstrip().startswith("제24조") and "경영상" in hit[0]["text"]
        assert legal.lookup(db, cs_id, "2019다12345")[0]["filename"].startswith("판례 2019다12345")
        assert legal.lookup(db, cs_id, "근로기준법 제99조") == []
        fn = legal.lookup_fn_for(db, cs_id)
        srcs = [{"text": hit[0]["text"], "filename": "근로기준법.txt"}]
        c = legal.check_citations(
            "경영상 해고는 근로기준법 제24조에 따릅니다 [1]. 예고는 근로기준법 제26조 [1]. 근로기준법 제99조도 있습니다.", srcs, fn
        )
        st = {r["ref"]: r["status"] for r in c["refs"]}
        assert st == {"근로기준법 제24조": "in_sources", "근로기준법 제26조": "in_collection", "근로기준법 제99조": "not_found"}
        assert c["n_not_found"] == 1 and not c["ok"]


def test_agent_lookup_tool(law_set, monkeypatch):
    _, cs_id = law_set
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["messages"][0]["content"])
        n = len(calls)
        act = {"thought": "번호로 찾자", "action": "lookup", "input": "근로기준법 제26조"} if n == 1 else {
            "thought": "답", "action": "finish", "input": "해고하려면 30일 전에 예고해야 합니다(근로기준법 제26조) [S1]."}  # fmt: skip
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(act, ensure_ascii=False)}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    with SessionLocal() as db:
        out = agent.run_to_end(
            llm.resolve(None, None), "해고 예고는 며칠 전?", lambda q: [], db=db, lookup_fn=legal.lookup_fn_for(db, cs_id)
        )
    assert "lookup" in calls[0] and out["steps"][0]["action"] == "lookup" and "30일" in out["sources"][0]["text"]
    assert out["citations"]["refs"][0]["status"] == "in_sources"


def _rows(n=24, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        hard = i % 3 == 0  # 긴 '왜 · 어떻게' 질문이 전체 경로에서 나음
        q = f"질문 {i} 왜 그렇게 되는지 절차와 이유를 각각 자세히 설명해 주세요" if hard else f"질문 {i} 기한은?"
        rows.append({"query": q, "confidence": float(rng.uniform(0, 0.05) if hard else rng.uniform(0.1, 0.4)),
                     "easy": {"quality": 0.0 if hard else 1.0, "ndcg": None, "ms": 1000.0, "search_ms": 50.0, "answer": None},
                     "hard": {"quality": 1.0, "ndcg": None, "ms": 3000.0, "search_ms": 80.0, "answer": None},
                     "rule": {"path": "hard" if hard else "easy", "reason": ""}, "llm": None})  # fmt: skip
    return rows


def test_learned_router_cross_validated(client):
    rows = _rows()
    with SessionLocal() as db:
        from app.core import crud

        spec = crud.get_spec(db, _model(client, "nlpai-lab/KURE-v1"), "embedding")
    model, cv = learned.train(spec, rows)
    assert cv["n_hard"] == 8 and cv["folds"] == 5 and len(cv["proba"]) == len(rows)
    paths = ["hard" if p >= 0.5 else "easy" for p in cv["proba"]]
    res = service.evaluate(rows, ["rule", "confidence"], 0.05, {"learned": paths})
    by = {r["router"]: r for r in res["results"]}
    assert "learned" in by and by["learned"]["quality"] >= by["always_easy"]["quality"]
    assert by["learned"]["latency_ms"]["mean"] < by["always_hard"]["latency_ms"]["mean"]
    path, why = learned.route(model, spec, rows[0]["query"], [{"score": 0.5}, {"score": 0.49}])
    assert path in ("easy", "hard") and "어려움 확률" in why
    with pytest.raises(ValueError):
        learned.cross_val_proba(np.zeros((4, 3)), ["easy", "easy", "easy", "hard"])  # 한쪽이 2개 미만


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
    assert _wait(client, cs["job"])["status"] == "done"
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


def test_sample_passages_document_filter(law_set):
    from sqlalchemy import select

    from app.core.db import Document
    from app.stages.rag import evaluation

    cid, cs_id = law_set
    with SessionLocal() as db:
        law_id = db.scalars(select(Document.id).where(Document.collection_id == cid, Document.filename == "근로기준법.txt")).one()
        got = evaluation.sample_passages(db, cs_id, 10, min_chars=10, document_ids=[law_id])
        assert got and {p["document_id"] for p in got} == {law_id}  # 적은 종류(법령)만 골라 보충할 수 있다
