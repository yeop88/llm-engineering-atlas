"""문서 검색 평가: 평가 세트 만들기(LLM 질문 생성 · 문장 추출) 와 정답 판정.

정답은 두 단계로 본다.
- 문서 단위: 검색 결과 청크가 정답 문서(doc_ids)에 속하는가 — 청크 세트가 달라도 그대로 쓸 수 있다.
- 근거 단위: 검색 결과 청크가 근거 문장(evidence)을 담고 있는가 — 문자 n-gram 포함률로 판정해
  청킹 방식(크기·겹침·경계)이 달라도 같은 기준으로 비교한다.
"""

import math
import random
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Chunk, Document
from app.rag.korean import split_sentences
from app.services import llm, stats
from app.services.jobs import Job, JobCancelled

GRAM = 4
EVIDENCE_HIT = 0.6  # 근거 문장의 n-gram 중 이 비율 이상이 청크에 있으면 '근거를 담은 청크'
_ws = re.compile(r"\s+")


# ── 근거 판정 ───────────────────────────────────────────────────────────────
def grams(text: str, n: int = GRAM) -> set[str]:
    t = _ws.sub("", text.lower())
    return {t[i : i + n] for i in range(max(1, len(t) - n + 1))} if t else set()


def coverage(evidence: set[str], chunk: set[str]) -> float:
    return len(evidence & chunk) / len(evidence) if evidence else 0.0


def contains_evidence(chunk_text: str, evidence: str) -> bool:
    return coverage(grams(evidence), grams(chunk_text)) >= EVIDENCE_HIT


def lexical_overlap(a: str, b: str) -> float:
    """질문과 근거의 글자 3-gram 자카드 — 높을수록 키워드 검색에 쉬운 질문."""
    ga, gb = grams(a, 3), grams(b, 3)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


# ── 지문 고르기 ─────────────────────────────────────────────────────────────
def sample_passages(db: Session, chunk_set_id: int, n: int, min_chars: int = 200, seed: int = 0) -> list[dict[str, Any]]:
    """문서마다 골고루(라운드 로빈) 무작위로 청크를 고른다."""
    rows = db.execute(
        select(Chunk.id, Chunk.document_id, Chunk.text, Document.filename, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.chunk_set_id == chunk_set_id)
    ).all()
    by_doc: dict[int, list] = defaultdict(list)
    for r in rows:
        if len(r.text) >= min_chars:
            by_doc[r.document_id].append(r)
    rng = random.Random(seed)
    for v in by_doc.values():
        rng.shuffle(v)
    docs = list(by_doc)
    rng.shuffle(docs)
    out: list[dict[str, Any]] = []
    while len(out) < n and any(by_doc[d] for d in docs):
        for d in docs:
            if by_doc[d] and len(out) < n:
                r = by_doc[d].pop()
                out.append({"chunk_id": r.id, "document_id": r.document_id, "text": r.text, "filename": r.filename, "title": r.title})
    return out


# ── 생성: 문장 추출 (LLM 없음) ──────────────────────────────────────────────
_HANGUL = re.compile(r"[가-힣]")
_ENDING = re.compile(r"(다|요|음|함|임|됨|것)[.!?]?$")


def sentence_quality(s: str) -> int:
    """0 = 표 조각·띄어 쓴 제목 같은 잡음, 1 = 글다운 문장, 2 = 서술어로 끝나는 완결 문장."""
    t = s.strip()
    chars = t.replace(" ", "")
    if not (20 <= len(t) <= 200) or not chars:
        return 0
    words = t.split()
    if len(_HANGUL.findall(chars)) / len(chars) < 0.5 or sum(map(len, words)) / len(words) < 2 or len(words) < 4:
        return 0  # 숫자·기호 위주 표 행, "번 역 자 문 위 원 회" 처럼 글자마다 띄운 제목
    return 2 if _ENDING.search(t) else 1


