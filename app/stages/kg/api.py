"""지식 그래프 · GraphRAG API (K1~K8). 원본 그래프는 앱 DB(내장 그래프 저장소), Cypher 는 Neo4j 로 옮겨서."""

import time
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, graphstore, llm
from app.core.auth import current_user, require_admin
from app.core.config import get_settings
from app.core.db import Collection, Document, EmbeddingModel, EvalSet, KgNode, SessionLocal, TestRun, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.apps import common as apps_common
from app.stages.embedding.model_manager import ModelSpec
from app.stages.guardrails import acl
from app.stages.kg import build, evaluate, graphrag, ontology, text2cypher
from app.stages.kg.schemas import BuildIn, CommunitiesIn, CqEvalIn, CypherIn, ExpandIn, HybridEvalIn, QuestionIn

router = APIRouter(prefix="/api/kg", tags=["kg"])
DB = Annotated[Session, Depends(get_db)]
GRAPH_RULE = "아래 '관계 요약'은 지식 그래프에서 근거 문서들이 서로 어떻게 이어지는지(인용 · 참조)입니다. 관계를 설명할 때만 쓰고, 내용의 근거는 근거 자료에서만 가져오세요.\n"


def _embed_fn(db: Session):
    row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == get_settings().verify_model))
    if row is None:
        return None
    spec = ModelSpec.from_row(row)
    return lambda texts: np.asarray(apps_common.embed(spec, texts, "plain"))


def _lcfg(body: Any) -> llm.LLMConfig:
    try:
        return llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


def _collection(db: Session, graph: str) -> int:
    """그래프를 만든 컬렉션(마지막 구축 기록)."""
    for r in db.scalars(select(TestRun).where(TestRun.kind == "kg_build").order_by(TestRun.id.desc())):
        if (r.result or {}).get("graph") == graph:
            return int(r.result["collection_id"])
    # 구축 기록이 없으면(스크립트로 만든 그래프 등) 노드가 가리키는 문서의 컬렉션으로 — 기록이 없다고 화면이 404 로 막히지 않게
    doc_id = db.scalar(select(KgNode.document_id).where(KgNode.graph == graph, KgNode.document_id.is_not(None)).limit(1))
    if doc_id and (d := db.get(Document, doc_id)):
        return d.collection_id
    raise HTTPException(404, f"그래프 '{graph}' 가 없습니다 — 먼저 구축하세요.")


def _search_cfg(db: Session, graph: str, cfg: dict[str, Any] | None) -> dict[str, Any]:
    if cfg:
        return cfg
    out = default_config(db, _collection(db, graph), top_k=10)
    if out is None:
        raise HTTPException(400, "준비된 청크 세트가 없습니다.")
    out.pop("model_id", None)
    return out


# ── K2 온톨로지 · K5 그래프 ─────────────────────────────────────────────────
@router.get("/ontology")
def get_ontology() -> dict:
    return ontology.load() | {"schema_text": ontology.schema_text()}


@router.get("/graphs")
def list_graphs(db: DB) -> list[dict]:
    return [graphstore.stats(db, g) for g in graphstore.graphs(db)]


@router.get("/graphs/{graph}/stats")
def graph_stats(graph: str, db: DB) -> dict:
    s = graphstore.stats(db, graph)
    if not s["nodes"]:
        raise HTTPException(404, "그래프가 비었습니다 — 먼저 구축하세요.")
    return s | {"collection_id": _collection(db, graph)}


