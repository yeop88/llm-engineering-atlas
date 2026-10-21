"""규제 대응 · 컴플라이언스(RC1~RC8): 법령 원문 모양 · 판 비교 · 적용 규칙 · 위험 등급 · 조항-통제 그래프 · 개정 영향 · 사람 판단 기록 · 감사 · AI 응답 고지."""

import pytest

from app.core import tracing
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.stages.compliance import audit, catalog, corpus, lawapi, risk, scope
from tests.helpers import wait_job

PIPA, DECREE = "개인정보 보호법", "개인정보 보호법 시행령"
OLD = {
    PIPA: [("제29조", "안전조치의무", "제29조(안전조치의무) 개인정보처리자는 접속기록 보관 등 안전성 확보에 필요한 조치를 하여야 한다."),
           ("제34조", "개인정보 유출등의 통지ㆍ신고", "제34조(개인정보 유출등의 통지ㆍ신고)\n① 유출을 알게 되었을 때에는 지체 없이 알려야 한다.")],
    DECREE: [("제30조", "개인정보의 안전성 확보 조치", "제30조(개인정보의 안전성 확보 조치)\n① 법 제29조에 따라 내부 관리계획을 수립한다.")],
}  # fmt: skip
NEW = {
    PIPA: [("제29조", "안전조치의무", "제29조(안전조치의무) 개인정보처리자는 내부 관리계획 수립, 접속기록 보관 등 조치를 하여야 한다. <개정 2026.3.10>"),
           ("제30조의3", "새 조항", "제30조의3(새 조항) 새로 생긴 의무."),
           ("제34조", "개인정보 유출등의 통지ㆍ신고", "제34조(개인정보 유출등의 통지ㆍ신고) <개정 2026.3.10>\n① 유출을 알게 되었을 때에는 지체 없이 알려야 한다.")],
    DECREE: OLD[DECREE],
}  # fmt: skip


@pytest.fixture
def fake_law_api(monkeypatch):
    """국가법령정보 API 대신: 법령마다 옛 판(20250101) · 현행(20260101). 개인정보 보호법만 제29조가 바뀌고 제30조의3 이 생긴다."""
    monkeypatch.setattr(get_settings(), "law_api_oc", "test-oc")
    vers = {n: [{"mst": f"{n}-new", "enforced": "20260101", "promulgated": "20251201", "status": "현행", "kind": "일부개정"},
                {"mst": f"{n}-old", "enforced": "20250101", "promulgated": "20241201", "status": "연혁", "kind": "일부개정"}] for n in (PIPA, DECREE)}  # fmt: skip
    monkeypatch.setattr(lawapi, "versions", lambda name: vers.get(name, []))

    def fetch(mst, enforced):
        name, which = mst.rsplit("-", 1)
        arts = (NEW if which == "new" else OLD)[name]
        return {
            "law": name,
            "enforced": enforced,
            "promulgated": "",
            "mst": mst,
            "articles": [{"no": n, "title": t, "text": x} for n, t, x in arts],
        }

    monkeypatch.setattr(lawapi, "fetch", fetch)


def test_article_text_matches_law_chunking_format():
    a = {"조문내용": "제37조의2(자동화된 결정에 대한 정보주체의 권리 등)", "항": [
        {"항내용": "① 정보주체는   거부할 수 있다.", "호": [{"호내용": "1. 첫째", "목": [{"목내용": ["가. 목 하나"]}]}]}, {"항내용": "② 설명을 요구할 수 있다."}]}  # fmt: skip
    assert lawapi._article_text(a).splitlines() == ["제37조의2(자동화된 결정에 대한 정보주체의 권리 등)", "① 정보주체는 거부할 수 있다.", "1. 첫째", "가. 목 하나",
                                                    "② 설명을 요구할 수 있다."]  # fmt: skip
    d = lawapi.document(
        {
            "law": PIPA,
            "enforced": "20260911",
            "promulgated": "20260310",
            "mst": "1",
            "articles": [{"no": "제1조", "title": "목적", "text": "제1조(목적) 목적"}],
        }
    )
    assert d["filename"] == "개인정보 보호법.txt" and d["source"]["enforced"] == "20260911" and d["source"]["kind"] == "statute"


def test_split_and_diff_ignore_amendment_marks():
    old = corpus.split_articles("개인정보 보호법\n\n" + "\n".join(x for _, _, x in OLD[PIPA]))
    new = corpus.split_articles("\n".join(x for _, _, x in NEW[PIPA]))
    assert list(old) == ["제29조", "제34조"] and old["제34조"]["title"] == "개인정보 유출등의 통지ㆍ신고"
    d = corpus.diff(old, new)
    # 제34조는 개정 표시만 붙고 내용이 같아 '바뀜'이 아니다 · 제29조는 본문이 바뀜 · 제30조의3 은 새로 생김
    assert [x["no"] for x in d["changed"]] == ["제29조"] and [x["no"] for x in d["added"]] == ["제30조의3"] and not d["removed"]