def from_sentences(passages: list[dict[str, Any]], seed: int = 0) -> list[dict[str, Any]]:
    """지문에서 한 문장을 골라 그대로 질문으로 쓴다. 단어가 그대로 겹쳐 쉬운 기준선이며 파이프라인 점검용이다."""
    rng = random.Random(seed)
    items = []
    for p in passages:
        scored = [(sentence_quality(s), s) for s in split_sentences(p["text"])]
        best = max((q for q, _ in scored), default=0)
        if best == 0:
            continue
        s = rng.choice([s for q, s in scored if q == best])
        items.append(_item(p, s, s, "sentence"))
    return items


def _item(p: dict[str, Any], query: str, evidence: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "query": query.strip(),
        "doc_ids": [p["document_id"]],
        "evidence": evidence.strip(),
        "source_chunk_id": p["chunk_id"],
        "filename": p["filename"],
        "type": kind,
        **extra,
    }


# ── 생성: LLM ───────────────────────────────────────────────────────────────
STYLES = {
    "fact": "지문의 사실을 묻는 질문. 지문의 핵심 단어를 써도 된다.",
    "paraphrase": "지문과 다른 단어·표현으로 같은 내용을 묻는 질문. 지문의 명사·동사를 그대로 쓰지 말 것.",
    "situation": "실제 사용자가 자기 상황을 설명하며 묻는 질문 (예: '입사 8개월인데 휴가가 며칠인가요?'). 지문 표현을 베끼지 말 것.",
}
SYSTEM = (
    "당신은 한국어 문서 검색 시스템을 평가하기 위한 질문을 만듭니다. "
    "주어진 지문만으로 답할 수 있고, 지문을 보지 않은 사람이 검색창에 입력할 법한 자연스러운 질문을 만드세요. "
    "반드시 JSON 만 출력합니다."
)


def _prompt(p: dict[str, Any], styles: list[str]) -> str:
    wanted = "\n".join(f"{i + 1}. {STYLES[s]} (type: {s})" for i, s in enumerate(styles))
    return f"""문서: {p["title"] or p["filename"]}
지문:
<<<
{p["text"][:4000]}
>>>

아래 유형마다 질문을 하나씩 만드세요.
{wanted}

규칙:
- 질문만 읽고도 무엇을 묻는지 알 수 있어야 합니다. "이 문서", "위 지문", "본문에서" 같은 표현을 쓰지 마세요.
- 답이 지문 안에 있어야 합니다.
- evidence 에는 답이 들어 있는 지문의 문장을 **그대로 복사**하세요 (한두 문장).
- 지문이 목차·표 조각·서명란처럼 질문을 만들 수 없는 내용이면 빈 배열을 돌려주세요.

출력 형식: {{"questions": [{{"type": "...", "question": "...", "evidence": "..."}}]}}"""


def _fix_evidence(evidence: str, passage: str) -> tuple[str, bool]:
    """LLM 이 근거를 조금 바꿔 적었으면 지문에서 가장 많이 겹치는 문장으로 바꾼다."""
    pg = grams(passage)
    if evidence and coverage(grams(evidence), pg) >= 0.9:
        return evidence, True
    sents = split_sentences(passage) or [passage]
    eg = grams(evidence, 3)  # 표현이 조금 바뀌어도 찾도록 짧은 n-gram
    best = max(sents, key=lambda s: coverage(eg, grams(s, 3)) if eg else 0)
    return (best, False) if eg and coverage(eg, grams(best, 3)) >= 0.3 else (passage, False)


