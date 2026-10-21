"""그래프 저장소(지식 그래프 K5): 앱 DB 의 노드 · 관계 테이블이 원본이고, Cypher 엔진(Neo4j · FalkorDB)에 그대로 옮겨 Cypher 를 돌린다.

왜 둘인가: 그래프 DB 서버 없이도 그래프를 만들고 이웃 확장(GraphRAG K7) · 커뮤니티 탐지(K8)를 할 수 있어야 실험이 막히지 않는다
(벡터 저장소가 Qdrant 로컬 파일 모드로 서버 없이 도는 것과 같은 이유). Text2Cypher(K6)는 실제 Cypher 엔진이 있어야 의미가 있어
Neo4j 를 쓰고, 그때 원본을 통째로 옮긴다 — 두 곳에 따로 쓰면 어긋나므로 쓰기는 늘 앱 DB 에만 한다.

Neo4j 에서 쓰기 쿼리를 막는 법: 읽기 접근 모드는 단일 서버에서 쓰기를 막지 못하므로, 실행 전에 EXPLAIN 으로 쿼리 종류를 보고
읽기('r')가 아니면 거절한다(키워드 검사는 우회가 쉽다 — CALL 프로시저 · 대소문자 · 주석).
FalkorDB 는 읽기 전용 명령(GRAPH.RO_QUERY)이 서버에서 쓰기를 거절하므로 그것으로 실행한다.

엔진을 둘 두는 이유: 같은 그래프 · 같은 역량 질문으로 Cypher 방언 차이(FalkorDB 는 OpenCypher + 자체 확장, 예: EXISTS { } 하위 쿼리 없음)와
속도 · 무게를 비교하려고. Neo4j 는 JVM 기반이라 무겁고, FalkorDB 는 Redis 모듈이라 가볍다.
"""

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import KgEdge, KgNode


class GraphUnavailable(RuntimeError):
    pass


# ── 앱 DB(원본) ────────────────────────────────────────────────────────────
def upsert(db: Session, graph: str, nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]]) -> dict[str, int]:
    """nodes: {label, key, name, props, document_id}, edges: {src: (label, key), dst: (label, key), type, props}.
    같은 (label, key) 는 이름 · 속성을 덮어쓰고, 같은 관계는 한 번만."""
    n_new = 0
    for n in nodes:
        stmt = sqlite_insert(KgNode).values(graph=graph, label=n["label"], key=n["key"][:200], name=(n.get("name") or n["key"])[:300],
                                            props=n.get("props") or {}, document_id=n.get("document_id"), created_at=func.now())  # fmt: skip
        stmt = stmt.on_conflict_do_update(index_elements=["graph", "label", "key"],
                                          set_={"name": stmt.excluded.name, "props": stmt.excluded.props,
                                                "document_id": func.coalesce(stmt.excluded.document_id, KgNode.document_id)})  # fmt: skip
        n_new += db.execute(stmt).rowcount or 0
    db.flush()
    ids = node_ids(db, graph)
    n_edges = 0
    for e in edges:
        s, d = ids.get(tuple(e["src"])), ids.get(tuple(e["dst"]))
        if s is None or d is None:
            continue
        stmt = sqlite_insert(KgEdge).values(graph=graph, src=s, dst=d, type=e["type"], props=e.get("props") or {})
        n_edges += db.execute(stmt.on_conflict_do_nothing(index_elements=["graph", "src", "dst", "type"])).rowcount or 0
    db.commit()
    return {"nodes": n_new, "edges": n_edges}


def node_ids(db: Session, graph: str) -> dict[tuple[str, str], int]:
    return {(lb, k): i for i, lb, k in db.execute(select(KgNode.id, KgNode.label, KgNode.key).where(KgNode.graph == graph))}


def clear(db: Session, graph: str) -> int:
    db.execute(delete(KgEdge).where(KgEdge.graph == graph))
    n = db.execute(delete(KgNode).where(KgNode.graph == graph)).rowcount or 0
    db.commit()
    return n


def stats(db: Session, graph: str) -> dict[str, Any]:
    labels = dict(db.execute(select(KgNode.label, func.count()).where(KgNode.graph == graph).group_by(KgNode.label)).all())
    types = dict(db.execute(select(KgEdge.type, func.count()).where(KgEdge.graph == graph).group_by(KgEdge.type)).all())
    return {"graph": graph, "nodes": sum(labels.values()), "edges": sum(types.values()), "labels": labels, "types": types}


def graphs(db: Session) -> list[str]:
    return list(db.scalars(select(KgNode.graph).distinct()))


