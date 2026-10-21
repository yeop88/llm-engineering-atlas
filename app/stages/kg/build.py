"""그래프 구축 작업: 추출(K3) → 쟁점 합치기(K4) → 온톨로지 검증(K2) → 내장 그래프 저장소에 적재(K5), 커뮤니티 요약(K8)."""

import re
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import graphstore, llm
from app.core.db import Document, KgEdge, KgNode
from app.stages.kg import extract, fusion, graphrag, ontology


def is_precedent(d: Document) -> bool:
    return ((d.meta or {}).get("source") or {}).get("kind") == "precedent" or d.filename.startswith("판례")


def build(db: Session, collection_id: int, graph: str, job: Any = None, lcfg: llm.LLMConfig | None = None,
          embed: Callable[[list[str]], np.ndarray] | None = None, issue_limit: int = 0,
          reuse_issues: dict[str, list[str]] | None = None) -> dict[str, Any]:  # fmt: skip
    """issue_limit: 쟁점을 LLM 으로 뽑을 판례 수(0 = 뽑지 않음, -1 = 모두). 판례당 로컬 LLM 5~10초라 처음에는 일부로."""
    t0 = time.perf_counter()
    upd = job.update if job else (lambda *a, **k: None)
    docs = list(db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for i, d in enumerate(docs):
        upd(0.05 + 0.25 * i / max(1, len(docs)), f"추출 {i + 1}/{len(docs)}")
        if is_precedent(d):
            n, e, h = extract.precedent(d)
            if h:
                holdings.append(h)
        else:
            n, e = extract.statute(d)
        nodes += n
        edges += e
    t_extract = time.perf_counter() - t0
    per_case: dict[str, list[str]] = {}
    issue_stats: dict[str, Any] = {"asked": 0, "with_issues": 0, "seconds": 0.0}
    if reuse_issues:  # 앞선 구축이 뽑은 쟁점을 다시 쓴다 — 합치기 규칙만 바꿔 다시 만들 때 LLM 을 15분 다시 부르지 않게
        have = {h["case_no"] for h in holdings}
        per_case = {k: v for k, v in reuse_issues.items() if k in have}
        issue_stats |= {"reused": len(per_case)}
    elif lcfg and issue_limit:
        todo = holdings if issue_limit < 0 else holdings[:issue_limit]
        t1 = time.perf_counter()
        for i, h in enumerate(todo):
            upd(0.3 + 0.5 * i / max(1, len(todo)), f"쟁점 추출 {i + 1}/{len(todo)} · {h['case_no']}")
            got = extract.extract_issues(lcfg, h["holding"])
            issue_stats["asked"] += 1
            if got:
                per_case[h["case_no"]] = got
                issue_stats["with_issues"] += 1
        issue_stats["seconds"] = round(time.perf_counter() - t1, 1)
    merged = fusion.merge_issues(per_case, embed) if per_case else {"nodes": [], "edges": [], "merges": [], "n_raw": 0, "n_issues": 0}
    nodes += merged["nodes"]
    edges += merged["edges"]
    nodes += extract.external_nodes(nodes, edges)
    v = ontology.validate(nodes, edges)
    upd(0.85, "적재")
    graphstore.clear(db, graph)
    saved = graphstore.upsert(db, graph, v["nodes"], v["edges"])
    return {"graph": graph, "collection_id": collection_id, "documents": len(docs), "saved": saved, "stats": graphstore.stats(db, graph),
            "rejected": v["rejected"][:50], "n_rejected": len(v["rejected"]), "issues": issue_stats | {"raw": merged["n_raw"], "merged": merged["n_issues"]},
            "merges": merged["merges"][:30], "issues_raw": per_case, "seconds": {"extract": round(t_extract, 1), "total": round(time.perf_counter() - t0, 1)}}  # fmt: skip


def _holding(doc: Document | None) -> str:
    if doc is None:
        return ""
    text = "\n".join(doc.pages or [])
    m = re.search(r"【판시사항】(.*?)(?=【|$)", text, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def communities(db: Session, graph: str, lcfg: llm.LLMConfig, job: Any = None, top: int = 12, min_size: int = 4) -> dict[str, Any]:
    """커뮤니티 탐지 → 큰 묶음부터 top 개 LLM 요약 → Community 노드 · IN_COMMUNITY 관계로 저장(앞선 요약은 지움)."""
    upd = job.update if job else (lambda *a, **k: None)
    t0 = time.perf_counter()
    upd(0.05, "커뮤니티 탐지")
    comms = graphrag.detect(db, graph, min_size=min_size)
    old = list(db.scalars(select(KgNode.id).where(KgNode.graph == graph, KgNode.label == "Community")))
    if old:
        db.execute(delete(KgEdge).where(KgEdge.graph == graph, KgEdge.dst.in_(old)))
        db.execute(delete(KgNode).where(KgNode.id.in_(old)))
        db.commit()
    docs = {
        d.id: d
        for d in db.scalars(select(Document).where(Document.id.in_({n.document_id for c in comms[:top] for n in c if n.document_id})))
    }
    nodes, edges, out, tokens = [], [], [], 0
    for i, members in enumerate(comms[:top]):
        upd(0.1 + 0.85 * i / max(1, min(top, len(comms))), f"요약 {i + 1}/{min(top, len(comms))} (구성원 {len(members)})")
        texts = {n.id: _holding(docs.get(n.document_id)) for n in members if n.label == "Precedent"}
        s = graphrag.summarize(lcfg, members, texts)
        tokens += int(((s.get("usage") or {}).get("input_tokens") or 0) + ((s.get("usage") or {}).get("output_tokens") or 0))
        key = f"c-{i + 1}"
        labels = {lb: sum(1 for n in members if n.label == lb) for lb in ("Article", "Precedent", "Issue")}
        nodes.append(
            {"label": "Community", "key": key, "name": s["name"], "props": {"summary": s["summary"], "size": len(members)} | labels}
        )
        edges += [{"src": (n.label, n.key), "dst": ("Community", key), "type": "IN_COMMUNITY"} for n in members]
        out.append({"key": key, "name": s["name"], "summary": s["summary"], "size": len(members), "members": labels,
                    "top": [n.name for n in members[:6]], "seconds": s.get("seconds")})  # fmt: skip
    graphstore.upsert(db, graph, nodes, edges)
    return {"graph": graph, "n_communities": len(comms), "summarized": len(out), "sizes": [len(c) for c in comms[:30]],
            "communities": out, "tokens": tokens, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


def stored_communities(db: Session, graph: str) -> list[dict[str, Any]]:
    return [{"key": n.key, "name": n.name, "summary": (n.props or {}).get("summary", ""), "size": (n.props or {}).get("size", 0)}
            for n in graphstore.nodes_of(db, graph, label="Community")]  # fmt: skip
