"""데이터 계보 · 근거(PV1~PV8): 답 → 문장 → 주장 → 인용 · 근거 판정(표시 빠짐), 같은 질문 · 다른 답의 부딪힘, 요청 기록 → 청크 → 문서 판 사슬 · API.

주장 판정은 규칙 그대로 잰다 — 특히 '글은 근거와 겹치는데 숫자 · 조문이 근거에 없는' 주장이 약함으로 걸리는지(가장 위험한 경우).
계보 사슬은 요청 기록을 직접 넣어 만든다(근거 청크 번호만 있으면 문서 · 판까지 이어지는지). 같은 원본을 다시 올려 옛 판을 만든다.
"""

import pytest

from app.core.db import Chunk, Document, SessionLocal, Trace
from app.stages.provenance import claims, lineage
from tests.helpers import wait_job

SRC = [{"text": "근로기준법 제43조에 따라 임금은 매월 1회 이상 일정한 날짜에 지급하여야 한다."},
       {"text": "세탁기 배수가 안 될 때는 배수 필터를 청소하세요."}]  # fmt: skip


# ── PV5~PV7 주장 · 근거 ───────────────────────────────────────────────────
def test_marks_and_split():
    assert claims.marks("제43조의2 에 따라 30일 안에 E4 코드") == ["제43조의2", "30일", "E4"]
    cs = claims.split_claims("임금은 매월 1회 이상 지급합니다 [1]. 필터를 청소하고, 전원을 다시 켜세요 [2].")
    assert [c["cites"] for c in cs] == [[1], [2], [2]]  # 인용은 문장 단위 — 그 문장의 주장들이 함께 쓴다
    assert "필터" in cs[1]["claim"] and "전원" in cs[2]["claim"]  # 쉼표에서 주장 둘로


def test_support_levels():
    strong = claims.support("임금은 매월 1회 이상 일정한 날짜에 지급하여야 한다", SRC, [1])
    assert strong["level"] == "strong" and strong["best_source"] == 1 and strong["cite_matches_best"]
    # 글은 겹치는데 숫자가 근거에 없다 — 약함(가장 위험)
    weak = claims.support("임금은 매월 2회 이상 일정한 날짜에 지급하여야 한다", SRC, [1])
    assert weak["level"] == "weak" and weak["marks_missing"] == ["2회"]
    assert claims.support("하늘이 파랗고 바다가 넓다", SRC, [1])["level"] == "none"
    unc = claims.support("세탁기 배수가 안 될 때는 배수 필터를 청소하세요", SRC, [])
    assert unc["level"] == "uncited" and unc["best_source"] == 2
    bad = claims.support("세탁기 배수 필터를 청소하세요", SRC, [9])
    assert not bad["cite_valid"]  # 없는 근거 번호


def test_analyze_summary():
    a = claims.analyze("근로기준법 제43조에 따라 임금은 매월 1회 이상 일정한 날짜에 지급하여야 한다 [1]. 배수 필터를 청소하세요 [1].", SRC)
    assert a["n"] == 2 and a["strong"] == 1.0  # 두 주장 모두 어떤 근거와는 강하게 겹친다
    assert a["cite_precision"] == 0.5  # 둘째 주장은 2번 근거와 겹치는데 1번을 인용
    assert a["traceable"] == 0.5  # 엉뚱한 근거를 인용한 주장은 인용을 따라가도 근거가 안 나온다 — 추적 불가


def test_contradictions():
    rows = [{"id": 1, "question": "임금은 한 달에 몇 번 주나요?", "answer": "매월 1회 이상 [1]."},
            {"id": 2, "question": "임금은 한 달에 몇 번 주나요?", "answer": "매월 2회 이상입니다."},
            {"id": 3, "question": "세탁기 배수 문제", "answer": "필터 청소 1회"}]  # fmt: skip
    out = claims.contradictions(rows)
    assert len(out) == 1 and out[0]["a"] == 1 and out[0]["b"] == 2
    assert out[0]["only_a"] == ["1회"] and out[0]["only_b"] == ["2회"]  # 인용 번호 [1] 은 표시로 세지 않는다
    assert claims.same_question("임금은 한 달에 몇 번", "임금은 한 달에 몇 번") and not claims.same_question("", "x")


