"""파인튜닝: 학습 데이터(누수 제외 · ICT) · 프롬프트 적용 · 실행 흐름(가짜 학습) · 기록 · 삭제."""

from pathlib import Path

import pytest

from app.finetune import data, service, trainer
from app.services.model_manager import ModelSpec
from tests.test_rag import DOCS, _wait

PASSAGES = [
    {
        "chunk_id": 1,
        "document_id": 1,
        "text": "공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다. 다만 대통령령으로 정하는 경우에는 괄호 안에 한자를 쓸 수 있다.",
    },
    {
        "chunk_id": 2,
        "document_id": 2,
        "text": "관세청은 7월 1일부터 구매대행업체 등록제를 시행한다. 등록하지 않은 업체는 통관 과정에서 불이익을 받을 수 있다. 등록은 세관에 신청한다.",
    },
]


def test_leak_filter_excludes_eval_evidence():
    keep, n = data.leak_filter(PASSAGES, ["공문서는 어문규범에 맞추어 한글로 작성하여야 한다", ""])
    assert n == 1 and [p["chunk_id"] for p in keep] == [2]
    assert data.leak_filter(PASSAGES, [])[1] == 0


def test_ict_pairs_remove_query_sentence():
    pairs = data.ict_pairs(PASSAGES, seed=1)
    assert len(pairs) == 2
    for p in pairs:
        assert p["anchor"] not in p["positive"] and p["type"] == "ict" and len(p["positive"]) >= 20


def test_resolve_prompts_uses_model_definitions():
    class M:
        prompts = {"query": "query: ", "document": "passage: "}

    def spec(**kw):
        base = dict(id=1, hf_id="x", modalities=("text",), trust_remote_code=False, load_kwargs={}, multimodal_load_kwargs={},
                    query_prompt="", document_prompt="", query_prefix="", document_prefix="", query_kwargs={}, document_kwargs={})  # fmt: skip
        return ModelSpec(**(base | kw))

    assert trainer.resolve_prompts(M(), spec(query_prompt="query", document_prompt="document")) == {
        "anchor": "query: ",
        "positive": "passage: ",
    }
    spec2 = spec(query_prefix="질문: ")
    assert trainer.resolve_prompts(M(), spec2) == {"anchor": "질문: "}  # 문서 쪽은 없음


@pytest.fixture
def fake_train(monkeypatch):
    calls = []

    def train(job, spec, pairs, out_dir, params, log):
        calls.append({"spec": spec, "pairs": pairs, "params": params})
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "model.safetensors").write_bytes(b"x" * 10)
        for step, loss in enumerate([2.0, 1.2, 0.8], 1):
            log.append({"step": step, "epoch": step / 3, "loss": loss})
            if job:
                job.update(step / 3, f"학습 {step}/3")
        return {"seconds": 1.0, "steps": 3, "train_pairs": len(pairs), "eval_pairs": 0, "first_loss": 2.0, "final_loss": 0.8,
                "eval_loss": None, "prompts": {"anchor": "query: "}, "dim": 16, "max_seq_length": 128, "device": "cpu"}  # fmt: skip

    monkeypatch.setattr(trainer, "train", train)
    return calls