@router.post("/build", status_code=202)
def build_graph(body: BuildIn, request: Request, db: DB) -> dict:
    """추출(K3) → 쟁점 합치기(K4) → 검증(K2) → 적재(K5). 같은 이름의 그래프는 지우고 다시 만든다."""
    require_admin(request, "지식 그래프 구축")
    if db.get(Collection, body.collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    lcfg = _lcfg(body) if body.issue_limit and not body.reuse_issues else None
    title = f"지식 그래프 구축 · {body.graph}" + (
        f" · 쟁점 {'전체' if body.issue_limit < 0 else body.issue_limit}" if body.issue_limit else ""
    )

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db2:
            reuse = None
            if body.reuse_issues:
                for r in db2.scalars(select(TestRun).where(TestRun.kind == "kg_build").order_by(TestRun.id.desc())):
                    if (r.result or {}).get("graph") == body.graph and (r.result or {}).get("issues_raw"):
                        reuse = r.result["issues_raw"]
                        break
                if reuse is None:
                    raise ValueError("다시 쓸 쟁점이 없습니다 — 먼저 LLM 쟁점 추출로 구축하세요.")
            out = build.build(db2, body.collection_id, body.graph, job, lcfg, _embed_fn(db2), body.issue_limit, reuse)
            out["run_id"] = crud.record_run(db2, "kg_build", [f"llm:{lcfg.model}"] if lcfg else [], title, body.model_dump(), out, 0).id
        return out

    return jobs.submit("kg_build", title, work).to_dict()


@router.get("/builds")
def builds(db: DB, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(TestRun).where(TestRun.kind == "kg_build").order_by(TestRun.id.desc()).limit(limit))
    return [{"id": r.id, "title": r.title, "created_at": r.created_at.isoformat()} | {k: (r.result or {}).get(k) for k in ("graph", "stats", "issues", "n_rejected", "merges", "seconds")}
            for r in rows]  # fmt: skip


@router.get("/graphs/{graph}/nodes")
def find_nodes(graph: str, db: DB, q: str = "", label: str | None = None, limit: int = 50) -> list[dict]:
    query = select(KgNode).where(KgNode.graph == graph)
    if label:
        query = query.where(KgNode.label == label)
    if q:
        query = query.where(KgNode.name.contains(q) | KgNode.key.contains(q))
    return [{"id": n.id, "label": n.label, "key": n.key, "name": n.name, "props": n.props, "document_id": n.document_id}
            for n in db.scalars(query.limit(min(limit, 500)))]  # fmt: skip


@router.get("/graphs/{graph}/nodes/{node_id}")
def node_detail(graph: str, node_id: int, db: DB, hops: int = 1) -> dict:
    """노드와 이웃(관계 방향 · 이름) — 그래프 탐색 화면."""
    nodes, edges = graphstore.neighbors(db, graph, [node_id], hops=max(1, min(hops, 2)), limit=200)
    by_id = {n.id: n for n in nodes}
    if node_id not in by_id:
        raise HTTPException(404, "노드를 찾을 수 없습니다.")
    me = by_id[node_id]
    return {"node": {"id": me.id, "label": me.label, "key": me.key, "name": me.name, "props": me.props, "document_id": me.document_id},
            "edges": [{"src": e.src, "dst": e.dst, "type": e.type, "src_name": by_id[e.src].name, "dst_name": by_id[e.dst].name,
                       "src_label": by_id[e.src].label, "dst_label": by_id[e.dst].label} for e in edges[:300]]}  # fmt: skip


# ── K7 그래프 하이브리드 ───────────────────────────────────────────────────
@router.post("/graphs/{graph}/expand")
def expand(graph: str, body: ExpandIn, request: Request, db: DB) -> dict:
    """질문 → RAG 검색 → 찾은 문서의 그래프 이웃으로 넓힌 문서 · 관계 요약(답변 없이 검색만)."""
    user = current_user(request)
    cfg = _search_cfg(db, graph, body.config.model_dump(exclude_none=True) if body.config else None)
    cfg |= {"acl_groups": acl.effective_groups(user, cfg.get("acl_groups"))}
    res = run_search(db, body.question, cfg)
    ex = graphrag.expand(db, graph, res["results"][:5], max_docs=body.max_docs)
    return {"results": [{k: r.get(k) for k in ("rank", "document_id", "filename", "score")} for r in res["results"]], "expand": ex}


@router.post("/graphs/{graph}/answer")
def graph_answer(graph: str, body: QuestionIn, request: Request, db: DB) -> dict:
    """GraphRAG 답변: 검색 결과 + 그래프로 넓힌 문서를 근거로, 관계 요약을 시스템 프롬프트에(같은 검증 · 가드레일 · 기록)."""
    user = current_user(request)
    lcfg = _lcfg(body)
    cfg = _search_cfg(db, graph, None) | {"acl_groups": acl.effective_groups(user, None)}
    first = run_search(db, body.question, cfg)
    ex = graphrag.expand(db, graph, first["results"][:5])
    docs = list(dict.fromkeys([r["document_id"] for r in first["results"][:5]] + [d["document_id"] for d in ex["docs"]]))
    out = serve.answer_once(db, body.question, cfg | {"doc_ids": docs, "top_k": 8}, lcfg, user=user,
                            instruction=(GRAPH_RULE + "\n".join(ex["relations"])) if ex["relations"] else "", kind="graphrag", route="graph")  # fmt: skip
    return {k: out.get(k) for k in ("answer", "sources", "verify", "guard", "trace_id", "notice")} | {"expand": ex}


# ── K8 커뮤니티 · 전체 질문 ────────────────────────────────────────────────
@router.post("/graphs/{graph}/communities", status_code=202)
def make_communities(graph: str, body: CommunitiesIn, request: Request) -> dict:
    require_admin(request, "커뮤니티 요약 만들기")
    lcfg = _lcfg(body)
    title = f"커뮤니티 요약 · {graph} · 상위 {body.top}"

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db2:
            out = build.communities(db2, graph, lcfg, job, body.top, body.min_size)
            out["run_id"] = crud.record_run(db2, "kg_communities", [f"llm:{lcfg.model}"], title, body.model_dump(), out, 0).id
        return out

    return jobs.submit("kg_communities", title, work).to_dict()


@router.get("/graphs/{graph}/communities")
def list_communities(graph: str, db: DB) -> list[dict]:
    return build.stored_communities(db, graph)


@router.post("/graphs/{graph}/global")
def global_question(graph: str, body: QuestionIn, db: DB) -> dict:
    """전체 · 추세 질문 — 청크가 아니라 커뮤니티 요약들로 답한다."""
    return graphrag.global_answer(_lcfg(body), body.question, build.stored_communities(db, graph), _embed_fn(db))


# ── K6 Cypher 엔진(Neo4j · FalkorDB) · Text2Cypher ────────────────────────
@router.get("/engines")
def engines() -> dict:
    """Cypher 엔진별 연결 상태와 기본 엔진(GRAPH_ENGINE)."""
    try:
        default = graphstore.engine_name()
    except graphstore.GraphUnavailable:
        default = None
    return {"default": default, "engines": graphstore.engines_status()}


@router.post("/graphs/{graph}/sync")
def sync_graph(graph: str, request: Request, db: DB, engine: str | None = None) -> dict:
    """그래프를 Cypher 엔진으로 옮긴다(관리자, 그 엔진의 기존 그래프는 지움). 시간도 돌려준다 — 엔진 비교용."""
    require_admin(request, "Cypher 엔진으로 옮기기")
    t0 = time.perf_counter()
    try:
        return graphstore.sync(db, graph, engine) | {"graph": graph, "seconds": round(time.perf_counter() - t0, 1)}
    except graphstore.GraphUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/cypher")
def run_cypher(body: CypherIn) -> dict:
    try:
        return graphstore.cypher_read(body.query, engine=body.engine)
    except graphstore.GraphUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:  # Cypher 문법 · 스키마 오류는 그대로 보여 준다
        raise HTTPException(400, f"Cypher 오류: {str(exc)[:400]}") from exc


@router.post("/text2cypher")
def text_to_cypher(body: QuestionIn) -> dict:
    lcfg = _lcfg(body)
    try:
        engine = graphstore.engine_name(body.engine)  # 알 수 없는 엔진 · 설정 없음은 LLM 을 부르기 전에 알린다
        return text2cypher.ask(lcfg, body.question, lambda q: graphstore.cypher_read(q, engine=engine)) | {"engine": engine}
    except graphstore.GraphUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc


# ── K1 역량 질문 · 실측 ────────────────────────────────────────────────────
@router.get("/cq")
def cq_list() -> dict:
    return text2cypher.cq_preset()


@router.post("/cq/eval", status_code=202)
def cq_eval(body: CqEvalIn) -> dict:
    lcfg = _lcfg(body)
    p = text2cypher.cq_preset()
    qs = [q for q in p["questions"] if not body.ids or q["id"] in body.ids]
    try:
        engine = graphstore.engine_name(body.engine)
    except graphstore.GraphUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    title = f"역량 질문 Text2Cypher · {graphstore.ENGINE_LABELS[engine]} · {lcfg.model} · {len(qs)}문항"

    def work(job: Job) -> dict[str, Any]:
        out = evaluate.cq(qs, lcfg, lambda q: graphstore.cypher_read(q, engine=engine), job) | {"llm": lcfg.public(), "engine": engine}
        with SessionLocal() as db2:
            out["run_id"] = crud.record_run(db2, "kg_cq", [f"llm:{lcfg.model}"], title, body.model_dump(), out, 0).id
        return out

    if not next(e for e in graphstore.engines_status() if e["engine"] == engine)["ok"]:  # 연결이 안 되면 작업 전에 알린다
        raise HTTPException(400, f"{graphstore.ENGINE_LABELS[engine]} 에 연결할 수 없습니다.")
    return jobs.submit("kg_cq", title, work).to_dict()


@router.post("/graphs/{graph}/hybrid-eval", status_code=202)
def hybrid_eval(graph: str, body: HybridEvalIn, db: DB) -> dict:
    """평가 세트로 '벡터 상위 k' vs '벡터 + 그래프 확장' 검색 비교(LLM 없이)."""
    s = db.get(EvalSet, body.eval_set_id)
    if s is None:
        raise HTTPException(404, "평가 세트를 찾을 수 없습니다.")
    cfg = _search_cfg(db, graph, body.config.model_dump(exclude_none=True) if body.config else None) | {"top_k": max(body.k * 3, 20)}
    items = [it for it in s.items if it.get("doc_ids") and (not body.only_multi or len(it["doc_ids"]) > 1)][: body.max_queries]
    title = f"그래프 하이브리드 검색 · {graph} · 평가 세트 #{s.id} · {len(items)}문항"

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db2:
            out = evaluate.hybrid(items, lambda q: run_search(db2, q, cfg)["results"], lambda r: graphrag.expand(db2, graph, r, max_docs=body.add),
                                  body.k, body.add, job=job)  # fmt: skip
            out |= {"eval_set": {"id": s.id, "name": s.name}, "config": cfg}
            out["run_id"] = crud.record_run(db2, "kg_hybrid", [], title, body.model_dump(), out, 0).id
        return out

    return jobs.submit("kg_hybrid", title, work).to_dict()


@router.get("/runs")
def kg_runs(db: DB, kind: str | None = None, limit: int = 30) -> list[dict]:
    kinds = [kind] if kind else ["kg_build", "kg_communities", "kg_cq", "kg_hybrid"]
    rows = db.scalars(select(TestRun).where(TestRun.kind.in_(kinds)).order_by(TestRun.id.desc()).limit(limit))
    return [{"id": r.id, "kind": r.kind, "title": r.title, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/runs/{run_id}")
def kg_run(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or not r.kind.startswith("kg_"):
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"id": r.id, "kind": r.kind, "title": r.title, "created_at": r.created_at.isoformat()} | (r.result or {})
