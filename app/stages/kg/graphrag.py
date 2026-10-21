"""K7 그래프 하이브리드 검색 · K8 글로벌 커뮤니티 요약.

K7: 1단계는 기존 RAG 검색(벡터 · BM25 · 하이브리드)을 그대로 쓰고, 찾은 문서의 그래프 노드에서 이웃을 따라 근거를 넓힌다.
    - 판례 → 그 판례가 인용한 조문 · 판례, 같은 조문을 인용한 다른 판례(공동 인용), 같은 쟁점의 판례
    - 조문 → 그 조문을 인용한 판례, 시행령 ↔ 법률 조문
    넓힌 문서는 '연결 수'(같은 이웃을 여러 번 공유할수록 위)로 줄 세워 벡터 결과 뒤에 붙인다 — 벡터 1위를 밀어내지 않게.
    여러 문서 질문(두 판례가 함께 정답)은 벡터 검색이 하나만 찾는 경우가 많은데, 두 판례가 같은 조문을 인용하면 그래프가 이어 준다.

K8: 그래프를 커뮤니티(서로 많이 이어진 묶음)로 나눠 묶음마다 LLM 요약을 미리 만들고, '전체적으로 어떤 쟁점이 있나' 같은 질문은
    청크가 아니라 요약들을 모아 답한다(청크 검색은 전체를 보지 못한다).
"""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import networkx as nx
import numpy as np
from sqlalchemy.orm import Session

from app.core import graphstore, llm
from app.core.db import KgEdge, KgNode
from app.stages.kg.extract import ART_HEAD, article_key, law_name

EXPAND_TYPES = ["CITES", "CITES_CASE", "REFERS_TO", "CONCERNS"]


# ── K7 그래프 하이브리드 ───────────────────────────────────────────────────
def seed_nodes(db: Session, graph: str, results: list[dict[str, Any]]) -> list[int]:
    """검색 결과 → 그래프 노드. 판례 문서는 문서 노드, 법령 청크는 청크 앞의 조문 머리로 조문 노드를 찾는다."""
    doc_ids = {r.get("document_id") for r in results if r.get("document_id")}
    by_doc: dict[int, list[KgNode]] = {}
    for n in graphstore.nodes_of(db, graph):
        if n.document_id in doc_ids:
            by_doc.setdefault(n.document_id, []).append(n)
    ids = graphstore.node_ids(db, graph)
    seeds: list[int] = []
    for r in results:
        nodes = by_doc.get(r.get("document_id"), [])
        prec = [n.id for n in nodes if n.label == "Precedent"]
        if prec:
            seeds += prec
            continue
        law = law_name(re.sub(r"\.(txt|md)$", "", r.get("filename") or ""))
        for m in ART_HEAD.finditer(r.get("text") or ""):
            if (nid := ids.get(("Article", article_key(law, m.group(1), m.group(2))))) is not None:
                seeds.append(nid)
    return list(dict.fromkeys(seeds))


def expand(db: Session, graph: str, results: list[dict[str, Any]], max_docs: int = 3, hops: int = 2) -> dict[str, Any]:
    """→ {"seeds", "docs": [{"document_id", "name", "links", "via"}], "relations": [글], "nodes", "edges"}."""
    seeds = seed_nodes(db, graph, results)
    if not seeds:
        return {"seeds": [], "docs": [], "relations": [], "nodes": 0, "edges": 0}
    nodes, edges = graphstore.neighbors(db, graph, seeds, EXPAND_TYPES, hops=hops, limit=400)
    by_id = {n.id: n for n in nodes}
    have = {r.get("document_id") for r in results}
    seed_set = set(seeds)
    score: Counter[int] = Counter()
    via: dict[int, list[str]] = {}
    adj: dict[int, set[int]] = {}
    for e in edges:
        adj.setdefault(e.src, set()).add(e.dst)
        adj.setdefault(e.dst, set()).add(e.src)
    for n in nodes:  # 씨앗과 직접 또는 공유 이웃(조문 · 쟁점)으로 이어진 문서 노드
        if n.document_id is None or n.document_id in have or n.id in seed_set:
            continue
        direct = adj.get(n.id, set()) & seed_set
        shared = {m for m in adj.get(n.id, set()) if adj.get(m, set()) & seed_set and m not in seed_set}
        links = len(direct) * 2 + len(shared)  # 직접 인용이 공동 인용보다 강한 연결
        if links:
            score[n.id] += links
            via[n.id] = [by_id[m].name for m in list(direct)[:2]] + [by_id[m].name for m in list(shared)[:3]]
    docs, seen_doc = [], set()
    for nid, sc in score.most_common():
        d = by_id[nid].document_id
        if d in seen_doc:
            continue
        seen_doc.add(d)
        docs.append({"document_id": d, "node": by_id[nid].name, "label": by_id[nid].label, "links": sc, "via": via[nid]})
        if len(docs) >= max_docs:
            break
    return {"seeds": [by_id[s].name for s in seeds if s in by_id], "docs": docs, "relations": relation_lines(edges, by_id, seed_set),
            "nodes": len(nodes), "edges": len(edges)}  # fmt: skip


REL_KO = {"CITES": "인용", "CITES_CASE": "판례 인용", "REFERS_TO": "참조", "CONCERNS": "다룸", "PART_OF": "속함"}


def relation_lines(edges: list[KgEdge], by_id: dict[int, KgNode], seeds: set[int], limit: int = 12) -> list[str]:
    """답변 근거에 붙일 '관계 요약' — 씨앗에 닿은 관계부터."""
    rows = sorted(edges, key=lambda e: -((e.src in seeds) + (e.dst in seeds)))
    out = []
    for e in rows:
        a, b = by_id.get(e.src), by_id.get(e.dst)
        if a and b:
            out.append(f"{a.name} -{REL_KO.get(e.type, e.type)}-> {b.name}")
        if len(out) >= limit:
            break
    return out