def test_rules_controls_profiles_are_consistent():
    ids = {c["id"] for c in catalog.controls()}
    assert all(set(r["controls"]) <= ids for r in catalog.rules())
    assert all(c["probe"] in audit.PROBES for c in catalog.controls())
    assert all(set(g["controls"]) <= ids for g in catalog.rubric()["grades"])
    rules = lambda key: {r["id"] for r in scope.applicable(catalog.profile(key))}  # noqa: E731
    assert {"ai-34", "ai-35", "pi-37-2"} <= rules("example_hiring")  # 고영향 · 자동화된 결정 경로
    assert "ai-31" in rules("as_answer") and "ai-31" not in rules("customer_memory")  # 생성형 AI 가 아니면 고지 의무 규칙이 없다
    assert scope.rule_key(next(r for r in catalog.rules() if r["id"] == "pi-37-2")) == "개인정보 보호법 제37조의2"
    assert len(catalog.obligation_queries()) == 22


def test_risk_grade_from_rubric():
    assert risk.score({"impact": 1, "autonomy": 1, "data": 1}, [])["grade"] == "낮음"
    assert risk.score({"impact": 2, "autonomy": 2, "data": 3}, [])["grade"] == "중간"
    assert risk.score({"impact": 3, "autonomy": 3, "data": 2}, [])["grade"] == "높음"
    hi = risk.score({"impact": 1, "autonomy": 1, "data": 1}, ["high_impact_area"])
    assert hi["grade"] == "높음" and "고영향" in hi["reasons"][-1]  # 고영향 영역은 점수와 상관없이
    assert risk.coverage(hi["controls"])["gaps"] == ["breach_procedure"]


def test_chunk_articles_reads_every_head():
    """짧은 조문이 합쳐진 청크에서도 뒤 조항을 찾는다(첫 머리만 보면 제28조의2 를 영영 못 찾았다)."""
    hit = {"filename": "개인정보 보호법.txt", "text": "제28조(감독) 감독한다.\n제28조의2(가명정보의 처리 등) 가명정보를 처리할 수 있다."}
    assert scope.chunk_articles(hit) == ["개인정보 보호법 제28조", "개인정보 보호법 제28조의2"]
    assert scope.chunk_articles({"filename": "x.txt", "text": "끝부분", "heading": "제3조(원칙)"}) == ["x 제3조"]


def test_import_graph_impact_and_revisions(client, fake_law_api):
    cid = client.post("/api/collections", json={"name": "규제 테스트", "domain": "legal"}).json()["id"]
    done = wait_job(client, client.post(f"/api/compliance/corpus/{cid}/import", json={"laws": [PIPA, DECREE], "date": "20250601"}).json())
    assert done["status"] == "done" and [a["enforced"] for a in done["result"]["added"]] == ["20250101", "20250101"]
    again = wait_job(client, client.post(f"/api/compliance/corpus/{cid}/import", json={"laws": [PIPA]}).json())
    assert again["result"]["skipped"][0]["law"] == PIPA  # 같은 법령의 다른 판은 섞지 않는다
    arts = client.get(f"/api/compliance/corpus/{cid}/articles").json()
    assert arts["total"] == 3 and arts["laws"] == {PIPA: 2, DECREE: 1}

    g = client.post("/api/compliance/graph/build", json={"collection_id": cid}).json()
    assert (
        g["stats"]["labels"]["Control"] == len(catalog.controls()) and "개인정보 보호법 제15조" in g["missing_articles"]
    )  # 자료에 없는 조항은 표시
    imp = client.post("/api/compliance/graph/impact", json={"keys": ["개인정보 보호법 시행령 제30조"]}).json()
    # 시행령 제30조 → '법 제29조' 참조 → 제29조를 근거로 둔 통제(요청 기록 · 위변조 검출 …) → 그 통제를 쓰는 기능
    assert {"audit_log", "integrity"} <= {c["id"] for c in imp["controls"]} and "고객 AS 상담 답변" in imp["features"]
    assert client.get("/api/compliance/graph").json()["built"] is True

    rev = client.get(f"/api/compliance/corpus/{cid}/revisions").json()
    p = next(x for x in rev["laws"] if x["law"] == PIPA)
    assert p["outdated"] and p["current"] == "20260101"
    d = p["current_diff"]
    assert [x["no"] for x in d["changed"]] == ["제29조"] and [x["no"] for x in d["added"]] == ["제30조의3"]
    assert "audit_log" in {c["id"] for c in d["impact"]["controls"]}
    dd = next(x for x in rev["laws"] if x["law"] == DECREE)["current_diff"]
    assert dd["keys"] == [] and "impact" not in dd  # 시행령은 판(시행일)만 새것이고 조문은 같다 — 바뀐 조항 0

    sc = client.get(f"/api/compliance/scope/as_answer?collection_id={cid}").json()
    assert {it["key"]: it["found"] for it in sc["items"]}["개인정보 보호법 제29조"] is True and sc["searched"] is False  # 청크 세트 없음
    client.delete(f"/api/collections/{cid}")


