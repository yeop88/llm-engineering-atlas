"""문서 검색 평가 세트: 근거 판정 · 질문 생성(문장 추출 · LLM) · 검토 · 내보내기."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import evaluation
from tests.test_rag import DOCS, _wait

PASSAGE = "공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다. 다만 대통령령으로 정하는 경우에는 괄호 안에 한자를 쓸 수 있다."


def test_evidence_matching_is_chunking_independent():
    ev = "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"
    assert evaluation.contains_evidence(PASSAGE, ev)
    assert evaluation.contains_evidence("…공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야", ev)  # 경계가 조금 잘려도
    assert not evaluation.contains_evidence("다만 대통령령으로 정하는 경우에는 괄호 안에 한자를 쓸 수 있다.", ev)
    assert evaluation.lexical_overlap(ev, ev) == 1.0 and evaluation.lexical_overlap("휴가 일수", ev) == 0.0


def test_sentence_quality_skips_noise():
    assert evaluation.sentence_quality("□4차산업혁명대비국어빅데이터구축 4,340 4,554 214 4.9") == 0
    assert evaluation.sentence_quality("○번 역 자 문 위 원 회 하 반 기") == 0
    assert evaluation.sentence_quality("○ (공공용어 제·개정 지원) 국어 및 용어 관련 위원회 참여") == 1
    assert evaluation.sentence_quality("이 경우 위촉위원의 과반수가 출석한 경우에만 개의할 수 있다.") == 2


def test_fix_evidence_and_finalize():
    assert evaluation._fix_evidence("공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다.", PASSAGE)[1] is True
    fixed, exact = evaluation._fix_evidence("괄호 안에는 한자를 써도 된다", PASSAGE)  # LLM 이 표현을 바꿔 적음
    assert not exact and fixed.startswith("다만")
    items, stats = evaluation.finalize(
        [
            {"query": "공문서는 무슨 글자로?", "doc_ids": [1], "evidence": "한글로 작성", "type": "fact"},
            {"query": "공문서는  무슨 글자로?", "doc_ids": [1], "evidence": "한글로 작성", "type": "fact"},  # 공백만 다른 중복
            {"query": "한자는 언제?", "doc_ids": [2], "evidence": "", "type": "manual"},
        ]
    )
    assert [it["id"] for it in items] == ["q1", "q2"] and stats["duplicates_removed"] == 1
    assert stats["documents"] == 2 and stats["with_evidence"] == 1 and stats["by_type"] == {"fact": 1, "manual": 1}


def test_from_llm_parses_and_reports(monkeypatch):
    passages = [{"chunk_id": i, "document_id": 7, "text": PASSAGE, "filename": "법.txt", "title": "국어기본법"} for i in (1, 2)]
    reply = {
        "questions": [
            {
                "type": "fact",
                "question": "공문서는 어떤 문자로 써야 하나요?",
                "evidence": "공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다.",
            },
            {"type": "situation", "question": "구청 공지문에 한자를 넣어도 되나요?", "evidence": "괄호 안에는 한자를 써도 된다"},
            {"type": "weird", "question": "  "},
        ]
    }
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (reply, {"usage": {"input_tokens": 100, "output_tokens": 20}}))
    items, stats = evaluation.from_llm(llm.LLMConfig("openai", "m"), passages, ["fact", "situation"], concurrency=2)
    assert len(items) == 4 and stats["calls"] == 2 and stats["input_tokens"] == 200 and stats["evidence_fixed"] == 2
    assert items[0]["doc_ids"] == [7] and items[0]["source_chunk_id"] == 1 and items[1]["type"] == "situation"

    def boom(*a, **k):
        raise llm.LLMError("HTTP 401")

    monkeypatch.setattr(llm, "chat_json", boom)
    with pytest.raises(llm.LLMError):  # 설정 오류로 계속 실패하면 멈춘다
        evaluation.from_llm(llm.LLMConfig("openai", "m"), passages * 3, ["fact"], concurrency=1)


@pytest.fixture
def collection(client):
    cid = client.post("/api/collections", json={"name": "평가 세트 테스트"}).json()["id"]
    files = [("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()]
    client.post(f"/api/collections/{cid}/documents", files=files)
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 150, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    yield cid, cs["id"], docs
    client.delete(f"/api/collections/{cid}")


def test_eval_set_api(client, collection, monkeypatch):
    cid, cs_id, docs = collection
    # 문장 추출 (LLM 없음)
    gen = client.post(
        f"/api/collections/{cid}/eval-sets/generate", json={"method": "sentence", "chunk_set_id": cs_id, "n_passages": 6, "min_chars": 40}
    )
    assert gen.status_code == 202 and gen.json()["status"] == "building"
    assert _wait(client, gen.json()["job"])["status"] == "done"
    s = client.get(f"/api/eval-sets/{gen.json()['id']}").json()
    assert s["status"] == "ready" and s["n_items"] >= 3 and s["stats"]["documents"] >= 2
    assert all(it["query"] == it["evidence"] and it["doc_ids"][0] in docs.values() for it in s["items"])

    # LLM 미설정 → 400, 가짜 OpenAI 호환 서버로 생성
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "openai_model", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    assert client.post(f"/api/collections/{cid}/eval-sets/generate", json={"chunk_set_id": cs_id}).status_code == 400
    monkeypatch.setattr(st, "openai_model", "fake")

    def handler(request: httpx.Request) -> httpx.Response:
        passage = json.loads(request.content)["messages"][1]["content"].split("<<<\n")[1].split("\n>>>")[0]
        q = {"type": "paraphrase", "question": f"질문 {hash(passage) % 1000}", "evidence": passage[:40]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"questions": [q]})}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    gen = client.post(
        f"/api/collections/{cid}/eval-sets/generate",
        json={"chunk_set_id": cs_id, "n_passages": 4, "min_chars": 40, "styles": ["paraphrase"]},
    ).json()
    assert _wait(client, gen["job"])["status"] == "done"
    s = client.get(f"/api/eval-sets/{gen['id']}").json()
    assert s["config"]["llm"]["model"] == "fake" and s["stats"]["generation"]["calls"] == 4 and s["n_items"] >= 1
    assert all(it["evidence_exact"] for it in s["items"])

    # 직접 입력 · 검증 · 검토(수정·삭제) · 내보내기 · 삭제
    bad = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "x", "items": [{"query": "q", "doc_ids": [999999]}]})
    assert bad.status_code == 400
    law = docs["법령.txt"]
    m = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={
            "name": "직접",
            "items": [
                {"query": "공문서 문자", "doc_ids": [law], "evidence": "한글로 작성"},
                {"query": "직구 등록제", "doc_ids": [docs["보도자료.txt"]]},
            ],
        },
    ).json()
    assert m["n_items"] == 2 and m["method"] == "manual"
    upd = client.patch(
        f"/api/eval-sets/{m['id']}",
        json={"name": "직접 v2", "items": [{"query": "공문서 문자", "doc_ids": [law], "evidence": "한글로 작성"}]},
    ).json()
    assert upd["name"] == "직접 v2" and upd["n_items"] == 1 and upd["stats"]["edited"]
    exp = client.get(f"/api/eval-sets/{m['id']}/export")
    assert "attachment" in exp.headers["content-disposition"] and exp.json()["items"][0]["doc_ids"] == [law]
    assert len(client.get(f"/api/collections/{cid}/eval-sets").json()) == 3
    assert client.delete(f"/api/eval-sets/{m['id']}").status_code == 200
    assert client.get(f"/api/eval-sets/{m['id']}").status_code == 404


# ── 조합 평가 ───────────────────────────────────────────────────────────────
def _chunk(doc, text):
    return {"document_id": doc, "text": text, "filename": f"{doc}.txt"}


def test_judge_evidence_and_doc_ranks():
    item = {"doc_ids": [2], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"}
    results = [
        _chunk(1, "해외직구 등록제"),
        _chunk(1, "다른 내용"),
        _chunk(3, "같은 내용 사본: 공문서는 어문규범에 맞추어 한글로 작성하여야 한다"),
        _chunk(2, "법령 다른 조문"),
    ]
    j = evaluation.judge(results, item, evaluation.grams(item["evidence"]))
    assert j["rank"] == 3  # 근거는 문서 id 와 상관없이 텍스트로 (사본 문서도 정답)
    assert j["doc_rank"] == 3 and j["doc_recall@5"] == 1.0  # 문서 순위는 중복 문서를 한 번만 센다: 1, 3, 2
    m = evaluation.query_metrics(j)
    assert m["hit@1"] == 0 and m["hit@3"] == 1 and m["mrr@10"] == pytest.approx(1 / 3) and m["ndcg@10"] == pytest.approx(0.5)
    no_ev = evaluation.judge(results, {"doc_ids": [2], "evidence": ""}, None)
    assert no_ev["rank"] == 4  # 근거가 없으면 정답 문서의 첫 청크
    assert evaluation.query_metrics(evaluation.judge([], item, evaluation.grams(item["evidence"])))["ndcg@10"] == 0


def test_run_eval_ranks_configs_with_ci():
    items = [
        {
            "id": f"q{i}",
            "query": f"질문{i}",
            "doc_ids": [i],
            "evidence": f"정답 문장 번호 {i} 입니다",
            "type": "fact" if i % 2 else "paraphrase",
        }
        for i in range(30)
    ]

    def search(q, cfg):
        i = int(q[2:])
        hit = _chunk(i, f"정답 문장 번호 {i} 입니다")
        if cfg["label"] == "good":
            res = [hit, _chunk(99, "x")]
        elif cfg["label"] == "broken":
            raise RuntimeError("인덱스 없음")
        else:  # 짝수 질문(다른 표현)은 못 찾음
            res = [_chunk(99, "x"), hit] if i % 2 else [_chunk(99, "x")]
        return {"results": res, "total_ms": 10.0}

    r = evaluation.run_eval(search, items, [{"label": "bad"}, {"label": "good"}, {"label": "broken"}])
    labels = [e["label"] for e in r["results"]]
    assert labels == ["good", "bad", "broken"] and r["results"][2]["status"] == "error"
    good, bad = r["results"][0], r["results"][1]
    assert good["metrics"]["ndcg@10"] == 1.0 and good["ci"]["ndcg@10"] == [1.0, 1.0]
    assert bad["vs_best"]["significant"] and bad["vs_best"]["diff"] < 0
    assert bad["by_type"]["paraphrase"]["ndcg@10"] == 0 and bad["by_type"]["fact"]["ndcg@10"] > 0
    assert r["queries"][0]["ranks"] == [1, None] and "per_query" not in good and good["latency_ms"]["mean"] == 10.0


def test_run_eval_stops_on_cancel():
    from app.core.jobs import Job, JobCancelled

    job = Job(id="x", kind="rag_eval", title="t")
    calls = []

    def search(q, cfg):
        calls.append(cfg["label"])
        job._cancel.set()  # 사용자가 취소 버튼을 누른 상태
        return {"results": [], "total_ms": 1.0}

    items = [{"id": f"q{i}", "query": "질문", "doc_ids": [1], "evidence": ""} for i in range(10)]
    with pytest.raises(JobCancelled):  # 취소는 '그 설정만 실패'가 아니라 평가 전체를 멈춘다
        evaluation.run_eval(search, items, [{"label": "a"}, {"label": "b"}], job)
    assert set(calls) == {"a"}


def test_evaluate_api(client, collection):
    cid, cs_id, docs = collection
    emb = next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == "nlpai-lab/KURE-v1")
    rr = next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == "BAAI/bge-reranker-v2-m3")
    idx = client.post("/api/indexes", json={"chunk_set_id": cs_id, "model_id": emb}).json()
    assert _wait(client, idx["job"])["status"] == "done"
    s = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={"name": "평가", "items": [
            {"query": "해외직구 구매대행업체 등록제 시행", "doc_ids": [docs["보도자료.txt"]]},
            {"query": "공문서는 한글로 작성", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"},
        ]},
    ).json()  # fmt: skip
    configs = [
        {"index_id": idx["id"], "mode": "dense"},
        {"index_id": idx["id"], "mode": "bm25"},  # 인덱스로 지정해도 BM25 는 그 청크 세트로
        {"index_id": idx["id"], "mode": "hybrid", "reranker_id": rr},
    ]
    assert client.post(f"/api/eval-sets/{s['id']}/evaluate", json={"configs": [{"mode": "dense"}]}).status_code == 400
    job = _wait(client, client.post(f"/api/eval-sets/{s['id']}/evaluate", json={"configs": configs}).json())
    assert job["status"] == "done", job
    r = job["result"]
    assert r["n_queries"] == 2 and len(r["results"]) == 3 and all(e["status"] == "ok" for e in r["results"])
    labels = {e["label"] for e in r["results"]}
    assert any("BM25" in lab for lab in labels) and any("+ bge-reranker-v2-m3" in lab for lab in labels)
    assert all("ci" in e and e["latency_ms"]["mean"] > 0 for e in r["results"])
    assert len(r["queries"]) == 2 and len(r["queries"][0]["ranks"]) == 3
    runs = client.get(f"/api/eval-sets/{s['id']}/runs").json()
    assert runs[0]["id"] == r["run_id"] and runs[0]["n_configs"] == 3