def nodes_of(db: Session, graph: str, ids: Iterable[int] | None = None, label: str | None = None) -> list[KgNode]:
    q = select(KgNode).where(KgNode.graph == graph)
    if ids is not None:
        q = q.where(KgNode.id.in_(list(ids)))
    if label:
        q = q.where(KgNode.label == label)
    return list(db.scalars(q))


def edges_of(db: Session, graph: str) -> list[KgEdge]:
    return list(db.scalars(select(KgEdge).where(KgEdge.graph == graph)))


def neighbors(db: Session, graph: str, seeds: Iterable[int], types: list[str] | None = None, hops: int = 1,
              limit: int = 300) -> tuple[list[KgNode], list[KgEdge]]:  # fmt: skip
    """seeds 에서 hops 단계 이웃(방향 무시). → (노드들, 관계들). 너무 퍼지지 않게 limit 개 노드에서 멈춘다."""
    seen, frontier = set(seeds), set(seeds)
    found: dict[int, KgEdge] = {}
    for _ in range(hops):
        if not frontier or len(seen) >= limit:
            break
        q = select(KgEdge).where(KgEdge.graph == graph, or_(KgEdge.src.in_(frontier), KgEdge.dst.in_(frontier)))
        if types:
            q = q.where(KgEdge.type.in_(types))
        nxt = set()
        for e in db.scalars(q):
            found[e.id] = e
            for n in (e.src, e.dst):
                if n not in seen:
                    nxt.add(n)
        nxt = set(list(nxt)[: max(0, limit - len(seen))])
        seen |= nxt
        frontier = nxt
    edges = [e for e in found.values() if e.src in seen and e.dst in seen]
    return nodes_of(db, graph, seen), edges


# ── Cypher 엔진 선택 ──────────────────────────────────────────────────────
ENGINES = ("neo4j", "falkordb")
ENGINE_LABELS = {"neo4j": "Neo4j", "falkordb": "FalkorDB"}


def engine_name(requested: str | None = None) -> str:
    """요청 → 설정(GRAPH_ENGINE) → 연결이 설정된 쪽(둘 다면 neo4j)."""
    st = get_settings()
    name = requested or st.graph_engine or ("neo4j" if st.neo4j_url else "falkordb" if st.falkordb_url else "neo4j")
    if name not in ENGINES:
        raise GraphUnavailable(f"알 수 없는 Cypher 엔진: {name} ({', '.join(ENGINES)})")
    return name


def engines_status() -> list[dict[str, Any]]:
    out = []
    for e in ENGINES:
        s = neo4j_status() if e == "neo4j" else falkordb_status()
        out.append({"engine": e, "label": ENGINE_LABELS[e]} | s)
    return out


def sync(db: Session, graph: str, engine: str | None = None) -> dict[str, Any]:
    e = engine_name(engine)
    out = neo4j_sync(db, graph) if e == "neo4j" else falkordb_sync(db, graph)
    return out | {"engine": e}


def cypher_read(query: str, params: dict[str, Any] | None = None, limit: int = 200, engine: str | None = None) -> dict[str, Any]:
    """읽기 전용 Cypher → {"columns", "rows", "type", "engine"}."""
    e = engine_name(engine)
    out = neo4j_read(query, params, limit) if e == "neo4j" else falkordb_read(query, params, limit)
    return out | {"engine": e}


# ── Neo4j(Cypher) ──────────────────────────────────────────────────────────
_driver: Any = None


def neo4j_driver() -> Any:
    global _driver
    st = get_settings()
    if not st.neo4j_url:
        raise GraphUnavailable("NEO4J_URL 이 설정되지 않았습니다 (.env) — docker compose --profile neo4j up -d")
    if _driver is None:
        from neo4j import GraphDatabase

        _driver = GraphDatabase.driver(st.neo4j_url, auth=(st.neo4j_user, st.neo4j_password) if st.neo4j_password else None)
    return _driver


def neo4j_status() -> dict[str, Any]:
    try:
        d = neo4j_driver()
        d.verify_connectivity()
        return {"ok": True, "url": get_settings().neo4j_url}
    except Exception as exc:  # 연결 실패 · 설정 없음 모두 화면에 이유를 보여 준다
        return {"ok": False, "url": get_settings().neo4j_url, "detail": str(exc)[:300]}