def test_finetune_flow(client, fake_train):
    cid = client.post("/api/collections", json={"name": "파인튜닝 테스트"}).json()["id"]
    topics = ["관세", "공문서", "도서관", "주차장", "건강검진", "연차휴가", "보안", "환불", "교육", "예산"]
    long_docs = {  # 학습 쌍을 넉넉히 만들 만큼 문장이 많은 문서
        f"{t}.txt": " ".join(f"{t} 규정 제{i}조는 {t} 업무의 {i}번째 절차를 정한 것이며 담당 부서가 매년 점검한다." for i in range(1, 9))
        for t in topics
    } | DOCS
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in long_docs.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "sentence", "size": 120, "overlap_sentences": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    es = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={
            "name": "평가",
            "items": [
                {"query": "해외직구 구매대행업체 등록제", "doc_ids": [docs["보도자료.txt"]], "evidence": "구매대행업체 등록제를 시행한다"}
            ],
        },
    ).json()
    base = next(m for m in client.get("/api/models").json() if m["hf_id"] == "nlpai-lab/KURE-v1")
    body = {
        "base_model_id": base["id"],
        "collection_id": cid,
        "chunk_set_id": cs["id"],
        "data_method": "ict",
        "n_passages": 40,
        "min_chars": 20,
        "eval_set_id": es["id"],
    }
    # 검증: 다른 컬렉션의 평가 세트, LLM 미설정
    assert client.post("/api/finetune", json=body | {"eval_set_id": 999999}).status_code == 400
    r = client.post("/api/finetune", json=body).json()
    assert r["status"] == "pending" and r["config"]["exclude_eval_set_ids"] == [es["id"]]  # 비교용 세트는 자동으로 학습에서 제외
    job = _wait(client, r["job"])
    assert job["status"] == "done", job
    run = client.get(f"/api/finetune/{r['id']}").json()
    assert run["status"] == "done" and run["data_stats"]["pairs"] >= 8 and run["data_stats"]["excluded_for_eval"] >= 1
    assert all("구매대행업체 등록제를 시행한다" not in p["positive"] for p in fake_train[0]["pairs"])  # 누수 없음
    assert [e["loss"] for e in run["log"]] == [2.0, 1.2, 0.8]
    cmp_ = run["metrics"]["comparison"]
    assert set(cmp_) >= {"dense", "hybrid", "queries"} and "paired" in cmp_["dense"] and cmp_["eval_set"]["n"] == 1
    model = client.get(f"/api/models/{run['output_model_id']}").json()
    assert (
        model["source"] == "finetuned" and model["cached"] and "파인튜닝" in model["tags"] and model["query_prompt"] == base["query_prompt"]
    )
    out = Path(model["hf_id"])
    card = client.get(f"/api/finetune/{r['id']}/card").text
    assert (out / "README.md").read_text(encoding="utf-8") == card
    assert "## 학습 데이터" in card and "누수 방지" in card and "## 학습 전후 비교" in card
    # 다시 비교 (검색 수정 뒤 등): 결과와 모델 카드가 갱신된다
    assert client.post(f"/api/finetune/{r['id']}/compare?eval_set_id=999999").status_code == 400
    job = _wait(client, client.post(f"/api/finetune/{r['id']}/compare").json())
    assert job["status"] == "done", job
    again = client.get(f"/api/finetune/{r['id']}").json()
    assert "recompared_at" in again["metrics"] and "paired" in again["metrics"]["comparison"]["dense"]
    # 삭제: 모델까지
    assert client.delete(f"/api/finetune/{r['id']}?delete_model=true").json()["model"]["hf_id"] == model["hf_id"]
    assert not out.exists() and client.get(f"/api/models/{run['output_model_id']}").status_code == 404
    client.delete(f"/api/collections/{cid}")


def test_finetune_llm_requires_config(client, monkeypatch):
    from app.config import get_settings

    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "openai_model", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    cid = client.post("/api/collections", json={"name": "파인튜닝 LLM"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", ("a.txt", "가나다 라마바 사아자. " * 30, "text/plain"))])
    cs = client.post(f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0}}).json()
    assert _wait(client, cs["job"])["status"] == "done"
    base = next(m for m in client.get("/api/models").json() if m["hf_id"] == "nlpai-lab/KURE-v1")
    r = client.post(
        "/api/finetune", json={"base_model_id": base["id"], "collection_id": cid, "chunk_set_id": cs["id"], "data_method": "llm"}
    )
    assert r.status_code == 400 and "LLM" in r.json()["detail"]
    client.delete(f"/api/collections/{cid}")


def test_model_card_without_comparison():
    from app.db import FinetuneRun

    r = FinetuneRun(
        id=9, name="x", status="error", base_hf_id="b", config={"data_method": "ict", "epochs": 1}, data_stats={}, metrics={}, error="boom"
    )
    r.created_at = __import__("datetime").datetime(2026, 10, 18)
    card = service.model_card(r, None, None)
    assert card.startswith("# x") and "## 오류" in card and "boom" in card and "학습 전후 비교" not in card


def test_mark_interrupted_on_restart():
    from app.crud import mark_interrupted
    from app.db import EvalSet, FinetuneRun, SessionLocal

    with SessionLocal() as db:
        r = FinetuneRun(name="끊김", status="running", base_hf_id="x", config={}, data_stats={}, log=[], metrics={})
        db.add(r)
        db.commit()
        assert mark_interrupted(db) >= 1
        db.refresh(r)
        assert r.status == "error" and "재시작" in r.error and r.finished_at
        assert not db.query(EvalSet).filter(EvalSet.status == "building").count()
