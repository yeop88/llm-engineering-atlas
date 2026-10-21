"""ED3 기기용 팩(압축 · 판 · 벡터 재사용 · 검색 · 평가) · ED5 증분 동기화. 팩 폴더는 임시 폴더로 바꿔 실제 data/ 에 쓰지 않는다."""

import zlib
from datetime import timedelta

import numpy as np
import pytest

from app.core.db import AnswerCache, Document, SessionLocal, VectorIndex, utcnow
from app.stages.edge import pack as pk
from app.stages.edge import sync as sy


@pytest.fixture(autouse=True)
def pack_dir(tmp_path, monkeypatch):
    # PACK_DIR 는 저장소 data/ 아래(BASE_DIR) — 테스트가 실제 팩 폴더를 만들거나 지우지 않게
    monkeypatch.setattr(pk, "PACK_DIR", tmp_path / "packs")
    return tmp_path / "packs"


def encoder(dim: int, calls: list | None = None):
    """글자 바이그램 해시 — 같은 글은 같은 벡터, 겹치는 표현이 많을수록 가깝다(가짜 임베딩 모델과 같은 성질)."""

    def enc(texts):
        if calls is not None:
            calls.append(list(texts))
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for r, t in enumerate(texts):
            s = "".join(t.split())
            for i in range(max(1, len(s) - 1)):
                out[r, zlib.crc32(s[i : i + 2].encode()) % dim] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)

    return enc


# ── 압축 · 복원 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("precision", "tol", "bpv"), [("float32", 0, 4 * 33), ("float16", 1e-3, 2 * 33), ("int8", 0.01, 33), ("int4", 0.1, 17)]
)
def test_compress_restore_round_trip(precision, tol, bpv):
    x = np.random.default_rng(0).normal(size=(20, 33)).astype(np.float32)  # 홀수 차원 — int4 는 한 바이트에 둘이라 채움이 필요
    a = pk.compress(x, precision)
    assert np.abs(pk.restore(a, precision, 33) - x).max() <= tol * (x.max() - x.min()) + 1e-6
    # 기기에 실제로 담기는 크기(눈금 lo · hi 는 팩 하나에 한 번이라 청크당 크기에서 뺀다)
    assert pk.bytes_per_chunk(a) == bpv


def test_binary_rescore_and_fixed_scale():
    x = np.random.default_rng(1).normal(size=(10, 16)).astype(np.float32)
    a = pk.compress(x, "binary_rescore")
    assert a["bits"].shape == (10, 2) and np.array_equal(np.unpackbits(a["bits"], axis=1).astype(bool), x > 0)
    # 앞 판의 눈금을 이어 쓰면 범위를 벗어난 값은 잘린다(같은 눈금이어야 가져온 벡터와 새 벡터를 섞을 수 있다)
    lo, hi = np.zeros(16, np.float32), np.ones(16, np.float32)
    r = pk.restore(pk.compress(x, "int8", lo, hi), "int8", 16)
    assert r.min() >= 0 and r.max() <= 1
    with pytest.raises(ValueError):
        pk.compress(x, "int2")
    assert pk.concat([{}, pk.take(a, np.array([], dtype=int))]) == {}


