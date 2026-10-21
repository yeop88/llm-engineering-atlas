"""IP2 근거 기여 · IP3 탐침 · IP5 조종 · IP6 내부 신호 환각 탐지 — 같은 자료(질문 × 근거 있음 / 근거 뺌)로.

자료: 평가 세트의 답할 수 있는 질문마다 검색 근거를 두 벌 만든다 — '근거 있음'(정답 근거를 담은 청크 포함)과 '근거 뺌'(그 청크를 빼고
다음 순위로 채움). 같은 질문인데 답이 근거에 있고 없음만 다르게 해, 모델 안의 신호가 '답이 근거에 있나'를 아는지 본다.

- 기여(IP2): 근거를 하나씩 지우고 같은 답의 로그확률이 얼마나 떨어지나(지우기 기여) · 답 토큰이 근거마다 준 어텐션. 가장 크게 기여한
  근거가 답이 인용한 번호 · 정답 근거와 같은지 — 인용과 실제 기여가 다를 수 있다
- 탐침(IP3): 층마다 프롬프트 마지막 토큰의 은닉 상태로 '근거 있음/뺌'을 선형 분류(교차 검증 정확도) — 어느 층에서 알게 되나
- 조종(IP5): 그 층의 (근거 뺌 평균 − 근거 있음 평균) 방향을 생성 중에 더한다 — 세기별로 근거 뺌의 거절률(올라야 함)과 근거 있음의
  거절률(오르면 부작용)을 같은 자료로
- 환각 탐지(IP6): 거절하지 않은 답 중 '근거 뺌' 쪽(근거 없이 답함 = 환각) 을 내부 신호(평균 엔트로피 · 최소 확률 · 탐침 점수)와 밖의
  검증(글자 근거율)으로 얼마나 가려내나(AUROC) — 밖의 검증은 답이 끝난 뒤에야, 내부 신호는 생성 중에 얻는다
"""

from typing import Any

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score

from app.stages.interp import lm
from app.stages.rag import answer, evaluation


def pairs(items: list[dict[str, Any]], contexts: list[list[dict[str, Any]]], k: int = 4) -> list[dict[str, Any]]:
    """질문마다 (근거 있음, 근거 뺌). 정답 근거가 검색되지 않은 질문 · 방해 근거가 모자란 질문은 뺀다."""
    out = []
    for it, ctx in zip(items, contexts, strict=True):
        evs = evaluation.evidences_of(it)
        has = [any(evaluation.contains_evidence(r.get("text") or "", e) for e in evs) for r in ctx]
        if not any(has[:k]):
            continue
        without = [r for r, h in zip(ctx, has, strict=True) if not h][:k]
        if len(without) < k:
            continue
        with_ = ctx[:k]
        gold = next(i for i, h in enumerate(has[:k]) if h)
        out.append({"item": it, "with": with_, "without": without, "gold_index": gold})
    return out


def attribution(model: Any, tok: Any, p: dict[str, Any], max_new: int = 80) -> dict[str, Any]:
    q, ctx = p["item"]["query"], p["with"]
    ids, spans = lm.prompt_ids(tok, q, ctx)
    gen = lm.generate(model, tok, ids, max_new)
    full = lm.answer_logprob(model, tok, ids, gen["text"])
    drops = []
    for i in range(len(ctx)):
        ids_i, _ = lm.prompt_ids(tok, q, ctx[:i] + ctx[i + 1 :])
        drops.append(round(full - lm.answer_logprob(model, tok, ids_i, gen["text"]), 4))
    a_ids = tok(gen["text"], add_special_tokens=False)["input_ids"][:120]
    att = lm.attention_to_spans(model, ids, a_ids, spans)
    cited = answer.citations(gen["text"])
    top_drop = int(np.argmax(drops)) + 1 if drops else None
    valid_att = [a for a in att if a is not None]
    top_att = (att.index(max(valid_att)) + 1) if valid_att else None
    return {"query": q, "answer": gen["text"], "drops": drops, "attention": att, "cited": cited, "gold": p["gold_index"] + 1, "top_drop": top_drop,
            "top_attention": top_att, "drop_is_gold": top_drop == p["gold_index"] + 1, "drop_is_cited": bool(cited) and top_drop in cited,
            "cited_is_gold": (p["gold_index"] + 1) in cited}  # fmt: skip


