"""공개 벤치마크 가져오기: MTEB 형식 변환 · 표본 추출 (내려받기는 가짜로 대체)."""

import time

from app.stages.embedding import public_benchmarks as pb

CORPUS = [{"_id": f"d{i}", "title": f"제목{i}" if i % 2 else "", "text": f"문서 {i} 본문"} for i in range(50)] + [
    {"_id": "empty", "text": "  "}
]
QUERIES = [{"id": f"q{i}", "text": f"질문 {i}"} for i in range(20)] + [{"_id": "orphan", "text": "정답 없음"}]
QRELS = [{"query-id": f"q{i}", "corpus-id": f"d{i}", "score": "1"} for i in range(20)] + [
    {"query-id": "q0", "corpus-id": "d40", "score": 1},
    {"query-id": "q1", "corpus-id": "d41", "score": "0"},  # 0점은 정답 아님
    {"query-id": "q2", "corpus-id": "missing", "score": 1},  # 코퍼스에 없는 문서
]


def test_build_retrieval_full_and_sampled():  # 질문은 "id", 문서는 "_id" (데이터마다 다름)
    corpus, queries, info = pb.build_retrieval(CORPUS, QUERIES, QRELS, None, None)
    assert len(queries) == 20 and len(corpus) == 50 and not info["sampled"]  # 빈 문서·정답 없는 질문 제외
    q = {x["id"]: x for x in queries}
    assert q["q0"]["relevant"] == ["d0", "d40"] and q["q1"]["relevant"] == ["d1"] and q["q2"]["relevant"] == ["d2"]
    corpus, queries, info = pb.build_retrieval(CORPUS, QUERIES, QRELS, 5, 12, seed=1)
    ids = {d["id"] for d in corpus}
    assert len(queries) == 5 and len(corpus) == 12 and info["sampled"]
    assert all(set(x["relevant"]) <= ids for x in queries)  # 표본 질문의 정답 문서는 반드시 포함
    again, _, _ = pb.build_retrieval(CORPUS, QUERIES, QRELS, 5, 12, seed=1)
    assert [d["id"] for d in again] == [d["id"] for d in corpus]  # seed 가 같으면 같은 표본


def _wait(client, job):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


def test_import_api(client, monkeypatch):
    def fake_read(repo, filename):
        if "KorSTS" in repo:
            return [{"sentence1": f"문장 {i}", "sentence2": f"비슷한 문장 {i}", "score": str(i % 6)} for i in range(30)]
        part = filename.split("/")[0].split("-")[-1]
        return {"corpus": CORPUS, "queries": QUERIES, "qrels": QRELS}[part]

    monkeypatch.setattr(pb, "_read", fake_read)
    cat = client.get("/api/public-benchmarks").json()
    assert {c["key"] for c in cat} >= {"autorag_ko", "korsts"} and all("license" in c for c in cat)
    assert client.post("/api/public-benchmarks/nope/import", json={}).status_code == 404
    job = _wait(client, client.post("/api/public-benchmarks/autorag_ko/import", json={"max_queries": 10, "max_corpus": 100}).json())
    assert job["status"] == "done", job
    assert job["result"]["name"] == "pub_autorag_ko"
    ds = client.get("/api/datasets/pub_autorag_ko").json()
    assert ds["type"] == "retrieval" and len(ds["queries"]) == 10 and ds["source"]["repo"] == "mteb/AutoRAGRetrieval"
    assert "라이선스 MIT" in ds["description"]
    job = _wait(client, client.post("/api/public-benchmarks/korsts/import", json={"max_queries": 20}).json())
    assert job["status"] == "done" and len(client.get("/api/datasets/pub_korsts").json()["pairs"]) == 20
    imported = {c["key"]: c["imported"] for c in client.get("/api/public-benchmarks").json()}
    assert imported["korsts"] and imported["ko_strategyqa"] is None
    assert client.delete("/api/datasets/pub_korsts").status_code == 200