# ── 팩 만들기 · 판 · 재사용 ─────────────────────────────────────────────────
def test_build_versions_reuse_and_delta(client, rag_collection):
    docs = rag_collection["docs"]
    with SessionLocal() as db:
        idx = db.get(VectorIndex, rag_collection["idx"])
        dim = idx.truncate_dim or idx.dim
        calls: list = []
        enc = encoder(dim, calls)
        m1 = pk.build(db, "as", idx, "int8", {}, enc)
        assert m1["version"] == 1 and m1["n_docs"] == 3 and m1["encoded"] == m1["n_chunks"] and m1["reused"] == 0 and m1["prev"] is None
        assert m1["bytes_per_chunk"] == dim and "chunk_ids" not in m1
        # 바뀐 것이 없으면 다시 인코딩하지 않는다 — 증분 동기화가 바뀐 문서만 보내려면 서버도 같은 값을 써야 한다
        m2 = pk.build(db, "as", idx, "int8", {}, enc)
        assert m2["version"] == 2 and m2["reused"] == m2["n_chunks"] and m2["encoded"] == 0 and m2["hash"] == m1["hash"]
        assert len(calls) == 1
        assert pk.versions("as") == [1, 2] and pk.listing()[0]["latest"] == 2
        # 문서 하나가 바뀜(sha256) → 그 문서의 청크만 인코딩
        d = db.get(Document, docs["AS안내.md"])
        d.sha256 = "0" * 64
        db.commit()
        m3 = pk.build(db, "as", idx, "int8", {}, enc)
        n_as = sum(1 for c in pk.load("as", 3)["chunks"] if c["doc_id"] == d.id)
        assert m3["encoded"] == n_as and m3["reused"] == m3["n_chunks"] - n_as and m3["hash"] != m2["hash"]
        # 같은 판끼리는 재사용 벡터와 새 벡터가 같은 눈금 — 바뀐 문서 쪽 복원값이 v2 와 같다(글이 같으므로)
        v2, v3 = pk.load("as", 2), pk.load("as", 3)
        assert np.array_equal(v2["arrays"]["q8"], v3["arrays"]["q8"]) and np.array_equal(v2["arrays"]["lo"], v3["arrays"]["lo"])

    # 증분: 바뀐 문서만 보내고, 그 문서의 옛 청크는 모두 지운다(한 문서 안에 옛 · 새 청크가 섞이지 않게)
    dl = sy.delta("as", 2, 3, with_content=True)
    assert dl["mode"] == "delta" and dl["changed_docs"] == [str(d.id)] and dl["added_docs"] == dl["removed_docs"] == []
    assert dl["send_chunks"] == n_as and len(dl["remove_chunk_ids"]) == n_as and len(dl["chunks"]) == n_as
    assert dl["verified"] and dl["bytes"] < dl["full_bytes"] and len(dl["arrays"]["q8"]) == n_as
    assert sy.delta("as", 3)["send_chunks"] == 0  # 이미 최신
    full = sy.delta("as", None)
    assert full["mode"] == "full" and full["send_chunks"] == m3["n_chunks"] and full["verified"]


def test_scope_added_removed_and_precision_change(client, rag_collection):
    docs = rag_collection["docs"]
    with SessionLocal() as db:
        idx = db.get(VectorIndex, rag_collection["idx"])
        enc = encoder(idx.truncate_dim or idx.dim)
        # 담당 범위: 문서 번호로 고른다 — 무엇을 담을지가 품질만큼 중요하다
        a = pk.build(db, "field", idx, "int4", {"doc_ids": [docs["AS안내.md"]]}, enc)
        assert a["n_docs"] == 1 and a["scope"] == {"doc_ids": [docs["AS안내.md"]]}
        b = pk.build(db, "field", idx, "int4", {"doc_ids": [docs["AS안내.md"], docs["법령.txt"]]}, enc)
        assert b["reused"] == a["n_chunks"]
        pk.build(db, "field", idx, "int4", {"doc_ids": [docs["법령.txt"]]}, enc)
        d4 = pk.build(db, "field", idx, "binary_rescore", {"doc_ids": [docs["법령.txt"]]}, enc)
        assert d4["reused"] == 0  # 정밀도가 바뀌면 재사용하지 않는다(눈금 · 모양이 다름)
        with pytest.raises(ValueError, match="범위"):
            pk.build(db, "field", idx, "int8", {"doc_ids": [999999]}, enc)
    add = sy.delta("field", 1, 2)
    assert add["added_docs"] == [str(docs["법령.txt"])] and add["remove_chunk_ids"] == [] and add["verified"]
    rem = sy.delta("field", 2, 3)
    assert rem["removed_docs"] == [str(docs["AS안내.md"])] and rem["send_chunks"] == 0 and len(rem["remove_chunk_ids"]) == a["n_chunks"]
    assert rem["verified"]
    # 정밀도가 바뀐 판으로는 증분을 섞을 수 없다 → 전체
    full = sy.delta("field", 3, 4)
    assert full["mode"] == "full" and "정밀도" in full["reason"]
    with pytest.raises(ValueError):
        pk.manifest("field", 9)
    pk.remove("field")
    assert pk.versions("field") == [] and pk.listing() == []