def from_llm(
    cfg: llm.LLMConfig, passages: list[dict[str, Any]], styles: list[str], job: Job | None = None, concurrency: int = 4
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"calls": 0, "failed": 0, "empty": 0, "input_tokens": 0, "output_tokens": 0, "evidence_fixed": 0, "errors": []}
    lock = threading.Lock()

    def one(p: dict[str, Any]) -> list[dict[str, Any]]:
        obj, res = llm.chat_json(cfg, SYSTEM, _prompt(p, styles), max_tokens=1500, temperature=0.5)
        qs = obj.get("questions", []) if isinstance(obj, dict) else obj if isinstance(obj, list) else []
        out = []
        for q in qs:
            if not isinstance(q, dict) or not str(q.get("question", "")).strip():
                continue
            ev, exact = _fix_evidence(str(q.get("evidence", "")), p["text"])
            kind = q.get("type") if q.get("type") in STYLES else "fact"
            out.append(_item(p, str(q["question"]), ev, kind, evidence_exact=exact))
        with lock:
            stats["calls"] += 1
            stats["input_tokens"] += res["usage"].get("input_tokens") or 0
            stats["output_tokens"] += res["usage"].get("output_tokens") or 0
        return out

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(one, p): p for p in passages}
        for fut in as_completed(futures):
            done += 1
            try:
                got = fut.result()
                if not got:
                    stats["empty"] += 1
                items.extend(got)
            except Exception as exc:
                stats["failed"] += 1
                if len(stats["errors"]) < 5:
                    stats["errors"].append(f"{type(exc).__name__}: {str(exc)[:200]}")
                if isinstance(exc, llm.LLMError) and stats["failed"] >= 3 and not items:
                    for f in futures:
                        f.cancel()  # 설정 오류로 계속 실패하면 일찍 멈춘다
                    raise
            if job:
                job.update(0.1 + 0.85 * done / len(passages), f"질문 생성 {done}/{len(passages)} (질문 {len(items)}개)")
    stats["evidence_fixed"] = sum(1 for it in items if not it.get("evidence_exact", True))
    order = {p["chunk_id"]: i for i, p in enumerate(passages)}  # 병렬 완료 순서와 상관없이 지문 순서로
    items.sort(key=lambda it: (order.get(it["source_chunk_id"], 0), list(STYLES).index(it["type"])))
    return items, stats