# ── PV1~PV4 계보 사슬 ─────────────────────────────────────────────────────
def _trace_with_chunk(cid: int, filename: str) -> tuple[int, int]:
    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.collection_id == cid, Document.filename == filename).order_by(Document.id).first()
        ch = db.query(Chunk).filter(Chunk.document_id == doc.id).first()
        t = Trace(kind="pv_test", question="세탁기 배수가 안 될 때", answer="배수 필터를 청소하세요 [1].",
                  sources=[{"chunk_id": ch.id, "document_id": doc.id, "filename": filename}])  # fmt: skip
        db.add(t)
        db.commit()
        return t.id, doc.id


def test_trace_chain_and_versions(client, rag_collection):
    tid, did = _trace_with_chunk(rag_collection["cid"], "AS안내.md")
    with SessionLocal() as db:
        ch = lineage.trace_chain(db, tid)
        assert ch["trace"]["id"] == tid
        s = ch["sources"][0]
        assert s["found"] and s["document"]["filename"] == "AS안내.md" and s["chunk_set"]["id"] == rag_collection["cs"]
        assert s["collection"]["id"] == rag_collection["cid"] and s["versions"][-1]["current"] and not s["stale"]
        assert lineage.trace_chain(db, 999999) is None
        assert lineage.chunk_chain(db, None, None) == {"found": False}
    # 같은 원본(같은 파일 이름)을 고쳐 다시 올리면 앞의 문서는 옛 판 — 그 근거로 한 답은 stale
    client.post(
        f"/api/collections/{rag_collection['cid']}/documents",
        files=[("files", ("AS안내.md", "# 제품 AS 안내\n새 판: 배수 필터를 매주 청소하세요.".encode(), "text/plain"))],
    )
    with SessionLocal() as db:
        s = lineage.trace_chain(db, tid)["sources"][0]
        assert len(s["versions"]) == 2 and s["stale"] and s["versions"][0]["document_id"] == did


# ── API ──────────────────────────────────────────────────────────────────
def test_trace_api(client, rag_collection):
    tid, _ = _trace_with_chunk(rag_collection["cid"], "AS안내.md")
    lst = client.get("/api/provenance/traces").json()["traces"]
    assert tid in {t["id"] for t in lst}
    r = client.get(f"/api/provenance/trace/{tid}").json()
    assert r["sources"][0]["found"] and r["claims"]["n"] == 1 and r["claims"]["claims"][0]["cites"] == [1]
    assert client.get("/api/provenance/trace/999999").status_code == 404


def test_analyze_and_contradictions_api(client):
    r = client.post("/api/provenance/analyze", json={"answer": "임금은 매월 2회 지급 [1].", "sources": SRC}).json()
    assert r["n"] == 1 and r["claims"][0]["marks_missing"]
    assert client.post("/api/provenance/analyze", json={"answer": ""}).status_code == 422
    with SessionLocal() as db:
        db.add_all([Trace(kind="pv_test", question="환불은 며칠 안에 되나요 시험", answer="7일 안에 됩니다"),
                    Trace(kind="pv_test", question="환불은 며칠 안에 되나요 시험", answer="14일 안에 됩니다")])  # fmt: skip
        db.commit()
    c = client.get("/api/provenance/contradictions").json()
    assert any(sorted(x["only_a"] + x["only_b"]) == ["14일", "7일"] for x in c["contradictions"]) and c["checked"] >= 2


def test_eval_job(client, rag_collection, scripted_llm):
    job = client.post("/api/provenance/eval", json={"eval_set_id": rag_collection["set"], "max_queries": 2})
    assert job.status_code == 202
    res = wait_job(client, job.json())
    assert res["status"] == "done", res
    assert res["result"]["run_id"]
    assert client.post("/api/provenance/eval", json={"eval_set_id": 999999}).status_code == 400


@pytest.mark.parametrize("url", ["/provenance/trace", "/provenance/check"])
def test_pages_open(client, url):
    assert client.get(url).status_code == 200
