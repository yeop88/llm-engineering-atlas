"""온디바이스 · 엣지 API(/api/edge): 추천 → 팩 만들기 · 검색 · 평가 → 기기에서 묻기(오프라인 흉내) → 기기 등록 · 동기화 →
기록 올리기(개인정보 재검사) → 미룬 요청 처리. 가짜 임베딩 · 가짜 LLM 만 쓰고, 팩 폴더는 임시 폴더로 바꾼다."""

import pytest

from app.core import crud
from app.core.config import get_settings
from app.core.db import SessionLocal, TestRun
from app.stages.edge import pack as pk
from tests.helpers import wait_job


@pytest.fixture(autouse=True)
def pack_dir(tmp_path, monkeypatch):
    # PACK_DIR 는 저장소 data/ 아래(BASE_DIR) — 백그라운드 작업까지 같은 모듈 값을 보므로 바꿔 끼우면 실제 폴더에 쓰지 않는다
    monkeypatch.setattr(pk, "PACK_DIR", tmp_path / "packs")


@pytest.fixture
def gguf_dir(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    for n, size in (("gemma-4-E4B-it-Q4_K_M.gguf", 3000), ("mmproj-gemma-4-E4B-it-f16.gguf", 10), ("Qwen3-4B-Q4_K_M.gguf", 2000)):
        (d / n).write_bytes(b"x" * size)
    monkeypatch.setattr(get_settings(), "llm_models_dir", d)
    return d


def _build(client, rag_collection, name="as", precision="int8", **scope):
    r = client.post("/api/edge/packs", json={"name": name, "index_id": rag_collection["idx"], "precision": precision} | scope)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json())
    assert job["status"] == "done", job
    return job["result"]


def test_profiles_and_recommend(client, gguf_dir):
    p = client.get("/api/edge/profiles").json()
    assert set(p["profiles"]) == {"phone", "tablet", "kiosk", "laptop"} and "binary_rescore" in p["precisions"]
    with SessionLocal() as db:
        empty = db.query(TestRun).filter(TestRun.kind == "quant_vectors").count() == 0
    if empty:  # 실측이 없으면 추측하지 않고 어디서 재는지 알려 준다
        r = client.post("/api/edge/recommend", json={"profile": "tablet"})
        assert r.status_code == 400 and "/quant/vectors" in r.json()["detail"]
    assert client.post("/api/edge/recommend", json={"profile": "냉장고"}).status_code == 400
    rows = lambda w, prec, rec, ram: {"weight": w, "dim": 1024, "precision": prec, "status": "ok", "is_base": prec == "float32" and w == "w_fp32",  # noqa: E731
                                      "metrics": {"recall@10": rec}, "bytes": {"ram": ram, "disk": ram}}  # fmt: skip
    with SessionLocal() as db:
        crud.record_run(db, "quant_vectors", ["nlpai-lab/KURE-v1"], "벡터 양자화", {}, {"results": [
            {"hf_id": "nlpai-lab/KURE-v1", "status": "ok", "rows": [rows("w_fp32", "float32", 0.9, 4096), rows("w_int8", "binary_rescore", 0.86, 1152),
                                                                     rows("w_int8", "int4", 0.5, 512) | {"status": "error"}]}]}, 0)  # fmt: skip
        # 두 평가 세트: 파일 둘을 잰 세트(오래됨)와 하나만 잰 세트(최근) — 세트를 섞으면 순서가 뒤집히므로 많이 잰 세트 하나만
        crud.record_run(db, "quant_llm", [], "LLM 양자화", {}, {"eval_set": {"name": "24문항"}, "results": [
            {"model": "gemma-4-e4b", "status": "ok", "quality": 0.83, "mean_seconds": 4.0},
            {"model": "qwen3-4b", "status": "ok", "quality": 0.7, "mean_seconds": 3.0}]}, 0)  # fmt: skip
        crud.record_run(db, "quant_llm", [], "LLM 양자화", {}, {"eval_set": {"name": "법률"}, "results": [
            {"model": "qwen3-4b", "status": "ok", "quality": 0.99, "mean_seconds": 3.0}]}, 0)  # fmt: skip
    r = client.post("/api/edge/recommend", json={"profile": "tablet", "n_chunks": 5000, "ctx": 4096}).json()
    llms = {x["name"]: x for x in r["llms"]}
    assert set(llms) == {"gemma-4-E4B-it-Q4_K_M.gguf", "Qwen3-4B-Q4_K_M.gguf"}  # 비전 투영 파일은 답변 모델이 아님
    assert llms["Qwen3-4B-Q4_K_M.gguf"]["quality"] == 0.7 and llms["Qwen3-4B-Q4_K_M.gguf"]["eval_set"] == "24문항"
    assert llms["gemma-4-E4B-it-Q4_K_M.gguf"]["vision"] and llms["gemma-4-E4B-it-Q4_K_M.gguf"]["ram_gb"] == pytest.approx(0.24, abs=0.01)
    # 메모리 = 임베딩(파라미터 × 가중치 바이트) + 색인 + LLM(파일 + KV) — 상태가 error 인 행은 후보가 아니다
    assert r["with_llm"] and r["with_llm"][0]["llm"] == "gemma-4-E4B-it-Q4_K_M.gguf"
    assert {x["precision"] for x in r["search_only"]} == {"float32", "binary_rescore"}
    assert r["with_llm"][0]["sources"][0].startswith("quant_vectors #")
    small = client.post("/api/edge/recommend", json={"profile": "tablet", "budget_gb": 0.5}).json()
    assert small["profile"]["budget_gb"] == 0.5 and small["with_llm"] == [] and small["nearest"]


