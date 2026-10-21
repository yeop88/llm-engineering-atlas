"""지식 그래프(K1~K8): 정형 추출 · 온톨로지 검증 · 쟁점 합치기 · 내장 그래프 저장소 · 이웃 확장 · 커뮤니티 · Text2Cypher · API."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.core import graphstore, llm
from app.core.db import Document, SessionLocal
from app.stages.kg import evaluate, extract, fusion, graphrag, ontology, text2cypher
from tests.helpers import wait_job

STATUTE = "근로기준법 시행령\n\n제1조(목적) 이 영은 「근로기준법」에서 위임한 사항을 정한다.\n제2조(평균임금) 법 제2조제1항제6호에 따른 평균임금은 「민법」 제5조 와 다르다.\n"
PREC = ("임금 (대법원 20200101 선고 2019다12345)\n【판시사항】 취업규칙의 불이익 변경에 근로자 과반수 동의가 필요한지\n"
        "【참조조문】 [1] 근로기준법 제94조 제1항, 제95조 / [2] 구 근로기준법(2007. 4. 11. 법률 제8372호로 개정되기 전의 것) 제30조, "
        "노동조합 및 노동관계조정법 제2조 및 제3조\n【참조판례】 대법원 2018. 1. 1. 선고 2017다1111 판결\n【전문】 …")  # fmt: skip


# ── K3 추출 · K2 검증 ──────────────────────────────────────────────────────
def test_cited_articles_handles_spaces_parens_and_carry_over():
    got = extract.cited_articles("[1] 근로기준법 제94조 제1항, 제95조 / [2] 구 근로기준법(2007. 4. 11. 법률 제8372호로 …) 제30조, "
                                 "여객자동차 운수사업법 제3조, 남녀고용평등과 일·가정 양립 지원에 관한 법률 제19조 및 제20조")  # fmt: skip
    assert got == [("근로기준법", "제94조"), ("근로기준법", "제95조"), ("근로기준법", "제30조"), ("여객자동차 운수사업법", "제3조"),
                   ("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "제19조"), ("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "제20조")]  # fmt: skip
    assert extract.law_name("근로기준법시행령") == "근로기준법 시행령"


def test_statute_and_precedent_extraction():
    n, e = extract.statute(Document(id=1, filename="근로기준법 시행령.txt", pages=[STATUTE]))
    keys = {x["key"] for x in n}
    assert {"근로기준법 시행령", "근로기준법 시행령 제1조", "근로기준법 시행령 제2조"} <= keys
    refs = {(x["src"][1], x["dst"][1]) for x in e if x["type"] == "REFERS_TO"}
    assert ("근로기준법 시행령 제2조", "근로기준법 제2조") in refs and (
        "근로기준법 시행령 제2조",
        "민법 제5조",
    ) in refs  # 모법 '법 제N조' · 「법령」 제N조
    pn, pe, h = extract.precedent(Document(id=2, filename="판례 2019다12345 임금.txt", pages=[PREC], meta={}))
    assert pn[0]["key"] == "2019다12345" and pn[0]["props"]["date"] == "2020-01-01" and "취업규칙" in h["holding"]
    cites = {x["dst"][1] for x in pe if x["type"] == "CITES"}
    assert {"근로기준법 제94조", "근로기준법 제30조", "노동조합 및 노동관계조정법 제3조"} <= cites
    assert ("Precedent", "2017다1111") in [x["dst"] for x in pe if x["type"] == "CITES_CASE"]
    ext = extract.external_nodes(n + pn, e + pe)
    assert any(x["key"] == "2017다1111" and x["props"]["external"] for x in ext)
    v = ontology.validate(n + pn + ext, e + pe)
    assert not v["rejected"] and len(v["edges"]) == len(e + pe)


def test_ontology_rejects_bad_relations():
    nodes = [{"label": "Precedent", "key": "p", "props": {"case_no": "p"}}, {"label": "Article", "key": "a", "props": {"law": "x", "no": "제1조"}},
             {"label": "Unknown", "key": "u"}, {"label": "Article", "key": "b", "props": {}}]  # fmt: skip
    edges = [{"src": ("Article", "a"), "dst": ("Precedent", "p"), "type": "CITES"}, {"src": ("Precedent", "p"), "dst": ("Article", "a"), "type": "LIKES"},
             {"src": ("Precedent", "p"), "dst": ("Article", "a"), "type": "CITES"}]  # fmt: skip
    v = ontology.validate(nodes, edges)
    whys = [r["why"] for r in v["rejected"]]
    assert len(v["nodes"]) == 2 and len(v["edges"]) == 1 and any("클래스" in w for w in whys) and any("필수" in w for w in whys)
    assert "(:Precedent)-[:CITES]->(:Article)" in ontology.schema_text()


# ── K4 쟁점 합치기 ─────────────────────────────────────────────────────────
def test_merge_issues_by_text_and_embedding():
    per = {"a": ["취업규칙 불이익 변경"], "b": ["취업규칙의 불이익 변경", "통상임금"], "c": ["통상임금 해당 여부"], "d": ["가산임금"]}

    def embed(names):  # '통상임금' 둘만 가깝게
        return np.array([[1.0, 0.0] if "통상" in n else [0.0, 1.0] if "가산" in n else [0.6, 0.8] for n in names])

    m = fusion.merge_issues(per, embed)
    canon = {e["src"][1]: e["dst"][1] for e in m["edges"] if e["src"][1] == "c"}
    assert m["n_raw"] == 5 and m["n_issues"] == 3 and canon["c"] == "통상임금"  # 조사 차이 · 임베딩 유사 둘 다 합침
    assert any(x["canonical"] == "취업규칙 불이익 변경" for x in m["merges"])
    assert any(n["key"] == "가산임금" for n in m["nodes"])  # 낱말 안의 '가'는 지우지 않는다


# ── K5 저장소 · K7 확장 · K8 커뮤니티 ──────────────────────────────────────
def _toy(db, graph="t"):
    nodes = [{"label": "Article", "key": f"법 제{i}조", "props": {"law": "법", "no": f"제{i}조"}} for i in range(1, 4)]
    nodes += [{"label": "Precedent", "key": f"p{i}", "props": {"case_no": f"p{i}"}, "document_id": None} for i in range(1, 6)]
    edges = [{"src": ("Precedent", "p1"), "dst": ("Article", "법 제1조"), "type": "CITES"}, {"src": ("Precedent", "p2"), "dst": ("Article", "법 제1조"), "type": "CITES"},
             {"src": ("Precedent", "p3"), "dst": ("Article", "법 제1조"), "type": "CITES"}, {"src": ("Precedent", "p4"), "dst": ("Article", "법 제2조"), "type": "CITES"},
             {"src": ("Precedent", "p5"), "dst": ("Article", "법 제2조"), "type": "CITES"}, {"src": ("Precedent", "p4"), "dst": ("Precedent", "p5"), "type": "CITES_CASE"}]  # fmt: skip
    graphstore.clear(db, graph)
    return graphstore.upsert(db, graph, nodes, edges)


def test_graphstore_upsert_is_idempotent_and_neighbors(client):
    with SessionLocal() as db:
        assert _toy(db) == {"nodes": 8, "edges": 6}
        again = graphstore.upsert(db, "t", [{"label": "Article", "key": "법 제1조", "name": "법 제1조(목적)", "props": {"law": "법", "no": "제1조"}}],
                                  [{"src": ("Precedent", "p1"), "dst": ("Article", "법 제1조"), "type": "CITES"}])  # fmt: skip
        assert again["edges"] == 0 and graphstore.stats(db, "t")["nodes"] == 8  # 같은 개체 · 관계는 늘지 않는다
        ids = graphstore.node_ids(db, "t")
        ns, es = graphstore.neighbors(db, "t", [ids[("Precedent", "p1")]], hops=2)
        assert {n.key for n in ns} == {"p1", "법 제1조", "p2", "p3"} and len(es) == 3  # 공동 인용 판례까지
        comms = graphrag.detect(db, "t", min_size=3)
        assert len(comms) == 2 and {n.key for n in comms[0]} in ({"p1", "p2", "p3", "법 제1조"}, {"p4", "p5", "법 제2조"})
        graphstore.clear(db, "t")


def test_expand_finds_co_citing_document(client, rag_collection):
    docs = rag_collection["docs"]
    d1, d2 = docs["AS안내.md"], docs["법령.txt"]
    with SessionLocal() as db:
        graphstore.clear(db, "t2")
        graphstore.upsert(db, "t2", [{"label": "Precedent", "key": "A", "props": {"case_no": "A"}, "document_id": d1},
                                     {"label": "Precedent", "key": "B", "props": {"case_no": "B"}, "document_id": d2},
                                     {"label": "Article", "key": "법 제9조", "props": {"law": "법", "no": "제9조"}}],
                          [{"src": ("Precedent", "A"), "dst": ("Article", "법 제9조"), "type": "CITES"},
                           {"src": ("Precedent", "B"), "dst": ("Article", "법 제9조"), "type": "CITES"}])  # fmt: skip
        ex = graphrag.expand(db, "t2", [{"document_id": d1, "filename": "AS안내.md", "text": ""}])
        assert [d["document_id"] for d in ex["docs"]] == [d2] and ex["docs"][0]["via"] == ["법 제9조"]
        assert any("인용" in r for r in ex["relations"])
        # 평가: 벡터가 A 만 찾으면 '모두 맞음'은 그래프 확장으로만
        out = evaluate.hybrid(
            [{"query": "q", "doc_ids": [d1, d2]}], lambda q: [{"document_id": d1}], lambda r: graphrag.expand(db, "t2", r), k=3, add=1
        )
        assert out["multi"]["vector"]["all"] == 0 and out["multi"]["graph"]["all"] == 1 and out["multi"]["added_gold"] == 1
        graphstore.clear(db, "t2")


# ── K6 Text2Cypher ─────────────────────────────────────────────────────────
def test_text2cypher_retries_and_score(monkeypatch):
    replies = iter(["```cypher\nMATCH (x:Nope) RETURN x\n```", "MATCH (p:Precedent) RETURN p.case_no;"])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": next(replies)})

    def run(q):
        if "Nope" in q:
            raise ValueError("Unknown label Nope")
        return {"columns": ["p.case_no"], "rows": [["A"], ["B"]]}

    cfg = llm.LLMConfig(provider="openai", model="fake")
    r = text2cypher.ask(cfg, "판례 사건번호는?", run)
    assert r["cypher"] == "MATCH (p:Precedent) RETURN p.case_no" and len(r["attempts"]) == 2 and "Nope" in r["attempts"][0]["error"]
    assert text2cypher.score({"rows": [["A"], ["B"]]}, r["result"]) == {"exact": True, "jaccard": 1.0, "lenient": True}
    named = {"rows": [["임금 (A)"], ["해고 (B)"]]}  # 같은 판례를 이름으로 — 정확 일치는 아니지만 같은 답
    assert text2cypher.score({"rows": [["A"], ["B"]]}, named) == {"exact": False, "jaccard": 0.0, "lenient": True}
    assert text2cypher.score({"rows": [["A"], ["C"]]}, r["result"])["jaccard"] == 0.333
    assert len(text2cypher.cq_preset()["questions"]) == 15


def test_engines_not_configured_in_tests():  # 쓰기 차단(EXPLAIN · GRAPH.RO_QUERY)은 실제 엔진으로 확인 — docs 의 K6 실측
    assert not graphstore.neo4j_status()["ok"] and not graphstore.falkordb_status()["ok"]  # 테스트는 엔진 없이
    assert graphstore.engine_name() == "neo4j" and graphstore.engine_name("falkordb") == "falkordb"
    with pytest.raises(graphstore.GraphUnavailable):
        graphstore.engine_name("arangodb")


def test_falkor_dialect_rewrites_simple_exists_only():
    """EXISTS { (패턴) } → 패턴 조건(하위 쿼리 안에서만 쓴 변수는 지움). 절이 든 하위 쿼리 · 일반 쿼리는 그대로."""
    q = "MATCH (a:Article) WHERE NOT EXISTS { (p:Precedent)-[:CITES]->(a) } RETURN count(a)"
    assert graphstore.falkor_dialect(q) == "MATCH (a:Article) WHERE NOT (:Precedent)-[:CITES]->(a) RETURN count(a)"
    assert graphstore.falkor_dialect("MATCH (p) WHERE NOT EXISTS {(p)-[r:X]->(q)} RETURN p") == "MATCH (p) WHERE NOT (p)-[:X]->() RETURN p"
    for same in ("MATCH (a) WHERE EXISTS { MATCH (a)--(b) WHERE b.x = 1 } RETURN a", "MATCH (a:Article {key: 'x'}) RETURN a"):
        assert graphstore.falkor_dialect(same) == same


def test_falkor_values_match_neo4j_shape():
    """FalkorDB 노드 · 경로도 Neo4j 쪽과 같은 모양(이름)으로 — 역량 질문 채점이 엔진과 상관없게."""
    node = SimpleNamespace(labels=["Article"], properties={"key": "근로기준법 제23조", "name": "근로기준법 제23조(해고 등의 제한)"})
    bare = SimpleNamespace(labels=["Precedent"], properties={"key": "2020다1234"})
    path = SimpleNamespace(nodes=lambda: [node, bare])
    assert graphstore._plain_falkor(node) == "근로기준법 제23조(해고 등의 제한)"
    assert graphstore._plain_falkor([bare, 3]) == ["2020다1234", 3]
    assert graphstore._plain_falkor(path) == ["근로기준법 제23조(해고 등의 제한)", "2020다1234"]


# ── API ────────────────────────────────────────────────────────────────────
def test_kg_api_build_expand_and_errors(client, rag_collection):
    cid = rag_collection["cid"]
    assert client.get("/api/kg/ontology").json()["graph"] == "legal"
    job = client.post("/api/kg/build", json={"collection_id": cid, "graph": "test-g"}).json()
    done = wait_job(client, job)
    assert done["status"] == "done", done
    assert done["result"]["stats"]["nodes"] >= 1 and done["result"]["n_rejected"] == 0  # '법령.txt' → 법령 노드
    st = client.get("/api/kg/graphs/test-g/stats").json()
    assert st["collection_id"] == cid
    r = client.post("/api/kg/graphs/test-g/expand", json={"question": "공문서 작성"}).json()
    assert r["results"] and "docs" in r["expand"]
    assert client.get("/api/kg/graphs/nope/stats").status_code == 404
    assert client.post("/api/kg/cypher", json={"query": "MATCH (n) RETURN n"}).status_code == 400  # Neo4j 설정 없음
    eng = client.get("/api/kg/engines").json()
    assert [e["engine"] for e in eng["engines"]] == ["neo4j", "falkordb"] and not any(e["ok"] for e in eng["engines"])
    assert client.post("/api/kg/cypher", json={"query": "MATCH (n) RETURN n", "engine": "falkordb"}).status_code == 400
    assert client.post("/api/kg/graphs/test-g/sync?engine=falkordb").status_code == 400
    assert client.post("/api/kg/cq/eval", json={"engine": "falkordb"}).status_code == 400  # 연결 안 되면 작업 전에
    assert client.post("/api/kg/build", json={"collection_id": cid, "graph": "BAD NAME"}).status_code == 422


def test_merge_keeps_opposite_roles_apart():
    """'임차인 지위 승계'와 '임대인 지위 승계'는 임베딩이 가까워도 다른 쟁점(첫 구축에서 합쳐졌던 것)."""
    same = lambda names: np.ones((len(names), 2)) / np.sqrt(2)  # noqa: E731 — 모두 똑같이 가깝게
    m = fusion.merge_issues({"a": ["임차인 지위 승계"], "b": ["임대인 지위 승계"], "c": ["임대인 지위의 승계"]}, same)
    keys = {n["key"] for n in m["nodes"]}
    assert len(keys) == 2 and "임차인 지위 승계" in keys
    assert fusion.conflict("근로자 과반수 동의", "사용자 동의") and not fusion.conflict("근로자 동의", "근로자 과반수 동의")