def neo4j_sync(db: Session, graph: str, batch: int = 500) -> dict[str, Any]:
    """앱 DB 의 그래프를 Neo4j 로 통째로 옮긴다. Neo4j 에는 그래프 하나만 둔다(옮길 때 전부 지움) — Text2Cypher 가 만든 쿼리에
    graph 조건이 빠져도 다른 그래프가 섞이지 않게. 노드 속성: key · name · graph · props 펼침."""
    d = neo4j_driver()
    ns, es = nodes_of(db, graph), edges_of(db, graph)
    by_id = {n.id: n for n in ns}
    with d.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        for label in {n.label for n in ns}:  # 레이블별 제약 — 같은 key 가 두 번 생기지 않게, MATCH 가 빠르게
            s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE (n.graph, n.key) IS UNIQUE").consume()
        for label in {n.label for n in ns}:
            rows = [{"key": n.key, "name": n.name, "props": {k: v for k, v in (n.props or {}).items() if isinstance(v, (str, int, float, bool))}}
                    for n in ns if n.label == label]  # fmt: skip
            for i in range(0, len(rows), batch):
                s.run(f"UNWIND $rows AS r CREATE (n:`{label}` {{graph: $g, key: r.key, name: r.name}}) SET n += r.props",
                      rows=rows[i : i + batch], g=graph).consume()  # fmt: skip
        for t in {e.type for e in es}:
            rows = [
                {"sl": by_id[e.src].label, "sk": by_id[e.src].key, "dl": by_id[e.dst].label, "dk": by_id[e.dst].key}
                for e in es
                if e.type == t
            ]
            for lbl_pair in {(r["sl"], r["dl"]) for r in rows}:
                part = [r for r in rows if (r["sl"], r["dl"]) == lbl_pair]
                for i in range(0, len(part), batch):
                    s.run(f"UNWIND $rows AS r MATCH (a:`{lbl_pair[0]}` {{graph: $g, key: r.sk}}), (b:`{lbl_pair[1]}` {{graph: $g, key: r.dk}}) "
                          f"CREATE (a)-[:`{t}`]->(b)", rows=part[i : i + batch], g=graph).consume()  # fmt: skip
    return {"nodes": len(ns), "edges": len(es)}


def neo4j_read(query: str, params: dict[str, Any] | None = None, limit: int = 200) -> dict[str, Any]:
    """읽기 전용 Cypher(Neo4j). EXPLAIN 으로 쿼리 종류가 읽기('r')인지 먼저 본다 → {"columns", "rows", "type"}."""
    d = neo4j_driver()
    with d.session() as s:
        summary = s.run("EXPLAIN " + query, params or {}).consume()
        qtype = getattr(summary, "query_type", None)
        if qtype != "r":
            raise PermissionError(f"읽기 쿼리만 실행합니다(쿼리 종류: {qtype}).")
        res = s.run(query, params or {})
        cols = list(res.keys())
        rows = [[_plain(v) for v in rec.values()] for rec in res.fetch(limit)]
        return {"columns": cols, "rows": rows, "type": qtype}


def _plain(v: Any) -> Any:
    """Neo4j 노드 · 관계 · 경로를 JSON 으로 — 노드는 name(없으면 key)."""
    if hasattr(v, "labels") and hasattr(v, "get"):
        return v.get("name") or v.get("key")
    if hasattr(v, "type") and hasattr(v, "start_node"):
        return v.type
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


# ── FalkorDB(OpenCypher) ───────────────────────────────────────────────────
FALKOR_GRAPH = "kg"  # FalkorDB 에도 그래프 하나만 — Neo4j 와 같은 이유(쿼리에 그래프 조건이 빠져도 섞이지 않게)
_falkor: Any = None


def falkordb_client() -> Any:
    global _falkor
    st = get_settings()
    if not st.falkordb_url:
        raise GraphUnavailable("FALKORDB_URL 이 설정되지 않았습니다 (.env) — docker compose --profile falkordb up -d")
    if _falkor is None:
        from falkordb import FalkorDB

        _falkor = FalkorDB.from_url(st.falkordb_url)
    return _falkor


def falkordb_status() -> dict[str, Any]:
    try:
        c = falkordb_client()
        c.connection.ping()
        return {"ok": True, "url": get_settings().falkordb_url}
    except Exception as exc:  # 연결 실패 · 설정 없음 모두 화면에 이유를 보여 준다
        return {"ok": False, "url": get_settings().falkordb_url, "detail": str(exc)[:300]}