def test_pack_build_search_eval_delete(client, rag_collection):
    lst = client.get("/api/edge/packs").json()
    assert any(i["id"] == rag_collection["idx"] for i in lst["indexes"])
    m = _build(
        client, rag_collection, product_model=[], doc_ids=[rag_collection["docs"]["AS안내.md"], rag_collection["docs"]["보도자료.txt"]]
    )
    assert m["version"] == 1 and m["n_docs"] == 2 and m["precision"] == "int8"
    g = client.get("/api/edge/packs/as").json()
    assert g["versions"] == [1] and g["sample"] and "chunk_ids" not in g
    assert client.get("/api/edge/packs/없음").status_code == 404 and client.get("/api/edge/packs/as?version=5").status_code == 404
    s = client.post("/api/edge/packs/as/search", json={"query": "세탁기 배수가 안 될 때", "k": 2}).json()
    assert s["results"][0]["doc_id"] == rag_collection["docs"]["AS안내.md"] and s["search_ms"] >= 0 and s["cache"] is None
    job = wait_job(client, client.post("/api/edge/packs/as/eval", json={"eval_set_id": rag_collection["set"], "k": 3}).json())
    assert job["status"] == "done", job
    ev = job["result"]
    # 공문서 질문은 팩 범위 밖(법령 문서를 안 담음) — 압축 손실이 아니라 범위 때문에 못 찾는 것으로 따로 센다
    assert ev["n"] == 2 and ev["n_in_scope"] == 1 and ev["in_scope"]["pack_hit"] == 1.0 and ev["server_hit"] is not None
    assert ev["run_id"] and ev["pack"]["name"] == "as"
    assert client.post("/api/edge/packs/as/eval", json={"eval_set_id": 999999}).status_code == 400
    bad = client.post("/api/edge/packs", json={"name": "x y", "index_id": rag_collection["idx"]})
    assert bad.status_code == 422  # 팩 이름은 폴더 이름이 된다 — 경로 문자를 막는다
    assert client.post("/api/edge/packs", json={"name": "x", "index_id": 999999}).status_code == 400
    fail = wait_job(
        client, client.post("/api/edge/packs", json={"name": "none", "index_id": rag_collection["idx"], "doc_ids": [999999]}).json()
    )
    assert fail["status"] == "error" and "범위" in fail["error"]
    assert client.delete("/api/edge/packs/as").json() == {"deleted": "as"}
    assert client.delete("/api/edge/packs/as").status_code == 404


def test_offline_ask_and_capabilities(client, rag_collection, scripted_llm, gguf_dir):
    _build(client, rag_collection)
    caps = client.get("/api/edge/capabilities", params={"pack": "as", "llm_file": "gemma-4-E4B-it-Q4_K_M.gguf"}).json()
    f = {x["key"]: x["status"] for x in caps["features"]}
    assert f["search"] == "ok" and f["answer"] == "ok" and f["photo"] == "ok" and f["law"] == "defer" and caps["llm"]["vision"]
    unknown = client.get("/api/edge/capabilities", params={"llm_file": "서버모델"}).json()
    assert unknown["llm"]["ram_gb"] is None and {x["key"]: x["status"] for x in unknown["features"]}["search"] == "no"

    # LLM 없이: 근거만
    a = client.post("/api/edge/ask", json={"pack": "as", "question": "세탁기 배수가 안 될 때", "use_llm": False}).json()
    assert a["mode"] == "sources" and a["sources"][0]["doc_id"] == rag_collection["docs"]["AS안내.md"] and a["pack_version"] == 1
    # 기기 LLM 으로 근거 답 + 검증
    a = client.post("/api/edge/ask", json={"pack": "as", "question": "세탁기 배수가 안 될 때", "model": "fake"}).json()
    assert a["mode"] == "answer" and "배수 필터" in a["answer"] and "supported_ratio" in a["verify"]
    # 서버가 필요한 질문: 연결 안 됨 → 기기 대기열, 연결됨 → 서버 서비스 답변
    client.post("/api/edge/devices", json={"id": "tab-1", "pack": "as"})
    q = client.post("/api/edge/ask", json={"pack": "as", "question": "현행 시행령 개정 내용", "device_id": "tab-1"}).json()
    assert q["mode"] == "defer" and q["defer"] == "law" and q["queued"]
    on = client.post("/api/edge/ask", json={"pack": "as", "question": "현행 시행령 개정 내용", "online": True, "model": "fake"}).json()
    assert on["server"].get("answer") and "queued" not in on
    ev = client.get("/api/edge/events", params={"device_id": "tab-1", "kind": "deferred"}).json()["events"]
    assert ev[0]["status"] == "queued" and ev[0]["payload"]["type"] == "law"
    client.delete("/api/edge/devices/tab-1")


