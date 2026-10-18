"""흐름 실행기: 맵의 단계들을 서비스 순서대로 이어 한 질문을 처리하고, 단계마다 무엇을 했는지 · 얼마나 걸렸는지 남긴다.

왜 이렇게 만들었나
- 단계는 각자 화면에서 따로 검증했다. 마지막으로 '이어 붙였을 때' 품질 · 지연이 어떻게 되는지를 봐야
  어느 단계가 병목이고 어느 단계가 품질을 올리는지 알 수 있다. 그래서 같은 질문(평가 세트)을 여러 연결
  방식(부분 연결 · 전체 연결)으로 돌려 나란히 비교한다.
- 아직 만들지 않은 단계(라우팅 · 증류 · 양자화 · 에이전트 · 강화학습)는 흐름에서 빼지 않고 '기본 동작'으로
  지나가게 했다(모든 질문 → 기본 LLM). 흐름 전체를 지금 돌려 볼 수 있고, 단계를 구현하면 그 자리만 바꾸면 된다.
- 검색 부분(4 향상 → 1 임베딩 → 2 검색 → 3 리랭킹)은 run_search 한 번으로 실행하고, 단계별 시간은 검색이
  돌려주는 timings_ms 를 단계에 나눠 담는다. 단계마다 따로 부르면 검색 경로가 둘이 되어 결과가 어긋날 수 있다.
"""

import time
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm, stats
from app.core.jobs import JobCancelled
from app.pipeline.search import ENHANCE_LABEL, run_search
from app.stages import registry
from app.stages.rag import answer, evaluation
from app.stages.routing import routers

RUN, OFF, DEFAULT = "run", "off", "default"  # 실행 · 꺼 둠 · 미구현이라 기본 동작

# 서비스 순서. timing 은 검색 timings_ms 의 어느 항목이 이 단계의 시간인지.
STEPS: list[dict[str, Any]] = [
    {"key": "search_lab", "title": "질의 다듬기", "timing": ("llm",)},
    {"key": "embedding", "title": "질의 임베딩", "timing": ("load", "embed")},
    {"key": "rag", "title": "검색", "timing": ("vector_search", "bm25")},
    {"key": "rerank", "title": "재정렬", "timing": ("rerank_load", "rerank")},
    {"key": "routing", "title": "난이도 분류", "timing": ()},
    {"key": "model", "title": "답변 모델 선택", "timing": ()},
    {"key": "answer", "title": "답변 · 근거 검증", "timing": ()},
]


def _stage(key: str) -> dict[str, str]:
    if key == "model":  # 쉬운 질문 → 7 증류 · 양자화 / 어려운 질문 → 8 에이전트 · 강화학습: 두 갈래를 한 칸에 보인다
        return {"no": "7·8", "stage": "소형 모델 / 에이전트 LLM"}
    if key == "answer":
        return {"no": registry.BY_KEY["rag"].no, "stage": "RAG 답변 생성"}
    s = registry.BY_KEY[key]
    return {"no": s.no, "stage": s.title}