def test_import_requires_law_api_key(client):
    cid = client.post("/api/collections", json={"name": "규제 키 없음"}).json()["id"]
    assert client.post(f"/api/compliance/corpus/{cid}/import", json={}).status_code == 400
    assert client.get(f"/api/compliance/corpus/{cid}/revisions").status_code == 400
    client.delete(f"/api/collections/{cid}")


def test_people_records_reviews_decision_and_audit(client, rag_collection):
    assert client.post("/api/compliance/risk/legal_answer", json={"grade": "낮음"}).status_code == 400  # 제안과 다르면 이유가 필요
    rec = client.post("/api/compliance/risk/legal_answer", json={"grade": "높음", "reason": "법률 판단에 가까움"}).json()
    assert rec["status"] == "draft" and rec["data"]["suggested"] == "중간"
    assert client.post(f"/api/compliance/records/{rec['id']}/confirm").json()["status"] == "confirmed"
    row = next(r for r in client.get("/api/compliance/risk").json() if r["profile"] == "legal_answer")
    assert row["record"]["data"]["grade"] == "높음" and "breach_procedure" in row["coverage"]["gaps"]

    cid = rag_collection["cid"]
    client.post(
        "/api/compliance/data/register",
        json={"subject": f"collection:{cid}", "purpose": "테스트", "basis": "공개 자료", "retention_days": 30},
    )
    inv = client.get("/api/compliance/data").json()
    assert next(c for c in inv["collections"] if c["collection_id"] == cid)["register"]["purpose"] == "테스트"
    assert client.post("/api/compliance/data/purge").status_code == 400  # confirm 없이는 지우지 않는다

    with SessionLocal() as db:
        t = tracing.record(db, kind="answer", user="local", question="질문", answer="답 [1]", model="fake",
                           sources=[{"document_id": 1, "chunk_id": None, "filename": "a.txt"}], verify={"supported_ratio": 1.0}, guard={"notice": True})  # fmt: skip
        tid = t.id
    d = client.get(f"/api/compliance/decisions/{tid}").json()
    assert d["integrity"]["body"] is True and d["guard"]["notice"] is True and d["sources"][0]["filename"] == "a.txt"
    rv = client.post("/api/compliance/reviews", json={"trace_id": tid, "reason": "wrong", "note": "틀림"}).json()
    assert rv["status"] == "open" and client.get("/api/compliance/reviews?status=open").json()["rows"][0]["id"] == rv["id"]
    done = client.post(f"/api/compliance/reviews/{rv['id']}/resolve", json={"outcome": "corrected", "note": "고침"}).json()
    assert done["status"] == "resolved" and done["outcome"] == "corrected"
    assert client.get(f"/api/compliance/decisions/{tid}").json()["reviews"][0]["outcome"] == "corrected"
    assert client.post("/api/compliance/reviews", json={"trace_id": 999999}).status_code == 404

    draft = client.get(f"/api/compliance/impact/draft?collection_id={cid}").json()
    assert {"retrieval", "redteam"} <= set(draft["missing"])  # 테스트 DB 엔 측정 기록이 없다 — 없다고 짚는다
    imp = client.post("/api/compliance/impact", json={"profile": "legal_answer", "collection_id": cid, "decision": "hold"}).json()
    assert client.post(f"/api/compliance/records/{imp['id']}/confirm").json()["status"] == "approved"

    a = client.post("/api/compliance/audit/run").json()
    rows = {r["control"]: r for r in a["rows"]}
    assert len(rows) == len(catalog.controls()) and rows["breach_procedure"]["status"] == "gap" and rows["integrity"]["status"] == "pass"
    assert rows["review"]["status"] == "pass" and a["run_id"]
    assert client.get("/api/compliance/audit/runs").json()[0]["id"] == a["run_id"]


def test_service_answer_carries_ai_notice(client, rag_collection, scripted_llm):
    """서비스 답변은 AI 응답 고지를 따로 돌려주고, 고지했는지를 요청 기록에 남긴다(RC6 · RC8 증적)."""
    r = client.post(
        "/api/conversation/turn", json={"collection_id": rag_collection["cid"], "question": "배수 필터 청소", "method": "none"}
    ).json()
    assert r["notice"] == get_settings().ai_notice and r["trace_id"]
    assert client.get(f"/api/compliance/decisions/{r['trace_id']}").json()["guard"]["notice"] is True
