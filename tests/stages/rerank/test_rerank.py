"""3 리랭킹: 융합 · LLM 목록형 · 리랭커 평가 작업."""

from tests.helpers import model_id, wait_job


def test_rerank_fusion_and_llm_rerank(client, rag_collection, scripted_llm):
    base = {"mode": "dense", "index_id": rag_collection["idx"], "top_k": 5}
    rr = model_id(client, "BAAI/bge-reranker-v2-m3")
    out = client.post(f"/api/collections/{rag_collection['cid']}/search", json={"query": "세탁기 배수 필터", "configs": [
        base | {"reranker_id": rr, "rerank_top": 5}, base | {"reranker_id": rr, "rerank_top": 5, "rerank_fusion": True},
        base | {"llm_rerank": {"top": 4}}]}).json()["results"]  # fmt: skip
    plain, fused, llm_r = out
    assert all("rerank_fused" in r["scores"] for r in fused["results"]) and "rerank_fused" not in plain["results"][0]["scores"]
    assert (
        llm_r["reranked"] and llm_r["llm_rerank"]["returned"] == 1 and llm_r["results"][0]["ranks"]["before_llm_rerank"] == 4
    )  # 4위가 1위로
    assert "llm_rerank" in llm_r["timings_ms"] and len(llm_r["results"]) == len(plain["results"])  # 빠뜨린 후보도 원래 순서로 남는다


def test_rerank_evaluate_job(client, rag_collection, scripted_llm):
    rr = model_id(client, "BAAI/bge-reranker-v2-m3")
    body = {
        "eval_set_id": rag_collection["set"],
        "config": {"mode": "dense", "index_id": rag_collection["idx"]},
        "reranker_ids": [rr],
        "ks": [3, 5],
        "llm": {"top": 4},
    }
    done = wait_job(client, client.post("/api/rerank/evaluate", json=body).json())
    assert done["status"] == "done", done.get("error")
    rows = done["result"]["rows"]
    keys = {(r["reranker"], r["k"], r["fusion"]) for r in rows}
    assert (None, 0, False) in keys and (rr, 3, True) in keys and (rr, 5, False) in keys and ("llm", 4, False) in keys
    none = next(r for r in rows if r["reranker"] is None)
    assert none["vs_none"] is None and all("diff" in r["vs_none"] for r in rows if r is not none)
    bad = client.post("/api/rerank/evaluate", json=body | {"reranker_ids": [model_id(client, "nlpai-lab/KURE-v1")]})
    assert bad.status_code == 400  # 임베딩 모델은 리랭커가 아니다