def falkordb_sync(db: Session, graph: str, batch: int = 500) -> dict[str, Any]:
    """앱 DB 의 그래프를 FalkorDB 로 통째로(기존 그래프는 지움). 노드 속성은 Neo4j 와 같게: key · name · graph · props 펼침."""
    c = falkordb_client()
    if FALKOR_GRAPH in c.list_graphs():
        c.select_graph(FALKOR_GRAPH).delete()
    g = c.select_graph(FALKOR_GRAPH)
    ns, es = nodes_of(db, graph), edges_of(db, graph)
    by_id = {n.id: n for n in ns}
    for label in {n.label for n in ns}:
        rows = [{"key": n.key, "name": n.name, "props": {k: v for k, v in (n.props or {}).items() if isinstance(v, (str, int, float, bool))}}
                for n in ns if n.label == label]  # fmt: skip
        for i in range(0, len(rows), batch):
            g.query(
                f"UNWIND $rows AS r CREATE (n:`{label}` {{graph: $g, key: r.key, name: r.name}}) SET n += r.props",
                {"rows": rows[i : i + batch], "g": graph},
            )
        g.query(f"CREATE INDEX FOR (n:`{label}`) ON (n.key)")  # 관계를 붙일 때 key 로 찾는다
    for t in {e.type for e in es}:
        rows = [
            {"sl": by_id[e.src].label, "sk": by_id[e.src].key, "dl": by_id[e.dst].label, "dk": by_id[e.dst].key} for e in es if e.type == t
        ]
        for pair in {(r["sl"], r["dl"]) for r in rows}:
            part = [r for r in rows if (r["sl"], r["dl"]) == pair]
            for i in range(0, len(part), batch):
                g.query(f"UNWIND $rows AS r MATCH (a:`{pair[0]}` {{key: r.sk}}), (b:`{pair[1]}` {{key: r.dk}}) CREATE (a)-[:`{t}`]->(b)",
                        {"rows": part[i : i + batch]})  # fmt: skip
    return {"nodes": len(ns), "edges": len(es)}


def falkordb_read(query: str, params: dict[str, Any] | None = None, limit: int = 200) -> dict[str, Any]:
    """읽기 전용 Cypher(FalkorDB) — GRAPH.RO_QUERY 가 쓰기를 서버에서 거절한다(그 오류는 PermissionError 로)."""
    g = falkordb_client().select_graph(FALKOR_GRAPH)
    run = falkor_dialect(query)
    try:
        r = g.ro_query(run, params or {})
    except Exception as exc:
        if "read-only" in str(exc):
            raise PermissionError("읽기 쿼리만 실행합니다(GRAPH.RO_QUERY 가 거절).") from exc
        raise
    cols = [h[1] for h in r.header]
    rows = [[_plain_falkor(v) for v in row] for row in r.result_set[:limit]]
    return {"columns": cols, "rows": rows, "type": "r"} | ({"rewritten": run} if run != query else {})


_EXISTS = re.compile(r"EXISTS\s*\{\s*(?P<pat>\([^{}]*\))\s*\}", re.IGNORECASE)
_PAT_VAR = re.compile(r"(?<=[(\[])\s*(?P<v>[A-Za-z_]\w*)(?=\s*[:)\]{])")
_CLAUSE = re.compile(r"\b(MATCH|WHERE|RETURN|WITH)\b", re.IGNORECASE)


def falkor_dialect(query: str) -> str:
    """Neo4j 의 'EXISTS { (패턴) }' → FalkorDB 가 받는 패턴 조건. 하위 쿼리 안에서만 쓴 변수는 지운다
    ('(p:Precedent)' → '(:Precedent)') — 패턴 조건은 새 변수를 들일 수 없어서(두 엔진 모두). MATCH · WHERE 가 든 하위 쿼리는
    뜻이 바뀔 수 있어 그대로 두고 엔진 오류를 돌려준다.
    왜 여기서 바꾸나: 엔진 비교 실측에서 소형 LLM 이 프롬프트 규칙 · 재시도 안내에도 EXISTS { } 를 세 번 모두 다시 썼다."""

    def one(m: re.Match[str]) -> str:
        pat = m.group("pat")
        if _CLAUSE.search(pat):
            return m.group(0)
        outside = query[: m.start()] + query[m.end() :]
        for v in {x.group("v") for x in _PAT_VAR.finditer(pat)}:
            if not re.search(rf"\b{v}\b", outside):
                pat = re.sub(rf"(?<=[(\[])\s*{v}\b", "", pat)
        return pat

    return _EXISTS.sub(one, query)


def _plain_falkor(v: Any) -> Any:
    """FalkorDB 노드 · 관계 · 경로를 JSON 으로 — Neo4j 쪽(_plain)과 같은 모양(노드는 name, 없으면 key)."""
    if hasattr(v, "labels") and hasattr(v, "properties"):
        return v.properties.get("name") or v.properties.get("key")
    if hasattr(v, "relation") and hasattr(v, "properties"):
        return v.relation
    if hasattr(v, "nodes") and callable(getattr(v, "nodes", None)):
        return [_plain_falkor(n) for n in v.nodes()]
    if isinstance(v, list):
        return [_plain_falkor(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain_falkor(x) for k, x in v.items()}
    return v