# ── 마무리 ──────────────────────────────────────────────────────────────────
def finalize(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """같은 질문 제거, id 부여, 통계."""
    seen, out = set(), []
    for it in items:
        key = _ws.sub(" ", it["query"].strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    for i, it in enumerate(out, 1):
        it["id"] = f"q{i}"
        if it.get("evidence"):
            it["lexical_overlap"] = round(lexical_overlap(it["query"], it["evidence"]), 3)
    by_type: dict[str, int] = defaultdict(int)
    for it in out:
        by_type[it.get("type") or "manual"] += 1
    ov = [it["lexical_overlap"] for it in out if "lexical_overlap" in it]
    return out, {
        "n": len(out),
        "documents": len({d for it in out for d in it["doc_ids"]}),
        "by_type": dict(by_type),
        "with_evidence": sum(1 for it in out if it.get("evidence")),
        "lexical_overlap": round(sum(ov) / len(ov), 3) if ov else None,
        "duplicates_removed": len(items) - len(out),
    }


# ── 평가 실행 ───────────────────────────────────────────────────────────────
K_VALUES = (1, 3, 5, 10)
PRIMARY = "ndcg@10"


def judge(results: list[dict[str, Any]], item: dict[str, Any], ev_grams: set[str] | None) -> dict[str, Any]:
    """검색 결과(순위순 청크) → 정답 순위. 근거 문장이 있으면 근거를 담은 첫 청크, 없으면 정답 문서의 첫 청크."""
    docs = set(item["doc_ids"])
    target_rank = doc_rank = None
    seen_docs: list[int] = []
    for i, r in enumerate(results, 1):
        if r["document_id"] not in seen_docs:
            seen_docs.append(r["document_id"])
        if doc_rank is None and r["document_id"] in docs:
            doc_rank = len(seen_docs)  # 문서 단위 순위 (같은 문서의 청크 여러 개는 한 번만 센다)
        if target_rank is None:
            hit = coverage(ev_grams, grams(r["text"])) >= EVIDENCE_HIT if ev_grams else r["document_id"] in docs
            if hit:
                target_rank = i
    found_docs = len(docs & set(seen_docs[:5]))
    return {"rank": target_rank, "doc_rank": doc_rank, "doc_recall@5": found_docs / len(docs)}


def query_metrics(j: dict[str, Any]) -> dict[str, float]:
    r = j["rank"]
    m = {f"hit@{k}": float(r is not None and r <= k) for k in K_VALUES}
    m["mrr@10"] = 1.0 / r if r is not None and r <= 10 else 0.0
    m["ndcg@10"] = 1.0 / math.log2(r + 1) if r is not None and r <= 10 else 0.0
    m["doc_mrr@10"] = 1.0 / j["doc_rank"] if j["doc_rank"] is not None and j["doc_rank"] <= 10 else 0.0
    m["doc_recall@5"] = j["doc_recall@5"]
    return m


def run_eval(search_fn: Any, items: list[dict[str, Any]], configs: list[dict[str, Any]], job: Job | None = None) -> dict[str, Any]:
    """configs 마다 모든 질문을 검색하고 지표 · 95% 구간 · 1위와의 짝지은 비교 · 질문 유형별 지표를 낸다.
    search_fn(query, cfg) → service.search 결과 (테스트에서 바꿔 끼울 수 있게 주입)."""
    ev = [grams(it["evidence"]) if it.get("evidence") else None for it in items]
    total = len(items) * len(configs)
    out = []
    step = 0
    for ci, cfg in enumerate(configs):
        entry: dict[str, Any] = {"label": cfg.get("label") or f"설정 {ci + 1}", "config": cfg}
        per_q: list[dict[str, Any]] = []
        lat: list[float] = []
        try:
            for qi, it in enumerate(items):
                step += 1
                if job and (qi % 5 == 0 or qi == len(items) - 1):
                    job.update(step / total * 0.97, f"[{ci + 1}/{len(configs)}] {entry['label']} — 질문 {qi + 1}/{len(items)}")
                res = search_fn(it["query"], cfg)
                lat.append(res.get("total_ms") or 0.0)
                j = judge(res["results"], it, ev[qi])
                top = res["results"][0] if res["results"] else None
                per_q.append(j | query_metrics(j) | {"top1": {"filename": top["filename"], "text": top["text"][:160]} if top else None})
        except JobCancelled:
            raise
        except Exception as exc:  # 인덱스 미준비·저장소 연결 실패 등은 그 설정만 실패로
            entry |= {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            out.append(entry)
            step = (ci + 1) * len(items)
            continue
        metric_names = list(per_q[0]) if per_q else []
        metric_names = [m for m in metric_names if m not in ("rank", "doc_rank", "top1")]
        entry["status"] = "ok"
        entry["metrics"] = {m: round(sum(q[m] for q in per_q) / len(per_q), 4) for m in metric_names}
        entry["ci"] = {m: stats.mean_ci([q[m] for q in per_q]) for m in (PRIMARY, "hit@5", "mrr@10")}
        lat_sorted = sorted(lat)
        entry["latency_ms"] = {"mean": round(sum(lat) / len(lat), 1), "p95": round(lat_sorted[min(len(lat) - 1, int(0.95 * len(lat)))], 1)}
        by_type: dict[str, list[float]] = defaultdict(list)
        for it, q in zip(items, per_q, strict=True):
            by_type[it.get("type") or "manual"].append(q[PRIMARY])
        entry["by_type"] = {t: {"n": len(v), PRIMARY: round(sum(v) / len(v), 4)} for t, v in by_type.items()}
        entry["per_query"] = per_q
        out.append(entry)

    ok = sorted([e for e in out if e["status"] == "ok"], key=lambda e: -e["metrics"][PRIMARY])
    if len(ok) > 1:
        best = [q[PRIMARY] for q in ok[0]["per_query"]]
        for e in ok[1:]:
            e["vs_best"] = {"metric": PRIMARY, "against": ok[0]["label"], **stats.paired_mean([q[PRIMARY] for q in e["per_query"]], best)}
    results = ok + [e for e in out if e["status"] != "ok"]
    # 질문별 비교표: 설정마다 정답 순위만 (전체 per_query 는 결과에서 빼서 크기를 줄인다)
    queries = [
        {"id": it["id"], "query": it["query"], "type": it.get("type"), "filename": it.get("filename"),
         "ranks": [e["per_query"][qi]["rank"] for e in ok],
         "top1": [e["per_query"][qi]["top1"] for e in ok]}
        for qi, it in enumerate(items)
    ]  # fmt: skip
    for e in ok:
        del e["per_query"]
    return {
        "primary_metric": PRIMARY,
        "n_queries": len(items),
        "results": results,
        "queries": queries,
        "bootstrap": {"n": stats.N_BOOT, "level": stats.LEVEL},
    }