# ── K8 커뮤니티 ───────────────────────────────────────────────────────────
def detect(db: Session, graph: str, min_size: int = 3, seed: int = 7) -> list[list[KgNode]]:
    """조문 · 판례 · 쟁점 그래프에서 Louvain 커뮤니티(크기 순). 법령 노드와 '속함'은 뺀다 — 넣으면 법령마다 한 덩어리가 돼
    '같은 문제를 다루는 조문 · 판례' 묶음이 아니라 법령 목차가 된다. 커뮤니티 노드(앞선 실행)도 뺀다."""
    g = nx.Graph()
    nodes = {n.id: n for n in graphstore.nodes_of(db, graph) if n.label in ("Article", "Precedent", "Issue")}
    g.add_nodes_from(nodes)
    for e in graphstore.edges_of(db, graph):
        if e.type in ("CITES", "CITES_CASE", "REFERS_TO", "CONCERNS") and e.src in nodes and e.dst in nodes:
            g.add_edge(e.src, e.dst)
    g.remove_nodes_from([n for n in list(g.nodes) if g.degree(n) == 0])
    comms = nx.community.louvain_communities(g, seed=seed) if g.number_of_edges() else []
    out = [[nodes[i] for i in c] for c in comms if len(c) >= min_size]
    return sorted(out, key=lambda c: -len(c))


SUM_SYSTEM = ("당신은 법률 지식 그래프의 한 묶음(서로 인용으로 이어진 조문 · 판례 · 쟁점)을 요약합니다. 이 묶음이 다루는 법적 주제와 "
              "핵심 쟁점, 중심이 되는 조문, 판례들의 흐름을 4~6문장으로 씁니다. 주어진 목록에 없는 내용은 지어내지 않습니다. "
              "첫 줄에 '이름: <8단어 안의 묶음 이름>'을 쓰고, 다음 줄부터 요약을 씁니다.")  # fmt: skip


def community_brief(members: list[KgNode], texts: dict[int, str], max_items: int = 25) -> str:
    """요약 프롬프트용 묶음 설명 — 쟁점 · 조문(제목) · 판례(사건명 · 판시사항 앞부분)."""
    deg = sorted(members, key=lambda n: (n.label != "Issue", n.label != "Article"))
    rows = []
    for n in deg[:max_items]:
        if n.label == "Precedent":
            rows.append(f"- 판례 {n.name}: {texts.get(n.id, '')[:200]}")
        elif n.label == "Article":
            rows.append(f"- 조문 {n.name}")
        else:
            rows.append(f"- 쟁점 {n.name}")
    return "\n".join(rows)


def summarize(lcfg: llm.LLMConfig, members: list[KgNode], texts: dict[int, str]) -> dict[str, Any]:
    r = llm.chat(lcfg, SUM_SYSTEM, community_brief(members, texts), 500, 0.1)
    text = (r["text"] or "").strip()
    m = re.match(r"\s*이름\s*[:：]\s*(.+)", text)
    name = m.group(1).strip()[:60] if m else (members[0].name[:40])
    summary = text[m.end() :].strip() if m else text
    return {"name": name, "summary": summary, "seconds": r.get("seconds"), "usage": r.get("usage")}


GLOBAL_SYSTEM = ("당신은 법률 지식 그래프의 묶음 요약들을 보고 전체를 묻는 질문에 답합니다. 요약에 있는 내용만 쓰고, 문장마다 근거 묶음 번호를 "
                 "[C1] 처럼 붙입니다. '흐름 · 경향 · 전체'를 물으면 요약들의 쟁점을 묶어 정리합니다 — 요약에 시기 · 연도가 없으면 그렇다고 한 줄 "
                 "밝히고 쟁점 중심으로 답합니다. 요약이 질문 주제와 전혀 관련이 없을 때만 '요약에서 찾을 수 없습니다'라고 답합니다.")  # fmt: skip
# 거절 조건을 '주제와 무관할 때만'으로 좁힌 이유: 2차 실측에서 '주택임대차 판례의 주요 흐름'에 주택임대차 묶음 4개를 정확히 골랐는데도
# '흐름'을 시간 순서로 읽고(요약에는 연도가 없음) 통째로 거절했다 — 1차와 같은 과잉 거절.


def global_answer(lcfg: llm.LLMConfig, question: str, communities: list[dict[str, Any]], embed: Callable[[list[str]], np.ndarray] | None,
                  top: int = 4) -> dict[str, Any]:  # fmt: skip
    """전체 질문 → 관련 커뮤니티 요약 top 개를 골라(임베딩) 한 번에 답한다. 요약이 적으면 모두."""
    if not communities:
        return {"answer": "커뮤니티 요약이 없습니다 — 먼저 커뮤니티 요약을 만드세요.", "used": []}
    picked = communities
    if embed is not None and len(communities) > top:
        v = embed([question] + [f"{c['name']}. {c['summary']}" for c in communities])
        sims = v[1:] @ v[0]
        picked = [communities[i] for i in np.argsort(-sims)[:top]]
    ctx = "\n\n".join(f"[C{i + 1}] {c['name']} (구성원 {c['size']})\n{c['summary']}" for i, c in enumerate(picked))
    r = llm.chat(lcfg, GLOBAL_SYSTEM, f"[묶음 요약]\n{ctx}\n\n[질문]\n{question}", 700, 0.1)
    return {"answer": r["text"], "used": [{"n": i + 1, "key": c["key"], "name": c["name"], "size": c["size"]} for i, c in enumerate(picked)],
            "seconds": r.get("seconds"), "usage": r.get("usage")}  # fmt: skip
