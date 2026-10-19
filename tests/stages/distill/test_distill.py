"""7a 지식 증류: LLM 증류 데이터 · 삼중쌍 검증."""

import json

import pytest

from app.stages.distill import llm_data
from tests.helpers import model_id, wait_job


def test_llm_distill_data(client, rag_collection, scripted_llm, monkeypatch):
    from app.stages.finetune import data

    monkeypatch.setattr(data, "build_pairs", lambda *a, **k: ([{"anchor": "세탁기 배수가 안 되면?"}, {"anchor": "공문서 문자"}], {}))
    body = {"collection_id": rag_collection["cid"], "chunk_set_id": rag_collection["cs"], "config": {"mode": "dense", "index_id": rag_collection["idx"]}, "n_passages": 2,
            "min_support": 0.5, "name": "t-distill"}  # fmt: skip
    done = wait_job(client, client.post("/api/distill/llm-data", json=body).json())
    assert done["status"] == "done", done.get("error")
    r = done["result"]
    assert r["file"] == "t-distill.jsonl" and r["kept"] + sum(r["dropped"].values()) == 2
    files = {f["name"]: f for f in client.get("/api/distill/llm-data").json()}
    assert files["t-distill.jsonl"]["samples"] == r["kept"]
    dl = client.get("/api/distill/llm-data/t-distill.jsonl")
    assert dl.status_code == 200 and (not r["kept"] or json.loads(dl.text.splitlines()[0])["messages"][2]["role"] == "assistant")
    assert client.get("/api/distill/llm-data/..%5Capp.db").status_code == 404
    with pytest.raises(ValueError):
        llm_data.file_path("../x.jsonl")


def test_distill_triplets_and_validation(client, rag_collection):
    from app.core.db import EmbeddingModel, SessionLocal
    from app.stages.distill.service import make_triplets
    from app.stages.embedding.model_manager import ModelSpec

    pairs = [{"anchor": f"질문 {i} 세탁기", "positive": f"지문 {i} 배수 필터 청소 {'가' * i}", "document_id": i % 3} for i in range(6)]
    with SessionLocal() as db:
        teacher = ModelSpec.from_row(db.get(EmbeddingModel, model_id(client, "nlpai-lab/KURE-v1")))
    trip, info = make_triplets(teacher, pairs)
    assert len(trip) == 6 and info["teacher_kind"] == "embedding" and all(t["negative"] != t["positive"] for t in trip)
    assert all(
        pairs[i]["document_id"] != next(p["document_id"] for p in pairs if p["positive"] == t["negative"]) for i, t in enumerate(trip)
    )  # 다른 문서의 오답
    same = client.post("/api/distill", json={"base_model_id": model_id(client, "nlpai-lab/KURE-v1"), "teacher_model_id": model_id(client, "nlpai-lab/KURE-v1"),
                                             "collection_id": rag_collection["cid"], "chunk_set_id": rag_collection["cs"], "data_method": "ict"})  # fmt: skip
    assert same.status_code == 400  # 교사와 학생이 같으면 증류가 아니다
