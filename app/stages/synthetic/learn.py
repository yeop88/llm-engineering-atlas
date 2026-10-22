"""SD7 · SD8 학습 · 실제 데이터 평가: 실제만 · 실제 + 합성(거르기 전 · 후) · 합성만으로 질문 유형 분류기를 학습해 시험용 실제 질문으로 잰다.

맵 원칙 '평가는 실제 데이터로 — 합성 평가 점수를 믿지 않는다'를 숫자로 보이려고, 같은 분류기를 합성 시험 질문으로도 잰다.
합성 질문은 틀에서 나와 서로 닮았으므로 합성 시험 점수가 실제보다 높게 나오는 것이 보통이다 — 그 차이가 '믿지 않는' 이유다.
분류기는 글자 n-gram(2~4, 어절 경계) TF-IDF + 로지스틱 회귀(유형 불균형은 가중으로). 가벼워서 조건마다 몇 초 안에 끝난다.
"""

from collections import Counter
from typing import Any

from app.stages.synthetic.make import TYPES


def _fit(texts: list[str], labels: list[str]) -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    return make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
                         LogisticRegression(max_iter=3000, class_weight="balanced", C=4.0)).fit(texts, labels)  # fmt: skip


def score(model: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "acc": None, "macro_recall": None, "recall": {}}
    pred = model.predict([x["query"] for x in items])
    rec = {}
    for t in TYPES:
        idx = [i for i, x in enumerate(items) if x["type"] == t]
        if idx:
            rec[t] = round(sum(pred[i] == t for i in idx) / len(idx), 3)
    return {"n": len(items), "acc": round(sum(p == x["type"] for p, x in zip(pred, items, strict=True)) / len(items), 3),
            "macro_recall": round(sum(rec.values()) / len(rec), 3), "recall": rec}  # fmt: skip


def cv_recall(train: list[dict[str, Any]], folds: int = 4) -> dict[str, float]:
    """SD1 의 '못 맞히는 유형': 학습용 실제 질문만으로 접어 나눠 유형별 재현율(예시가 1~2건인 유형은 못 맞힌 것으로 나온다)."""
    hit: Counter = Counter()
    tot: Counter = Counter()
    for f in range(folds):
        tr = [x for i, x in enumerate(train) if i % folds != f]
        te = [x for i, x in enumerate(train) if i % folds == f]
        if len({x["type"] for x in tr}) < 2 or not te:
            continue
        m = _fit([x["query"] for x in tr], [x["type"] for x in tr])
        for x, p in zip(te, m.predict([x["query"] for x in te]), strict=True):
            tot[x["type"]] += 1
            hit[x["type"]] += p == x["type"]
    return {t: round(hit[t] / tot[t], 3) for t in tot}


def compare(train: list[dict[str, Any]], test: list[dict[str, Any]], syn_raw: list[dict[str, Any]], syn_clean: list[dict[str, Any]],
            syn_test: list[dict[str, Any]], llm_clean: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """조건마다 학습 → 실제 시험 · 합성 시험 점수."""
    conds = [
        ("실제만", train),
        ("실제 + 합성(거르기 전)", train + syn_raw),
        ("실제 + 합성(거른 뒤)", train + syn_clean),
        ("합성만(거른 뒤)", syn_clean),
    ]
    if llm_clean is not None:
        conds.append(("실제 + LLM 합성(거른 뒤)", train + llm_clean))
    rows = []
    for name, data in conds:
        if len({x["type"] for x in data}) < 2:
            continue
        m = _fit([x["query"] for x in data], [x["type"] for x in data])
        rows.append({"condition": name, "n_train": len(data), "real": score(m, test), "synthetic": score(m, syn_test)})
    return rows


def experiment(
    items: list[dict[str, Any]], seeds: int = 5, per_type: int = 60, keep: int = 25, lcfg: Any = None, progress=lambda f, m: None
) -> dict[str, Any]:
    """나누기 씨앗마다 부족 분석 → 부족 유형만 생성 → 다양성 고르기 → 거르기 → 조건별 학습 · 실제 · 합성 시험. 씨앗 평균과 범위."""
    from app.stages.synthetic import make

    runs = []
    for s in range(seeds):
        progress(s / seeds, f"씨앗 {s + 1}/{seeds}")
        train, test = make.split(items, s)
        gaps = make.gap(train, cv_recall(train))
        short = [g["type"] for g in gaps if g["short"]] or list(TYPES)
        raw = make.generate(train, short, per_type, s)
        syn_test = make.generate(train, list(TYPES), 15, 1000 + s)  # 합성 시험 — 같은 틀 · 다른 씨앗(학습 합성과 겹치지 않게)
        div = make.select_diverse(raw, keep)
        clean, rep = make.clean(div, [x["query"] for x in test])
        llm_clean = None
        if lcfg is not None:
            gen = make.llm_generate(lcfg, train, short, 24, 8, s, lambda f, m, s=s: progress((s + f) / seeds, f"씨앗 {s + 1} LLM · {m}"))
            llm_clean, _ = make.clean(gen, [x["query"] for x in test])
        runs.append({"seed": s, "gaps": gaps, "short": short, "clean_report": rep, "diversity_raw": make.diversity([x["query"] for x in raw]),
                     "diversity_clean": make.diversity([x["query"] for x in clean]), "rows": compare(train, test, raw, clean, syn_test, llm_clean), "llm_n": len(llm_clean) if llm_clean is not None else None,
                     "examples": [{"type": x["type"], "how": x["how"], "query": x["query"]} for x in clean[:: max(1, len(clean) // 10)][:10]]})  # fmt: skip
    conds = [r["condition"] for r in runs[0]["rows"]]
    summary = []
    for c in conds:
        rs = [next(x for x in r["rows"] if x["condition"] == c) for r in runs]
        real = [x["real"]["acc"] for x in rs]
        summary.append({"condition": c, "n_train": round(sum(x["n_train"] for x in rs) / len(rs)), "real_acc": round(sum(real) / len(real), 3),
                        "real_min": min(real), "real_max": max(real), "real_macro": round(sum(x["real"]["macro_recall"] for x in rs) / len(rs), 3),
                        "synthetic_acc": round(sum(x["synthetic"]["acc"] for x in rs) / len(rs), 3),
                        "recall": {t: round(sum(x["real"]["recall"].get(t, 0) for x in rs) / len(rs), 3) for t in TYPES}})  # fmt: skip
    return {"seeds": seeds, "per_type": per_type, "keep": keep, "summary": summary, "runs": runs}
