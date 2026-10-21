"""문서 처리 API: 메타데이터 · 필터 검색 · 증분 갱신 · 폴더 수집 · 파싱 점검 · OCR · 표 추출 · 정제 · 청크 품질 · 근거 보존."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import Chunk, Document, SessionLocal
from app.stages.docintel import incremental, sources
from tests.helpers import wait_job
from tests.stages.docintel.pdf import TABLE_PAGE, make_pdf


def _search(client, cid, cs, filters=None, q="배수 필터"):
    cfg = {"mode": "bm25", "chunk_set_id": cs, "top_k": 10} | ({"filters": filters} if filters else {})
    return client.post(f"/api/collections/{cid}/search", json={"query": q, "configs": [cfg]}).json()["results"][0]


def _chunks(cs: int) -> dict[int, list[int]]:
    with SessionLocal() as db:
        out: dict[int, list[int]] = {}
        for cid, did in db.execute(select(Chunk.id, Chunk.document_id).where(Chunk.chunk_set_id == cs).order_by(Chunk.id)):
            out.setdefault(did, []).append(cid)
        return out


# ── D6 메타데이터 · 필터 ───────────────────────────────────────────────
def test_meta_edit_facets_and_filtered_search(client, rag_collection):
    cid, docs = rag_collection["cid"], rag_collection["docs"]
    as_doc = docs["AS안내.md"]
    r = client.patch(
        f"/api/docintel/documents/{as_doc}/meta",
        json={"values": {"doc_type": "매뉴얼", "product_model": "WM-100, WM-200", "date": "2025-01-02"}},
    )
    assert r.status_code == 200 and r.json()["meta"]["product_model"] == ["WM-100", "WM-200"]
    client.patch(f"/api/docintel/documents/{docs['법령.txt']}/meta", json={"values": {"doc_type": "법령", "superseded": True}})
    assert client.patch(f"/api/docintel/documents/{as_doc}/meta", json={"values": {"sha256": "x"}}).status_code == 400

    m = client.get(f"/api/docintel/collections/{cid}/meta").json()
    assert m["facets"]["doc_type"] == ["매뉴얼", "법령"] and m["facets"]["n_superseded"] == 1
    assert m["facets"]["date_min"] == "2025-01-02"
    row = next(d for d in m["documents"] if d["document_id"] == as_doc)
    assert row["doc_type"] == "매뉴얼" and set(m["fields"]) >= {"doc_type", "acl", "superseded"}

    cs = rag_collection["cs"]
    assert _search(client, cid, cs)["results"]  # 필터 없음
    hit = _search(client, cid, cs, {"doc_type": ["매뉴얼"]})
    assert hit["results"] and {x["document_id"] for x in hit["results"]} == {as_doc}
    assert hit["restricted"]["filters"]["allowed_docs"] == 1
    # 허용 문서가 0개면 빈 결과 — doc_ids=[] 를 '제한 없음'으로 오해하면 모든 문서가 나온다
    none = _search(client, cid, cs, {"doc_type": ["없는 종류"]})
    assert none["results"] == [] and none["restricted"]["filters"]["allowed_docs"] == 0
    latest = _search(client, cid, cs, {"latest_only": True}, q="공문서 한글")
    assert docs["법령.txt"] not in {x["document_id"] for x in latest["results"]}


# ── D6 증분 갱신 ───────────────────────────────────────────────────────
def test_incremental_refresh_rechunks_only_changed_docs(client, rag_collection):
    cid, cs, docs = rag_collection["cid"], rag_collection["cs"], rag_collection["docs"]
    st = client.get(f"/api/docintel/collections/{cid}/status").json()["chunk_sets"]
    assert [c["up_to_date"] for c in st if c["id"] == cs] == [True]
    before = _chunks(cs)
    target = docs["AS안내.md"]
    with SessionLocal() as db:
        d = db.get(Document, target)
        d.pages = ["# 제품 AS 안내\n세탁기 배수가 안 될 때는 배수 필터를 청소하세요.\n\n건조기 먼지 필터는 매번 비우세요."]
        incremental.touch(d)
        db.commit()
    st = next(c for c in client.get(f"/api/docintel/collections/{cid}/status").json()["chunk_sets"] if c["id"] == cs)
    assert st["changed"] == [target] and not st["added"] and not st["up_to_date"]

    job = client.post(f"/api/docintel/chunk-sets/{cs}/refresh").json()
    res = wait_job(client, job)
    assert res["status"] == "done", res
    r = res["result"]
    assert r["plan"]["changed"] == [target] and r["removed_chunks"] == len(before[target])
    assert r["indexes"] == [rag_collection["idx"]] and r["seconds"] >= 0
    after = _chunks(cs)
    # 바뀌지 않은 문서의 청크는 그대로(같은 id) — 바뀐 문서만 새 청크
    assert {k: v for k, v in after.items() if k != target} == {k: v for k, v in before.items() if k != target}
    assert len(after[target]) == r["added_chunks"]  # (SQLite 는 지운 id 를 다시 쓸 수 있어 id 로는 새 청크를 가리지 않는다)
    st = next(c for c in client.get(f"/api/docintel/collections/{cid}/status").json()["chunk_sets"] if c["id"] == cs)
    assert st["up_to_date"] and st["refreshed_at"]
    # 새 글이 검색 · 인덱스 양쪽에 들어갔다
    assert any("건조기" in x["text"] for x in _search(client, cid, cs, q="건조기 먼지")["results"])
    idx = rag_collection["idx"]
    dense = client.post(
        f"/api/collections/{cid}/search", json={"query": "건조기 먼지 필터", "configs": [{"mode": "dense", "index_id": idx, "top_k": 3}]}
    ).json()
    assert any("건조기" in x["text"] for x in dense["results"][0]["results"])


# ── D1 폴더 수집 ───────────────────────────────────────────────────────
@pytest.fixture
def inbox(tmp_path, monkeypatch):
    root = tmp_path / "inbox"
    (root / "규정").mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "ingest_roots", [root])
    return root


def test_check_path_rejects_outside_roots(inbox, tmp_path):
    assert sources.check_path(str(inbox / "규정")) == (inbox / "규정").resolve()
    with pytest.raises(sources.SourceError, match="허용된 폴더"):
        sources.check_path(str(tmp_path))
    with pytest.raises(sources.SourceError, match="허용된 폴더"):
        sources.check_path(str(inbox / ".." / "다른곳"))  # .. 로 빠져나가기
    with pytest.raises(sources.SourceError, match="폴더가 없습니다"):
        sources.check_path(str(inbox / "없음"))


def test_folder_sync_new_changed_deleted(client, inbox, tmp_path):
    cid = client.post("/api/collections", json={"name": "폴더 수집 테스트"}).json()["id"]
    try:
        folder = inbox / "규정"
        (folder / "출장.txt").write_text("출장비는 실비로 정산합니다.", encoding="utf-8")
        (folder / "휴가.md").write_text("# 휴가\n연차는 입사 1년 뒤 15일입니다.", encoding="utf-8")
        (folder / "무시.exe").write_bytes(b"MZ")  # 지원하지 않는 형식은 보지 않는다
        assert client.post("/api/docintel/sources", json={"collection_id": cid, "path": str(tmp_path)}).status_code == 400
        src = client.post("/api/docintel/sources", json={"collection_id": cid, "path": str(folder), "interval_min": 0}).json()
        assert client.get(f"/api/docintel/sources?collection_id={cid}").json()["sources"][0]["id"] == src["id"]

        def sync():
            res = wait_job(client, client.post(f"/api/docintel/sources/{src['id']}/sync", json={"refresh": True}).json())
            assert res["status"] == "done", res
            return res["result"]["sync"]

        s1 = sync()
        assert (s1["new"], s1["changed"], s1["deleted"], s1["n_files"]) == (2, 0, 0, 2)
        assert sync()["unchanged"] == 2  # 같은 해시는 건너뜀

        (folder / "출장.txt").write_text("출장비는 실비로 정산하고 영수증을 붙입니다.", encoding="utf-8")
        (folder / "휴가.md").unlink()
        (folder / "보안.txt").write_text("보안 교육은 해마다 받습니다.", encoding="utf-8")
        s3 = sync()
        assert (s3["new"], s3["changed"], s3["deleted"], s3["unchanged"]) == (1, 1, 1, 0)
        names = {d["filename"]: d for d in client.get(f"/api/collections/{cid}").json()["documents"]}
        assert set(names) == {"출장.txt", "보안.txt"} and names["출장.txt"]["meta"]["source_path"] == "출장.txt"

        # 이름만 바꾼 파일(내용 같음): 옛 문서를 먼저 지우므로 새 이름으로 다시 들어간다(내용이 사라지지 않음)
        (folder / "보안.txt").rename(folder / "보안 교육.txt")
        s4 = sync()
        assert (s4["new"], s4["deleted"], s4["skipped"]) == (1, 1, [])
        names = {d["filename"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
        assert names == {"출장.txt", "보안 교육.txt"}

        assert client.delete(f"/api/docintel/sources/{src['id']}").json() == {"deleted": src["id"]}
        assert len(client.get(f"/api/collections/{cid}").json()["documents"]) == 2  # 소스를 지워도 문서는 남는다
    finally:
        client.delete(f"/api/collections/{cid}")


# ── D2 · D3 파싱 점검 · OCR · 표 ───────────────────────────────────────
@pytest.fixture
def pdf_collection(client):
    cid = client.post("/api/collections", json={"name": "PDF 테스트"}).json()["id"]
    pdf = make_pdf([TABLE_PAGE, ""])  # 2쪽은 글자 없음(스캔된 쪽처럼)
    up = client.post(f"/api/collections/{cid}/documents", files=[("files", ("매출 보고.pdf", pdf, "application/pdf"))]).json()
    yield cid, up["added"][0]["id"]
    client.delete(f"/api/collections/{cid}")


def test_parsing_report_layout_and_tables(client, pdf_collection):
    cid, did = pdf_collection
    rep = client.get(f"/api/docintel/collections/{cid}/parsing").json()
    assert rep["n_issues"] == 1 and rep["n_without_original"] == 0
    d = client.get(f"/api/docintel/documents/{did}/parsing").json()
    assert d["empty_pages"] == [2] and d["ocr_possible"] and len(d["pages"]) == 2
    assert client.get(f"/api/docintel/documents/{did}/tables").json() == {"layout": None, "figures": [], "tables": []}

    res = wait_job(client, client.post(f"/api/docintel/documents/{did}/layout", json={"figures": True}).json())
    assert res["status"] == "done", res
    assert res["result"]["tables"] == 1 and res["result"]["figures"] == 0
    t = client.get(f"/api/docintel/documents/{did}/tables").json()
    assert t["layout"]["table_list"][0]["rows"] == 3
    assert t["tables"][0].splitlines()[:3] == ["[표 1-1]", "| Quarter | Sales |", "|---|---|"]
    assert client.get(f"/api/docintel/documents/{did}/figures/0").status_code == 404
    assert client.get(f"/api/docintel/documents/{did}/parsing").json()["layout"]["tables"] == 1


def test_ocr_fills_empty_pages_and_measures_text_pages(client, pdf_collection, scripted_llm):
    cid, did = pdf_collection
    before = client.get(f"/api/docintel/documents/{did}/parsing").json()["pages"][0]
    # 빈 쪽(2)은 채우고, 글이 있는 쪽(1)은 덮어쓰지 않고 정확도만 잰다
    res = wait_job(client, client.post(f"/api/docintel/documents/{did}/ocr", json={"pages": [1, 2]}).json())
    assert res["status"] == "done", res
    pages = {p["page"]: p for p in res["result"]["pages"]}
    assert pages[1]["measured_only"] and 0 <= pages[1]["accuracy"] < 1 and res["result"]["accuracy"] == pages[1]["accuracy"]
    assert "measured_only" not in pages[2] and pages[2]["chars"] > 0
    d = client.get(f"/api/docintel/documents/{did}/parsing").json()
    assert d["pages"][0] == before and "배수 필터" in d["pages"][1]
    assert d["ocr"]["accuracy"] == pages[1]["accuracy"]
    # 다른 쪽만 다시 재도 앞선 기록(2쪽을 채운 것)은 남는다
    res2 = wait_job(client, client.post(f"/api/docintel/documents/{did}/ocr", json={"pages": [1]}).json())
    assert {p["page"] for p in res2["result"]["pages"]} == {1, 2}
    assert 2 not in client.get(f"/api/docintel/documents/{did}/parsing").json()["empty_pages"]


def test_ocr_rejects_non_pdf(client, rag_collection, scripted_llm):
    did = rag_collection["docs"]["AS안내.md"]
    res = wait_job(client, client.post(f"/api/docintel/documents/{did}/ocr", json={}).json())
    assert res["status"] == "error" and "PDF" in res["error"]


# ── D4 정제 ─────────────────────────────────────────────────────────────
def test_clean_analyze_and_apply(client):
    cid = client.post("/api/collections", json={"name": "정제 테스트"}).json()["id"]
    try:
        page = "사내 규정집 2025\n{}\n- {} -"
        bodies = ["급여는 매월 25일에 지급한다.", "연차는 입사 1년 뒤 15일이다.", "출장 신청은 사흘 전에 한다."]
        text = "\f".join(page.format(b, i) for i, b in enumerate(bodies, 1))
        files = [("files", ("규정집.txt", text.encode(), "text/plain")),
                 ("files", ("복무규정 v1.txt", "복무 시간은 9시부터 18시까지이다.".encode(), "text/plain")),
                 ("files", ("복무규정 v2.txt", "복무 시간은 9시부터 18시까지이며 점심은 1시간이다.".encode(), "text/plain"))]  # fmt: skip
        client.post(f"/api/collections/{cid}/documents", files=files)
        r = client.get(f"/api/docintel/collections/{cid}/clean?threshold=0.9").json()
        assert r["n_docs"] == 3 and [g["group"] for g in r["version_groups"]] == ["복무규정"]
        out = client.post(f"/api/docintel/collections/{cid}/clean/apply", json={"boilerplate": True, "versions": True}).json()
        assert out["versions"] == {"groups": 1, "superseded": 1}
        m = {d["filename"]: d for d in client.get(f"/api/docintel/collections/{cid}/meta").json()["documents"]}
        assert m["복무규정 v1.txt"]["superseded"] and not m["복무규정 v2.txt"]["superseded"]
        assert m["복무규정 v1.txt"]["version_group"] == "복무규정"
    finally:
        client.delete(f"/api/collections/{cid}")


# ── D5 · D7 청크 품질 · 근거 보존 ─────────────────────────────────────
def test_chunk_quality_and_preservation(client, rag_collection):
    cs = rag_collection["cs"]
    q = client.get(f"/api/docintel/chunk-sets/{cs}/quality").json()
    assert q["n_chunks"] > 0 and q["n_text"] == q["n_chunks"] and q["length"]["count"] == q["n_text"]
    assert q["empty_docs"] == [] and q["broken_chunks"] == 0 and isinstance(q["issues"], list)
    p = client.get(f"/api/docintel/chunk-sets/{cs}/preservation?eval_set_id={rag_collection['set']}").json()
    assert p["n_evidences"] == 2 and p["preserved"] == 2 and p["rate"] == 1.0 and p["broken"] == []
    assert client.get(f"/api/docintel/chunk-sets/{cs}/preservation?eval_set_id=999999").status_code == 404
    assert client.get("/api/docintel/chunk-sets/999999/quality").status_code == 404