def _search_cfg(fc: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(fc["config"])
    cfg["top_k"] = max(int(cfg.get("top_k") or 10), int(fc.get("context_top") or 5))
    return cfg


def _route(db: Session, question: str, fc: dict[str, Any], lcfg: llm.LLMConfig | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """6 라우팅. → (판단, 미리 한 검색 결과). 확신도 라우터는 쉬운 경로로 먼저 검색해야 판단할 수 있으므로,
    쉬움으로 판단되면 그 검색을 그대로 이어 쓴다(같은 검색을 두 번 하지 않게). 어려움이면 그 검색은 버려진 비용이다."""
    rc = fc["routing"]
    t = time.perf_counter()
    pre = None
    if rc["router"] == "rule":
        path, reason = routers.route_rule(question, rc.get("rule_max_chars") or 45)
    elif rc["router"] == "llm":
        if lcfg is None:
            raise llm.LLMError("LLM 판단 라우터에는 LLM 이 필요합니다.")
        path, reason, _ = routers.route_llm(lcfg, question)
    else:
        pre = run_search(db, question, _search_cfg(fc))
        path, reason = routers.route_confidence(pre["results"], rc.get("threshold", 0.05))
    ms = (time.perf_counter() - t) * 1000
    return {"router": rc["router"], "path": path, "reason": reason, "ms": round(ms, 1)}, (pre if path == routers.EASY else None)


def run(db: Session, question: str, fc: dict[str, Any], lcfg: llm.LLMConfig | None, evidence: str = "") -> dict[str, Any]:
    """fc: FlowConfig dict — {"config": SearchConfig, "answer", "context_top", "max_context_chars", "max_tokens", "model", "routing"}."""
    started = time.perf_counter()
    route, pre = (None, None)
    if fc.get("routing"):
        route, pre = _route(db, question, fc, lcfg)
        if route["path"] == routers.HARD:
            fc = fc["routing"]["hard"] | {"label": fc.get("label", "")}
    cfg = _search_cfg(fc)
    res = pre if pre is not None else run_search(db, question, cfg)
    t = res.get("timings_ms") or {}
    tech = (cfg.get("enhance") or {}).get("technique") or "none"
    steps: dict[str, dict[str, Any]] = {}

    def put(key: str, status: str, detail: str, ms: float | None = None) -> None:
        spec = next(s for s in STEPS if s["key"] == key)
        if ms is None:
            ms = sum(t.get(k, 0.0) for k in spec["timing"])
        steps[key] = {"key": key, "title": spec["title"], **_stage(key), "status": status, "ms": round(ms, 1), "detail": detail}

    if tech != "none":
        variants = [v["text"] for v in (res.get("enhance") or {}).get("variants", []) if v["name"] != "original"]
        put("search_lab", RUN, f"{ENHANCE_LABEL[tech]}: " + " / ".join(v[:60] for v in variants))
    else:
        put("search_lab", OFF, "끔 — 원 질의 그대로 검색")
    mode = cfg.get("mode", "hybrid")
    put("embedding", RUN if mode != "bm25" else OFF, "의미 검색용 질의 벡터" if mode != "bm25" else "BM25 만 사용 — 임베딩 없음")
    put(
        "rag",
        RUN,
        f"{({'dense': '의미', 'bm25': 'BM25', 'hybrid': '하이브리드'})[mode]} 검색 · 후보 {sum((res.get('candidates') or {}).values())}개",
    )
    put("rerank", RUN if res.get("reranked") else OFF, "리랭커로 후보 재정렬" if res.get("reranked") else "끔")
    if route:
        # 확신도 라우터의 시간에는 판단용 검색이 들어 있다. 쉬움이면 그 검색을 이어 썼으므로 검색 단계와 겹치지 않게 0 으로 둔다.
        r_ms = 0.0 if (route["router"] == "confidence" and route["path"] == routers.EASY) else route["ms"]
        where = "쉬움 → 빠른 경로" if route["path"] == routers.EASY else "어려움 → 전체 경로"
        put("routing", RUN, f"{routers.ROUTERS[route['router']]}: {where} — {route['reason']}", r_ms)
    else:
        put("routing", OFF, "끔 — 모든 질문을 한 경로로 보냄", 0.0)
    # 7 · 8 은 예정 단계: 경로에 모델을 지정하지 않으면 기본 LLM 으로 답한다. 7 소형 모델이 생기면 쉬운 경로에 지정한다.
    if fc.get("answer") and lcfg is not None and fc.get("model"):
        lcfg = llm.resolve(lcfg.provider, fc["model"])
        put("model", RUN, f"이 경로의 모델: {lcfg.model}", 0.0)
    else:
        put(
            "model",
            DEFAULT if fc.get("answer") else OFF,
            f"예정 단계 — 기본 LLM({lcfg.model})" if (fc.get("answer") and lcfg) else "답변 안 함",
            0.0,
        )

    out: dict[str, Any] = {
        "question": question,
        "results": res["results"][: int(fc.get("context_top") or 5)],
        "search": res,
        "route": route,
    }
    if fc.get("answer"):
        if lcfg is None:
            raise llm.LLMError("답변 단계에는 LLM 이 필요합니다.")
        t0 = time.perf_counter()
        context, sources = answer.build_context(res["results"][: int(fc.get("context_top") or 5)], int(fc.get("max_context_chars") or 6000))
        gen = llm.chat(
            lcfg, answer.SYSTEM, answer.user_prompt(question, context), max_tokens=int(fc.get("max_tokens") or 500), temperature=0.1
        )
        check = answer.verify_lexical(gen["text"], sources)
        with_ev = [i + 1 for i, s in enumerate(sources) if evidence and evaluation.contains_evidence(s["text"], evidence)]
        ratio = check["supported_ratio"]
        put("answer", RUN, "근거 없음 · 거절" if check["refused"] else f"근거 있는 문장 {ratio * 100:.0f}%" if ratio is not None else "검증할 문장 없음",
            (time.perf_counter() - t0) * 1000)  # fmt: skip
        out["answer"] = {
            "text": gen["text"], "sources": sources, "verify": check, "output_tokens": gen["usage"].get("output_tokens"), "seconds": gen["seconds"],
            "refused": check["refused"], "supported_ratio": ratio, "invalid_citations": check["invalid_citations"], "cited": check["cited_sources"],
            "evidence_retrieved": bool(with_ev) if evidence else None,
            "evidence_cited": bool(set(with_ev) & set(check["cited_sources"])) if evidence else None,
        }  # fmt: skip
    else:
        put("answer", OFF, "검색까지만", 0.0)
    out["steps"] = [steps[s["key"]] for s in STEPS]
    out["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out


def _agg(sts: list[str]) -> str | None:
    if not sts:
        return None
    return sts[0] if len(set(sts)) == 1 else "partial"  # 질문에 따라 실행 · 꺼짐이 섞임(라우팅)


def evaluate(db: Session, items: list[dict[str, Any]], flows: list[dict[str, Any]], lcfg: llm.LLMConfig | None, job=None) -> dict[str, Any]:
    """같은 질문들을 여러 연결 방식으로 처리해 검색 품질 · 답변 품질 · 단계별 지연을 나란히 비교한다.
    첫 번째 연결 방식을 기준으로 짝지은 비교를 한다 — '부분 연결에 단계를 더하면 좋아지는가'를 보려는 것이라 기준이 고정돼야 한다."""
    ev = [evaluation.grams(it["evidence"]) if it.get("evidence") else None for it in items]
    total = len(items) * len(flows)
    out = []
    for fi, fc in enumerate(flows):
        label = fc.get("label") or f"연결 {fi + 1}"
        per_q, rows, lat, step_ms = [], [], [], {s["key"]: [] for s in STEPS}
        # 라우팅을 켜면 질문마다 실행되는 단계가 달라진다 — 마지막 질문의 상태가 아니라 실행 비율을 센다
        status: dict[str, list[str]] = {s["key"]: [] for s in STEPS}
        hard = 0
        try:
            for qi, it in enumerate(items):
                if job:
                    job.update((fi * len(items) + qi) / total * 0.97, f"[{fi + 1}/{len(flows)}] {label} — 질문 {qi + 1}/{len(items)}")
                r = run(db, it["query"], fc, lcfg, it.get("evidence", ""))
                j = evaluation.judge(r["search"]["results"], it, ev[qi])
                per_q.append(j | evaluation.query_metrics(j))
                lat.append(r["total_ms"])
                for s in r["steps"]:
                    step_ms[s["key"]].append(s["ms"])
                    status[s["key"]].append(s["status"])
                hard += bool(r.get("route") and r["route"]["path"] == routers.HARD)
                if "answer" in r:
                    rows.append(r["answer"] | {"query": it["query"]})
        except JobCancelled:
            raise
        except Exception as exc:  # 한 연결 방식이 실패해도(LLM 끊김 등) 나머지는 비교한다
            out.append({"label": label, "flow": fc, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        names = [m for m in per_q[0] if m not in ("rank", "doc_rank")]
        srt = sorted(lat)
        entry = {
            "label": label, "flow": fc, "status": "ok", "n": len(items),
            "metrics": {m: round(sum(q[m] for q in per_q) / len(per_q), 4) for m in names},
            "ci": {evaluation.PRIMARY: stats.mean_ci([q[evaluation.PRIMARY] for q in per_q])},
            "latency_ms": {"mean": round(sum(lat) / len(lat), 1), "p95": round(srt[min(len(srt) - 1, int(0.95 * len(srt)))], 1)},
            "steps": [{"key": k, "status": _agg(status[k]), "run_rate": round(status[k].count(RUN) / len(status[k]), 3) if status[k] else 0.0,
                       "mean_ms": round(sum(v) / len(v), 1) if v else 0.0} for k, v in step_ms.items()],
            "hard_rate": round(hard / len(items), 3) if fc.get("routing") else None,
            "answer": answer.summarize_eval(rows) if rows else None,
            "per_query": [q[evaluation.PRIMARY] for q in per_q],
        }  # fmt: skip
        out.append(entry)
    ok = [e for e in out if e["status"] == "ok"]
    if ok:
        base = ok[0]
        for e in ok[1:]:
            e["vs_first"] = {"metric": evaluation.PRIMARY, "against": base["label"], **stats.paired_mean(e["per_query"], base["per_query"])}
    for e in ok:
        e.pop("per_query")
    return {"n_queries": len(items), "results": out, "steps": [{"key": s["key"], "title": s["title"], **_stage(s["key"])} for s in STEPS]}
