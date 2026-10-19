"""답변 근거 검증 방식: 글자(기본) · 의미(임베딩 유사도) · 혼합, 그리고 사람 판정과의 일치도.

왜 만들었나
- 글자 검증(인용 근거와의 글자 3-gram 포함률)은 숫자 · 고유명사를 잘 잡지만, 근거를 바꿔 말한 문장을 '근거 없음'으로 본다.
  실측에서 에이전트 답변의 문장 근거율이 38% 로 나왔는데, 읽어 보면 맞는 요약이 많았다. 보상 함수(8b)도 이 검증을 써서
  같이 왜곡된다.
- 의미 검증: 답변 문장과 '인용한 근거의 문장들' 중 가장 가까운 것의 코사인 유사도. 바꿔 말해도 잡지만 숫자 하나가 틀린
  문장도 비슷하다고 볼 수 있다. 그래서 혼합(글자 또는 의미 중 하나라도 통과)을 함께 둔다.
- 어느 쪽이 맞는지는 감으로 정하지 않고 사람 판정(라벨)과의 일치도(정확도 · F1 · 카파)로 고른다. 기준값(유사도 문턱)도
  라벨로 훑어 정한다. 그 전까지 의미 문턱은 잠정값이다.
"""

import time
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.korean import split_sentences

METHODS = {"lexical": "글자 겹침", "semantic": "의미 유사도", "hybrid": "글자 또는 의미", "llm": "LLM 판정"}


def _model():
    """검증용 임베딩 모델. 카탈로그에 있는 모델이어야 한다(설정 VERIFY_MODEL)."""
    from sqlalchemy import select

    from app.core.db import EmbeddingModel, SessionLocal
    from app.stages.embedding.model_manager import ModelSpec, get_manager

    with SessionLocal() as db:
        row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == get_settings().verify_model))
        if row is None:
            raise ValueError(f"검증용 임베딩 모델이 카탈로그에 없습니다: {get_settings().verify_model}")
        spec = ModelSpec.from_row(row)
    manager = get_manager()
    return manager, manager.get(spec)


def semantic_scores(sentences: list[str], cited: list[list[int]], sources: list[dict[str, Any]]) -> list[float | None]:
    """문장마다: 인용한 근거들의 문장 중 가장 가까운 것과의 코사인. 인용이 없으면 None.
    근거를 통째로 한 벡터로 만들지 않고 문장으로 나누는 이유: 근거 청크는 길어서 한 벡터로는 답변 한 문장과의 유사도가 희석된다."""
    if not sentences:
        return []
    manager, lm = _model()
    src_sents = [split_sentences(s["text"]) or [s["text"]] for s in sources]
    flat = [x for ss in src_sents for x in ss]
    owner = [i for i, ss in enumerate(src_sents) for _ in ss]
    if not flat:
        return [None] * len(sentences)
    # 문장 대 문장 유사도라 질의/문서 프롬프트가 아닌 일반(plain) 인코딩 — 둘 다 같은 종류의 글이다
    a = manager.encode(lm, sentences, "plain").embeddings
    b = manager.encode(lm, flat, "plain").embeddings
    sim = a @ b.T
    out: list[float | None] = []
    for i, cs in enumerate(cited):
        cols = [k for k, o in enumerate(owner) if (o + 1) in cs]
        out.append(round(float(np.max(sim[i, cols])), 4) if cols else None)
    return out


def relevance_scores(question: str, sentences: list[str]) -> list[float]:
    """문장마다 질문과의 코사인. 질문은 '질의', 문장은 '문서' 프롬프트로 인코딩한다 — 검색에서 질문이 근거를 찾는 것과 같은 관계라서.
    인용 표시([1])는 빼고 잰다(숫자 기호가 유사도를 흐리지 않게)."""
    if not sentences:
        return []
    import re

    manager, lm = _model()
    q = manager.encode(lm, [question], "query").embeddings
    s = manager.encode(lm, [re.sub(r"\[\d+(?:[,，]\s*\d+)*\]", "", x).strip() or x for x in sentences], "document").embeddings
    return [round(float(v), 4) for v in (s @ q[0])]


def apply_relevance(check: dict[str, Any], question: str) -> dict[str, Any]:
    """근거 검증 결과에 질문 관련성을 더한다. 문장의 근거 상태(status)는 그대로 두고 off_topic 표시만 더한다 —
    '근거에 있는가'와 '질문에 답하는가'는 다른 질문이라 섞으면 어느 쪽이 문제인지 알 수 없다."""
    s = get_settings()
    claims = [x for x in check["sentences"] if x["status"] != "refusal"]
    if not claims:
        return check | {"relevant_ratio": None, "off_topic": 0}
    t = time.perf_counter()
    for x, sc in zip(claims, relevance_scores(question, [x["text"] for x in claims]), strict=True):
        x["relevance"] = sc
        x["off_topic"] = sc < s.verify_relevance_ok
    off = sum(1 for x in claims if x["off_topic"])
    return check | {"relevant_ratio": round(1 - off / len(claims), 3), "off_topic": off,
                    "relevance_threshold": s.verify_relevance_ok, "relevance_seconds": round(time.perf_counter() - t, 2)}  # fmt: skip


