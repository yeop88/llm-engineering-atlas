"""2순위(답변 검증): 일치도 계산 · 의미 · 혼합 검증 · 검증 모델 없을 때 글자로 돌아가기 · 라벨 · 일치도 API · 판정 문장 만들기."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import answer
from app.stages.rag import verify as vf
from tests.test_rag import DOCS, _model, _wait


def test_agreement_metrics():
    a = vf.agreement([True, True, False, False], [True, False, False, True])
    assert a["accuracy"] == 0.5 and a["precision"] == 0.5 and a["recall"] == 0.5 and a["kappa"] == 0.0
    perfect = vf.agreement([True, False, True], [True, False, True])
    assert perfect["kappa"] == 1.0 and perfect["f1"] == 1.0


def test_compare_methods_finds_threshold():
    # 사람: 앞 둘은 근거 있음(바꿔 말해 글자 겹침은 낮지만 의미는 높음), 뒤 둘은 근거 없음
    rows = [{"label": True, "lexical": 0.2, "semantic": 0.9, "llm": True}, {"label": True, "lexical": 0.6, "semantic": 0.85, "llm": True},
            {"label": False, "lexical": 0.1, "semantic": 0.6, "llm": True}, {"label": False, "lexical": 0.3, "semantic": 0.55, "llm": False}]  # fmt: skip
    r = vf.compare_methods(rows, lexical_ok=0.5)
    assert r["semantic"]["kappa"] == 1.0 and 0.6 < r["semantic"]["threshold"] <= 0.85
    assert r["lexical"]["recall"] == 0.5 and r["hybrid"]["kappa"] == 1.0 and r["llm"]["fp"] == 1 and r["semantic_sweep"]


def test_verify_falls_back_to_lexical(monkeypatch):
    monkeypatch.setattr(get_settings(), "verify_model", "없는/모델")
    out = answer.verify("배수 필터를 청소하세요 [1].", [{"text": "배수 필터를 청소하세요."}], method="semantic")
    assert out["method"] == "lexical" and "semantic 실패" in out["fallback"] and out["supported_ratio"] == 1.0  # 평가가 멈추지 않게


def test_semantic_and_hybrid(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "verify_model", "nlpai-lab/KURE-v1")
    monkeypatch.setattr(get_settings(), "verify_semantic_ok", 0.5)
    srcs = [{"text": "세탁기 배수가 안 될 때는 배수 필터를 청소하세요. 냉장고 소음은 수평을 맞추면 줄어듭니다."}]
    text = "세탁기 물이 안 빠지면 배수 필터 청소 [1]. 금리는 3%입니다 [1]."
    lex = answer.verify(text, srcs, method="lexical")
    sem = answer.verify(text, srcs, method="semantic")
    hyb = answer.verify(text, srcs, method="hybrid")
    assert sem["method"] == "semantic" and all("semantic" in s for s in sem["sentences"]) and sem["semantic_seconds"] >= 0
    first_sem, second_sem = (s["semantic"] for s in sem["sentences"])
    assert first_sem > second_sem  # 근거와 같은 뜻의 문장이 무관한 문장보다 가깝다
    assert hyb["supported_ratio"] >= lex["supported_ratio"]  # 혼합은 글자로 통과한 것을 잃지 않는다


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        if "판정하는 검토자" in system:
            text = json.dumps({"judgements": [{"n": 1, "supported": True, "reason": "근거와 같음"}]}, ensure_ascii=False)
        else:
            text = "배수 필터를 청소하세요 [1]."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))


def test_verify_api_flow(client, fake_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "verify_model", "nlpai-lab/KURE-v1")
    cid = client.post("/api/collections", json={"name": "검증 보정"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    idx = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": _model(client, "nlpai-lab/KURE-v1")}).json()
    assert _wait(client, idx["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    s = client.post(
        f"/api/collections/{cid}/eval-sets", json={"name": "e", "items": [{"query": "세탁기 배수", "doc_ids": [docs["AS안내.md"]]}]}
    ).json()
    done = _wait(
        client, client.post("/api/verify/sample", json={"eval_set_id": s["id"], "config": {"mode": "dense", "index_id": idx["id"]}}).json()
    )
    assert done["status"] == "done", done.get("error")
    item = done["result"]["items"][0]
    assert (
        item["sentence"].startswith("배수 필터")
        and item["scores"]["llm"] is True
        and item["scores"]["semantic"] is not None
        and "[1]" in item["sources"]
    )
    labels = [
        item | {"label": True},
        item | {"sentence": "금리는 3%입니다 [1].", "label": False, "scores": {"lexical": 0.0, "semantic": 0.2, "llm": True}},
    ]
    assert client.post("/api/verify/labels", json={"collection_id": cid, "items": labels}).json()["saved"] == 2
    ag = client.get(f"/api/verify/agreement?collection_id={cid}").json()
    assert ag["n"] == 2 and ag["lexical"]["n"] == 2 and "threshold" in ag["semantic"] and ag["llm"]["fp"] == 1
    lab = client.get(f"/api/verify/labels?collection_id={cid}").json()
    assert client.delete(f"/api/verify/labels/{lab['items'][0]['id']}").status_code == 200
    assert client.get("/api/verify/settings").json()["method"] == "lexical"
    client.delete(f"/api/collections/{cid}")