def test_device_sync_upload_process(client, rag_collection, scripted_llm):
    _build(client, rag_collection, doc_ids=[rag_collection["docs"]["AS안내.md"]])
    d = client.post("/api/edge/devices", json={"id": "kiosk-7", "name": "매장 7", "profile": "kiosk", "pack": "as"}).json()
    assert not d["ok"] and "동기화 기록 없음" in d["flags"]
    # 처음 동기화는 전체, 다음 판이 나오면 증분
    s1 = client.post("/api/edge/devices/kiosk-7/sync", json={}).json()
    assert s1["delta"]["mode"] == "full" and s1["device"]["version"] == 1 and s1["device"]["ok"]
    _build(client, rag_collection, doc_ids=[rag_collection["docs"]["AS안내.md"], rag_collection["docs"]["법령.txt"]])
    lst = client.get("/api/edge/devices").json()
    me = next(x for x in lst["devices"] if x["id"] == "kiosk-7")
    assert any("뒤처짐" in f for f in me["flags"]) and lst["summary"]["behind"] >= 1
    s2 = client.post("/api/edge/devices/kiosk-7/sync", json={}).json()
    assert s2["delta"]["mode"] == "delta" and s2["delta"]["verified"] and s2["delta"]["added_docs"] and s2["device"]["version"] == 2
    dl = client.get("/api/edge/packs/as/delta", params={"from_version": 1, "content": True}).json()
    assert dl["send_chunks"] == len(dl["chunks"]) and dl["arrays"]
    assert client.post("/api/edge/devices/없는기기/sync", json={}).status_code == 404

    # 대기열에 쌓인 미룬 요청(개인정보 포함)도 함께 올라가고, 서버는 다시 검사한다
    client.post("/api/edge/ask", json={"pack": "as", "question": "현행 시행령 개정 내용 010-1234-5678 로 알려줘", "device_id": "kiosk-7"})
    up = client.post("/api/edge/devices/kiosk-7/upload", json={"events": [
        {"kind": "feedback", "payload": {"question": "김철수 010-9999-8888", "rating": 1, "customer": "김철수", "usage": "검색 2회"}}]}).json()  # fmt: skip
    assert up["stored"] == 2 and up["deferred"] == 1 and up["violations"] == 0 and up["stats"]["usage"]["n"] == 1
    # 기기가 마스킹 없이 올린 경우(prepare=False): 서버가 찾아 가린 값만 저장하고 위반을 남긴다
    leak = client.post("/api/edge/devices/kiosk-7/upload", json={"prepare": False, "events": [
        {"kind": "log", "payload": {"question": "연락처 010-5555-6666", "customer": "박영수"}}]}).json()  # fmt: skip
    assert leak["violations"] >= 2
    evs = client.get("/api/edge/events", params={"device_id": "kiosk-7"}).json()["events"]
    blob = str([e["payload"] for e in evs])
    assert "010-5555-6666" not in blob and "010-9999-8888" not in blob and "010-1234-5678" not in blob and "박영수" not in blob
    assert next(x for x in client.get("/api/edge/devices").json()["devices"] if x["id"] == "kiosk-7")["pii_flags"] >= 1

    # 미룬 요청 처리 → 다음 동기화 때 기기로
    job = wait_job(client, client.post("/api/edge/events/process", json={"model": "fake"}).json())
    assert job["status"] == "done" and job["result"]["processed"] >= 1
    done = client.get("/api/edge/events", params={"device_id": "kiosk-7", "kind": "deferred"}).json()["events"]
    assert done[0]["status"] == "processed" and done[0]["result"].get("answer")
    assert client.post("/api/edge/events/process", json={}).status_code == 400  # 처리할 것이 없음
    ov = client.get("/api/edge/overview").json()
    assert ov["n_devices"] >= 1 and ov["events"].get("processed", 0) >= 1 and ov["packs"][0]["name"] == "as"
    assert client.delete("/api/edge/devices/kiosk-7").json() == {"deleted": "kiosk-7"}
    assert client.get("/api/edge/events", params={"device_id": "kiosk-7"}).json()["events"] == []
    assert client.delete("/api/edge/devices/kiosk-7").status_code == 404


def test_privacy_preview(client):
    r = client.post("/api/edge/privacy/preview", json={"events": [{"kind": "feedback", "payload": {"question": "010-1234-5678 로 연락", "photo": "..."}}],
                                                      "policy": {"question": "raw"}}).json()  # fmt: skip
    # 정책을 raw 로 풀면 기기는 그대로 올리지만, 서버 재검사가 잡아 가린 값만 저장한다
    assert "010-1234-5678" in r["events"][0]["payload"]["question"] and r["report"]["dropped"] == ["photo"]
    chk = r["server_check"][0]
    assert chk["violations"] and "010-1234-5678" not in chk["stored"]["question"] and r["rules"] == ["raw", "masked", "stats", "never"]