def apply(check: dict[str, Any], sources: list[dict[str, Any]], method: str) -> dict[str, Any]:
    """글자 검증 결과(answer.verify_lexical)에 의미 점수를 더하고 방식에 맞게 문장 상태 · 근거율을 다시 매긴다."""
    if method == "lexical":
        return check | {"method": "lexical"}
    s = get_settings()
    sents = check["sentences"]
    claims = [x for x in sents if x["status"] not in ("refusal", "uncited")]
    t = time.perf_counter()
    scores = semantic_scores([x["text"] for x in claims], [x["citations"] for x in claims], sources)
    for x, sc in zip(claims, scores, strict=True):
        x["semantic"] = sc
        sem_ok = sc is not None and sc >= s.verify_semantic_ok
        sem_weak = sc is not None and sc >= s.verify_semantic_weak
        lex = x["status"]
        if method == "semantic":
            x["status"] = "supported" if sem_ok else "weak" if sem_weak else "unsupported"
        else:  # hybrid: 글자로 이미 확인됐거나 의미로 통과하면 근거 있음
            x["status"] = "supported" if (lex == "supported" or sem_ok) else "weak" if (lex == "weak" or sem_weak) else "unsupported"
    real = [x for x in sents if x["status"] != "refusal"]
    ok = sum(1 for x in real if x["status"] == "supported")
    return check | {"sentences": sents, "supported_ratio": round(ok / len(real), 3) if real else None, "method": method,
                    "semantic_seconds": round(time.perf_counter() - t, 2)}  # fmt: skip


# ── 사람 판정과의 일치도 ─────────────────────────────────────────────────
def agreement(labels: list[bool], preds: list[bool]) -> dict[str, Any]:
    """정확도 · 정밀도 · 재현율 · F1(근거 있음 기준) · 코헨 카파(우연히 맞을 확률을 뺀 일치도)."""
    n = len(labels)
    if not n:
        return {"n": 0}
    tp = sum(1 for y, p in zip(labels, preds, strict=True) if y and p)
    tn = sum(1 for y, p in zip(labels, preds, strict=True) if not y and not p)
    fp = sum(1 for y, p in zip(labels, preds, strict=True) if not y and p)
    fn = n - tp - tn - fp
    acc = (tp + tn) / n
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    py, pp = sum(labels) / n, sum(preds) / n
    pe = py * pp + (1 - py) * (1 - pp)
    kappa = (acc - pe) / (1 - pe) if pe < 1 else 0.0
    return {"n": n, "accuracy": round(acc, 3), "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "kappa": round(kappa, 3),
            "tp": tp, "tn": tn, "fp": fp, "fn": fn}  # fmt: skip


def compare_methods(rows: list[dict[str, Any]], lexical_ok: float) -> dict[str, Any]:
    """라벨 붙은 문장들(row: label · lexical · semantic · llm)로 방식별 일치도와, 의미 문턱을 훑어 찾은 가장 좋은 값."""
    y = [bool(r["label"]) for r in rows]
    out: dict[str, Any] = {"lexical": agreement(y, [(r.get("lexical") or 0) >= lexical_ok for r in rows])}
    sem = [r for r in rows if r.get("semantic") is not None]
    if sem:
        ys = [bool(r["label"]) for r in sem]
        sweep = []
        for th in [round(x, 2) for x in np.arange(0.5, 0.96, 0.02)]:
            a = agreement(ys, [r["semantic"] >= th for r in sem])
            sweep.append({"threshold": th, "kappa": a["kappa"], "f1": a["f1"], "accuracy": a["accuracy"]})
        best = max(sweep, key=lambda x: (x["kappa"], x["f1"]))
        th = best["threshold"]
        out["semantic"] = agreement(ys, [r["semantic"] >= th for r in sem]) | {"threshold": th}
        out["hybrid"] = agreement(ys, [(r.get("lexical") or 0) >= lexical_ok or r["semantic"] >= th for r in sem]) | {"threshold": th}
        out["semantic_sweep"] = sweep
    judged = [r for r in rows if r.get("llm") is not None]
    if judged:
        out["llm"] = agreement([bool(r["label"]) for r in judged], [bool(r["llm"]) for r in judged])
    return out


def compare_relevance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """질문 관련성 라벨(row: relevant · relevance)로 질문-문장 유사도 기준을 훑어 가장 일치하는 값 + AUC(기준과 무관한 가름 능력)."""
    rows = [r for r in rows if r.get("relevance") is not None]
    if not rows:
        return {}
    y = [bool(r["relevant"]) for r in rows]
    sc = [float(r["relevance"]) for r in rows]
    pos, neg = [v for v, t in zip(sc, y, strict=True) if t], [v for v, t in zip(sc, y, strict=True) if not t]
    auc = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)) if pos and neg else None
    sweep = []
    for th in [round(x, 2) for x in np.arange(0.4, 0.91, 0.02)]:
        a = agreement(y, [v >= th for v in sc])
        sweep.append({"threshold": th, "kappa": a["kappa"], "f1": a["f1"], "accuracy": a["accuracy"]})
    best = max(sweep, key=lambda x: (x["kappa"], x["f1"]))
    cur = get_settings().verify_relevance_ok
    return {"relevance": agreement(y, [v >= best["threshold"] for v in sc]) | {"threshold": best["threshold"]},
            "relevance_current": agreement(y, [v >= cur for v in sc]) | {"threshold": cur},
            "relevance_auc": round(auc, 3) if auc is not None else None, "relevance_sweep": sweep}  # fmt: skip
