"""RC7 규정 조항 ↔ 시스템 통제 매핑: 지식 그래프 저장소(K5)에 '통제 -근거→ 조항', '기능 -적용→ 통제'를 잇는다.

지식 그래프 맵의 '판례 -인용→ 조문'과 같은 방식이고, 조항 노드는 법령 문서에서 정형 추출(K3, kg.extract.statute)로 만든다 —
그래서 시행령 조문의 '법 제N조' 참조(REFERS_TO)도 함께 들어와, 시행령이 바뀌어도 모법 조항을 거쳐 통제를 찾을 수 있다.
개정 감시(corpus.revisions)가 바뀐 조항 키를 주면 impact 가 영향받는 통제 · 기능을 바로 돌려준다.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import graphstore
from app.core.db import KgEdge, KgNode
from app.stages.compliance import catalog, corpus, scope
from app.stages.kg import extract

GRAPH = "compliance"


def build(db: Session, collection_id: int) -> dict[str, Any]:
    graphstore.clear(db, GRAPH)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for d in corpus.statute_docs(db, collection_id):
        n, e = extract.statute(d)
        nodes += n
        edges += e
    have = {(n["label"], n["key"]) for n in nodes}
    for c in catalog.controls():
        nodes.append({"label": "Control", "key": c["id"], "name": c["name"],
                      "props": {"kind": c["kind"], "where": c["where"], "implemented": c.get("implemented", True)}})  # fmt: skip
    missing = []
    for r in catalog.rules():
        key = scope.rule_key(r)
        if ("Article", key) not in have:  # 규칙이 가리키는 조항이 자료에 없음(판이 다르거나 법령을 안 넣음) — 노드는 두되 표시
            missing.append(key)
            nodes.append({"label": "Article", "key": key, "name": key, "props": {"missing": True}})
            have.add(("Article", key))
        for c in r["controls"]:
            edges.append(
                {
                    "src": ("Control", c),
                    "dst": ("Article", key),
                    "type": "BASED_ON",
                    "props": {"rule": r["id"], "obligation": r["obligation"]},
                }
            )
    for p in catalog.profiles():
        nodes.append(
            {"label": "Feature", "key": p["key"], "name": p["name"], "props": {"attrs": p["attrs"], "example": bool(p.get("example"))}}
        )
        for c in sorted({c for r in scope.applicable(p) for c in r["controls"]}):
            edges.append({"src": ("Feature", p["key"]), "dst": ("Control", c), "type": "APPLIES"})
    saved = graphstore.upsert(db, GRAPH, nodes, edges)
    return {"graph": GRAPH, "collection_id": collection_id, "saved": saved, "missing_articles": sorted(set(missing)),
            "stats": graphstore.stats(db, GRAPH)}  # fmt: skip


def impact(db: Session, keys: list[str]) -> dict[str, Any]:
    """바뀐 조항 키 → 그 조항을 근거로 둔 통제 → 그 통제를 쓰는 기능. 시행령 조항은 '법 제N조' 참조로 모법 조항까지 한 단계 따라간다."""
    ids = graphstore.node_ids(db, GRAPH)
    nodes = {n.id: n for n in db.scalars(select(KgNode).where(KgNode.graph == GRAPH))}
    edges = db.scalars(select(KgEdge).where(KgEdge.graph == GRAPH)).all()
    start = {ids[("Article", k)] for k in keys if ("Article", k) in ids}
    via = {e.dst: e.src for e in edges if e.type == "REFERS_TO" and e.src in start}  # 시행령 조항 → 모법 조항
    arts = start | set(via)
    out_controls: dict[str, dict[str, Any]] = {}
    for e in edges:
        if e.type == "BASED_ON" and e.dst in arts:
            c = nodes[e.src]
            row = out_controls.setdefault(c.key, {"id": c.key, "name": c.name, "articles": [], "rules": [], "features": []})
            a = nodes[e.dst].key
            row["articles"].append(a + (f" (← {nodes[via[e.dst]].key})" if e.dst in via and e.dst not in start else ""))
            row["rules"].append((e.props or {}).get("rule"))
    for e in edges:
        if e.type == "APPLIES" and nodes[e.dst].key in out_controls:
            out_controls[nodes[e.dst].key]["features"].append(nodes[e.src].name)
    feats = sorted({f for c in out_controls.values() for f in c["features"]})
    return {"keys": keys, "matched": [nodes[i].key for i in start], "unmatched": [k for k in keys if ("Article", k) not in ids],
            "controls": list(out_controls.values()), "features": feats}  # fmt: skip


def overview(db: Session) -> dict[str, Any]:
    """통제마다 근거 조항 수 · 적용 기능 — 근거가 없는 통제(규칙에 안 걸림)도 드러난다."""
    nodes = {n.id: n for n in db.scalars(select(KgNode).where(KgNode.graph == GRAPH))}
    if not nodes:
        return {"built": False, "controls": []}
    edges = db.scalars(select(KgEdge).where(KgEdge.graph == GRAPH)).all()
    rows = []
    for c in [n for n in nodes.values() if n.label == "Control"]:
        arts = sorted({nodes[e.dst].key for e in edges if e.type == "BASED_ON" and e.src == c.id})
        feats = sorted({nodes[e.src].name for e in edges if e.type == "APPLIES" and e.dst == c.id})
        rows.append({"id": c.key, "name": c.name, "kind": (c.props or {}).get("kind"), "implemented": (c.props or {}).get("implemented", True),
                     "articles": arts, "features": feats})  # fmt: skip
    return {"built": True, "stats": graphstore.stats(db, GRAPH), "controls": rows}