def collect(
    model: Any, tok: Any, ps: list[dict[str, Any]], layers: list[int], max_new: int, progress=lambda f, m: None, steer=None
) -> list[dict[str, Any]]:
    """질문 × (있음 · 뺌) 마다 은닉 상태(층별) · 생성 · 내부 신호 · 밖의 검증."""
    rows = []
    for i, p in enumerate(ps):
        for kind in ("with", "without"):
            progress(i / max(1, len(ps)), f"{i + 1}/{len(ps)} · 근거 {'있음' if kind == 'with' else '뺌'}")
            ids, _ = lm.prompt_ids(tok, p["item"]["query"], p[kind])
            hs = lm.hidden_last(model, ids, layers)
            g = lm.generate(model, tok, ids, max_new, steer)
            _, used = answer.build_context(p[kind], 2500)
            v = answer.verify(g["text"], used)
            rows.append({"query": p["item"]["query"], "kind": kind, "hidden": hs, "answer": g["text"], "refused": bool(v.get("refused")),
                         "supported_ratio": v.get("supported_ratio"), **{k: g[k] for k in ("mean_entropy", "min_prob", "mean_logprob", "n_tokens")}})  # fmt: skip
    return rows


def probe(rows: list[dict[str, Any]], layers: list[int], folds: int = 5) -> dict[str, Any]:
    y = np.array([r["kind"] == "without" for r in rows], dtype=int)
    out = {}
    for li in layers:
        x = np.array([r["hidden"][li] for r in rows], dtype=np.float32)
        if len(set(y)) < 2 or len(y) < folds * 2:
            out[li] = None
            continue
        clf = LogisticRegression(max_iter=2000, C=0.5)
        out[li] = round(float(np.mean(cross_val_score(clf, x, y, cv=min(folds, int(min(np.bincount(y))))))), 4)
    best = max((li for li in out if out[li] is not None), key=lambda li: out[li], default=None)
    return {"by_layer": out, "best_layer": best, "best_acc": out.get(best) if best is not None else None, "n": len(rows)}


def probe_scores(rows: list[dict[str, Any]], layer: int) -> list[float]:
    """같은 층 탐침의 '근거 뺌' 확률 — 교차 적합(자기 자신을 맞히지 않게 두 갈래로 나눠 서로 예측)."""
    y = np.array([r["kind"] == "without" for r in rows], dtype=int)
    x = np.array([r["hidden"][layer] for r in rows], dtype=np.float32)
    s = np.zeros(len(rows))
    idx = np.arange(len(rows))
    # 질문(짝) 단위로 나눈다 — 자료는 '있음 · 뺌'이 번갈아 쌓여, 짝수 · 홀수 번째로 나누면 한 갈래에 한 종류만 남아 학습이 안 된다
    for part in ((idx // 2) % 2 == 0, (idx // 2) % 2 == 1):
        clf = LogisticRegression(max_iter=2000, C=0.5).fit(x[~part], y[~part])
        s[part] = clf.predict_proba(x[part])[:, 1]
    return s.tolist()


def direction(rows: list[dict[str, Any]], layer: int) -> torch.Tensor:
    a = np.array([r["hidden"][layer] for r in rows if r["kind"] == "without"], dtype=np.float32)
    b = np.array([r["hidden"][layer] for r in rows if r["kind"] == "with"], dtype=np.float32)
    d = a.mean(0) - b.mean(0)
    return torch.tensor(d / (np.linalg.norm(d) + 1e-12))


def refusal_rates(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    def rate(kind: str) -> float | None:
        rs = [r["refused"] for r in rows if r["kind"] == kind]
        return round(sum(rs) / len(rs), 4) if rs else None

    return {"without_refused": rate("without"), "with_refused": rate("with")}


def hallucination(rows: list[dict[str, Any]], probe_layer: int | None) -> dict[str, Any]:
    """거절하지 않은 답에서 '근거 뺌'(= 근거 없이 답함)을 가려내는 AUROC. 신호는 클수록 환각 쪽이 되게 방향을 맞춘다."""
    scores = probe_scores(rows, probe_layer) if probe_layer is not None else None
    sel = [i for i, r in enumerate(rows) if not r["refused"]]
    y = [int(rows[i]["kind"] == "without") for i in sel]
    if len(set(y)) < 2:
        return {"n": len(sel), "note": "거절하지 않은 답에 두 종류가 다 있어야 잴 수 있습니다", "auroc": {}}
    sig = {"평균 엔트로피": [rows[i]["mean_entropy"] or 0 for i in sel], "최소 확률(낮을수록)": [-(rows[i]["min_prob"] or 0) for i in sel],
           "밖의 검증: 근거율(낮을수록)": [-(rows[i]["supported_ratio"] or 0) for i in sel]}  # fmt: skip
    if scores is not None:
        sig[f"탐침 점수(층 {probe_layer})"] = [scores[i] for i in sel]
    return {"n": len(sel), "n_hallucinated": sum(y), "auroc": {k: round(float(roc_auc_score(y, v)), 4) for k, v in sig.items()}}