def test_select_docs_by_meta_and_recency(client, rag_collection):
    docs = rag_collection["docs"]
    with SessionLocal() as db:
        d = db.get(Document, docs["AS안내.md"])
        d.meta = (d.meta or {}) | {"product_model": ["WM-200"], "doc_type": "manual"}
        old = db.get(Document, docs["법령.txt"])
        old.created_at = utcnow() - timedelta(days=30)
        db.commit()
        cid = rag_collection["cid"]
        assert [x.id for x in pk.select_docs(db, cid, {"product_model": ["WM-200", " "]})] == [d.id]
        assert [x.id for x in pk.select_docs(db, cid, {"doc_type": ["manual"]})] == [d.id]
        recent = {x.id for x in pk.select_docs(db, cid, {"since_days": 7})}
        assert old.id not in recent and d.id in recent
        # 글이 바뀐 시각(changed_at)도 최근으로 본다 — 오래전에 올린 문서라도 고쳤으면 다시 담는다
        old.meta = (old.meta or {}) | {"changed_at": utcnow().isoformat()}
        db.commit()
        assert old.id in {x.id for x in pk.select_docs(db, cid, {"since_days": 7})}
        assert len(pk.select_docs(db, cid, {})) == 3


def test_search_cache_and_evaluate(client, rag_collection):
    docs = rag_collection["docs"]
    with SessionLocal() as db:
        idx = db.get(VectorIndex, rag_collection["idx"])
        enc = encoder(idx.truncate_dim or idx.dim)
        q_text = "세탁기 배수가 안 될 때"
        qv = enc([q_text])[0]
        # 근거가 팩 안인 캐시 답만 담는다 — 팩 밖 문서에 기댄 답은 기기에서 근거를 보여 줄 수 없다
        db.add_all([
            AnswerCache(collection_id=rag_collection["cid"], model_hf_id=idx.model_hf_id, question=q_text, vector=qv.tolist(),
                        answer="배수 필터를 청소하세요", sources=[{"document_id": docs["AS안내.md"]}]),
            AnswerCache(collection_id=rag_collection["cid"], model_hf_id=idx.model_hf_id, question="공문서", vector=qv.tolist(),
                        answer="한글로", sources=[{"document_id": docs["법령.txt"]}]),
            AnswerCache(collection_id=rag_collection["cid"], model_hf_id="다른/모델", question=q_text, vector=[0.0], answer="x",
                        sources=[{"document_id": docs["AS안내.md"]}]),
        ])  # fmt: skip
        db.commit()
        for prec in ("binary_rescore", "float16"):
            name = f"s-{prec}".replace("_", "-")
            m = pk.build(db, name, idx, prec, {"doc_ids": [docs["AS안내.md"], docs["보도자료.txt"]]}, enc)
            assert m["n_cache"] == 1
            p = pk.load(name)
            res, ms = pk.search(p, qv, k=2)
            # 압축한 문서 벡터로도 정답 문서가 1위(질의는 float 그대로 — 비대칭)
            assert res[0]["doc_id"] == docs["AS안내.md"] and res[0]["score"] >= res[-1]["score"] and ms >= 0
            assert pk.cache_hit(p, qv)["answer"] == "배수 필터를 청소하세요"
            assert pk.cache_hit(p, enc(["전혀 다른 질문 공문서 한글"])[0]) is None
            ev = pk.evaluate(p, [{"id": 1, "query": q_text, "doc_ids": [docs["AS안내.md"]]},
                                 {"id": 2, "query": "공문서 작성 문자", "doc_ids": [docs["법령.txt"]]}], enc,
                             lambda q: [{"document_id": docs["법령.txt"]}], k=2)  # fmt: skip
            # 범위 밖 질문을 따로 센다 — 압축 손실과 '안 담아서 못 찾음'을 나눠 보려고
            assert ev["n"] == 2 and ev["n_in_scope"] == 1 and ev["in_scope"]["pack_hit"] == 1.0 and ev["pack_hit"] == 0.5
            assert ev["server_hit"] == 0.5 and ev["in_scope"]["server_hit"] == 0.0
        no_srv = pk.evaluate(p, [{"query": q_text, "doc_ids": [docs["AS안내.md"]]}], enc, None)
        assert no_srv["server_hit"] is None and "server_hit" not in no_srv["rows"][0]
        pk.build(db, "nocache", idx, "int8", {}, enc, include_cache=False)
        assert pk.load("nocache")["cache"] == [] and pk.cache_hit(pk.load("nocache"), qv) is None
