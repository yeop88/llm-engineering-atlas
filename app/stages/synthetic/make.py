"""SD1~SD6 합성 데이터: 부족 분석 → 전략 → 생성(만든 방법 · 원본 기록) → 다양성 · 중복 · 누수 · 개인정보 거르기 → 검토 표본.

과제는 '질문 유형 분류'(법률 질문 7유형 — 사실 · 바꿔 말하기 · 조건 · 상황 · 긴 상황 · 답 없음 · 여러 질문)다. 유형은 답하는 방법(라우팅 ·
거절 · 근거 수)을 정하는 신호라 실제로 쓸모가 있고, 학습이 가벼워(글자 n-gram + 로지스틱 회귀) 합성 데이터의 효과를 이 PC 에서
여러 번 잴 수 있다. 실제 질문은 평가 세트의 질문이고, 학습용(적게 · 유형이 치우치게)과 시험용(나머지, 학습 · 생성에 쓰지 않음)으로 나눈다.

생성은 LLM 없이 규칙으로 한다(템플릿 · 바꿔 쓰기 · 이어 붙이기). 원본은 학습용 실제 질문의 근거 문장 · 질문뿐이다 — 시험용 질문의
근거로 만들면 그것이 누수다. LLM 바꿔 쓰기는 같은 자리(strategy 'llm')에 끼울 수 있게 해 두고 비교만 한다.
"""

import json
import random
import re
from collections import Counter
from typing import Any

import numpy as np

from app.stages.flywheel.review import similar
from app.stages.guardrails import pii

TYPES = ("fact", "paraphrase", "condition", "situation", "long_situation", "unanswerable", "multi")
LABEL = {
    "fact": "사실",
    "paraphrase": "바꿔 말하기",
    "condition": "조건",
    "situation": "상황",
    "long_situation": "긴 상황",
    "unanswerable": "답 없음",
    "multi": "여러 질문",
}
# 법률 용어 → 일상 말(바꿔 말하기 · 상황 질문은 고객의 말투로 묻는다)
PLAIN = {"근로자": "직원", "사용자": "회사", "임차인": "세입자", "임대인": "집주인", "지급": "주는 것", "반환": "돌려받는 것", "해고": "잘리는 것", "퇴직": "그만두는 것",
         "임금": "월급", "보증금": "전세금", "계약": "약속", "배당": "나눠 받는 것", "경매": "집이 팔리는 것", "대항력": "버틸 수 있는 힘", "판단": "보는 것"}  # fmt: skip
SITUATIONS = [
    "제가 일하는 회사에서",
    "저희 집주인이",
    "전세로 살고 있는데",
    "얼마 전 퇴사했는데",
    "계약 기간이 끝나 가는데",
    "월급이 몇 달째 밀려서",
]
DETAILS = ["구체적인 금액 기준은 얼마인가요?", "정확한 기간은 며칠인가요?", "몇 퍼센트까지 인정되나요?", "신청 서류는 무엇인가요?"]


def split(
    items: list[dict[str, Any]], seed: int = 0, train_counts: dict[str, int] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """실제 질문 → (학습용, 시험용). 학습용은 유형마다 train_counts 만큼만 — 실제 데이터가 부족하고 치우친 상황을 만든다."""
    counts = train_counts or {
        "fact": 12,
        "paraphrase": 12,
        "situation": 12,
        "long_situation": 6,
        "unanswerable": 6,
        "condition": 2,
        "multi": 1,
    }
    r = random.Random(seed)
    by: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by.setdefault(it.get("type"), []).append(it)
    train, test = [], []
    for t, xs in by.items():
        if t not in TYPES:
            continue
        xs = xs[:]
        r.shuffle(xs)
        k = counts.get(t, 0)
        train += xs[:k]
        test += xs[k:]
    return train, test


def gap(train: list[dict[str, Any]], cv_recall: dict[str, float] | None = None, min_n: int = 8) -> list[dict[str, Any]]:
    """SD1 부족 분석: 유형별 학습 수와(있으면) 교차 검증 재현율 → 부족 유형과 이유. 적고 못 맞히는 유형부터."""
    n = Counter(it["type"] for it in train)
    out = []
    for t in TYPES:
        why = []
        if n[t] < min_n:
            why.append(f"학습 예시 {n[t]}건(< {min_n})")
        rec = (cv_recall or {}).get(t)
        if rec is not None and rec < 0.6:
            why.append(f"교차 검증 재현율 {round(rec * 100)}%")
        out.append(
            {
                "type": t,
                "label": LABEL[t],
                "n": n[t],
                "recall": rec,
                "short": bool(why),
                "why": why,
                "need": max(0, min_n * 5 - n[t]) if why else 0,
            }
        )
    return sorted(out, key=lambda x: (not x["short"], x["recall"] if x["recall"] is not None else 1, x["n"]))


def strategy(t: str) -> list[str]:
    """SD2: 유형마다 맞는 생성 방법 — 형식이 유형을 정하는 것(조건 · 상황 · 여러 질문)은 틀, 말투가 정하는 것은 바꿔 쓰기."""
    return {"fact": ["template"], "paraphrase": ["plain_rewrite"], "condition": ["template"], "situation": ["template", "plain_rewrite"],
            "long_situation": ["template"], "unanswerable": ["template"], "multi": ["combine"]}[t]  # fmt: skip


PARTICLE = re.compile(r"(은|는|이|가|을|를|에서|에게|으로|로|의|와|과|에)$")


def _topic(ev: str, q: str) -> str:
    """근거 문장 · 질문에서 물을 거리(앞쪽 명사구): 어절을 차례로 모아 조사로 끝나는 어절에서 조사를 떼고 멈춘다(2~6어절).

    처음에는 글자 수(40자 안)로 잘랐다. 그러자 '…단서에 따른' 이 '…단서에 따'로 잘려 '따은 무엇을 뜻하나요?' 같은 깨진 질문이 나왔다.
    어절 단위로 끊어야 글이 깨지지 않는다.
    """
    src = re.sub(r"^(따라서|그러나|다만|그리고|원심은|피고는|원고는|이 사건)\s*", "", (ev or q or "").strip())
    words, out = src.split(), []
    for w in words[:8]:
        w = w.strip(" ,.‘’'\"()")
        m = PARTICLE.search(w)
        if m and len(out) >= 1:
            out.append(w[: m.start()] or w)
            break
        out.append(w)
        if len(out) >= 6:
            break
    return " ".join(x for x in out if x)


def j(word: str, pair: str) -> str:
    """조사 맞추기: j('소유', '은/는') → '소유는'. 받침이 있으면 앞, 없으면 뒤 — 틀에 '은'을 박아 두면 '소유은'이 나왔다."""
    a, b = pair.split("/")
    ch = word[-1] if word else ""
    batchim = "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
    if not ("가" <= ch <= "힣"):
        batchim = ch.isdigit() and ch in "0136789"  # 숫자는 읽는 소리로(일 · 삼 · 육 · 칠 · 팔 · 십 · 영)
    return word + (a if batchim else b)


def _plain(s: str) -> str:
    for a, b in PLAIN.items():
        s = s.replace(a, b)
    return s


def generate(train: list[dict[str, Any]], types: list[str], per_type: int = 60, seed: int = 0) -> list[dict[str, Any]]:
    """SD3: 학습용 실제 질문만 원본으로 — 만든 방법 · 원본 id 를 남긴다(나중에 '어떤 방법이 도움이 됐나'를 가르려고)."""
    r = random.Random(seed)
    seeds = [it for it in train if it.get("evidence") or it.get("query")]
    out = []
    for t in types:
        for k in range(per_type):
            a, b = r.choice(seeds), r.choice(seeds)
            top, top2 = _topic(a.get("evidence", ""), a["query"]), _topic(b.get("evidence", ""), b["query"])
            if t == "fact":
                q, how = (
                    r.choice(
                        [f"{top}에 대해 법원은 어떻게 판단했나요?", f"{j(top, '은/는')} 무엇을 뜻하나요?", f"{top}의 요건은 무엇인가요?"]
                    ),
                    "template",
                )
            elif t == "paraphrase":
                q, how = (
                    _plain(
                        r.choice(
                            [
                                f"{j(top, '은/는')} 어떻게 되나요?",
                                f"{j(top, '이면/면')} 어떻게 하나요?",
                                f"{top} 관련해서 받을 수 있는 건 뭔가요?",
                            ]
                        )
                    ),
                    "plain_rewrite",
                )
            elif t == "condition":
                q, how = (
                    r.choice(
                        [
                            f"만약 {top}인 경우라면, {j(top2, '은/는')} 어떻게 되나요?",
                            f"{top}일 때 {j(top2, '은/는')} 인정되나요?",
                            f"{j(top, '이라면/라면')} {j(top2, '은/는')} 달라지나요?",
                            f"{top}인 경우, {top2}의 효력은 어떻게 되나요?",
                            f"{j(top, '이/가')} 없었다면 {j(top2, '은/는')} 어떻게 판단되나요?",
                        ]
                    ),
                    "template",
                )
            elif t == "situation":
                q = f"{r.choice(SITUATIONS)} {_plain(top)} 문제가 생겼어요. 제가 할 수 있는 게 있을까요?"
                how = "template+plain_rewrite"
            elif t == "long_situation":
                q = (f"{r.choice(SITUATIONS)} {_plain(top)} 일이 있었습니다. 그 뒤로 {_plain(top2)} 문제도 겹쳤는데요, "
                     f"이런 경우 제 권리가 보호되는지, 그리고 어떤 절차를 밟아야 하는지 알고 싶습니다.")  # fmt: skip
                how = "template"
            elif t == "unanswerable":
                q, how = f"{top}의 {r.choice(DETAILS)}", "template"
            else:
                q, how = f"{j(top, '은/는')} 어떻게 판단되며, 그와 함께 {top2}의 기준은 무엇인가요?", "combine"
            out.append({"id": f"syn-{t}-{k}", "query": q, "type": t, "how": how, "source_ids": [a.get("id"), b.get("id")]})
    return out


def llm_generate(
    lcfg: Any, train: list[dict[str, Any]], types: list[str], per_type: int = 24, batch: int = 8, seed: int = 0, progress=lambda f, m: None
) -> list[dict[str, Any]]:
    """SD3 의 LLM 바꿔 쓰기: 유형마다 학습용 실제 질문 2개를 예로, 다른 근거 문장(학습용)을 주제로 같은 유형 질문을 batch 개씩.

    규칙 틀은 같은 말투만 늘린다. LLM 은 말투를 다양하게 만들 수 있지만 느리고, 유형을 지키지 않을 수 있다(검토 · 실제 평가로 본다).
    """
    from app.core import llm

    r = random.Random(seed)
    out: list[dict[str, Any]] = []
    calls = max(1, per_type // batch)
    for ti, t in enumerate(types):
        ex = [x["query"] for x in train if x["type"] == t][:2] or [x["query"] for x in train][:1]
        for c in range(calls):
            progress((ti * calls + c) / (len(types) * calls), f"{LABEL[t]} {c + 1}/{calls}")
            topics = [_topic(x.get("evidence", ""), x["query"]) for x in r.sample(train, min(batch, len(train)))]
            sys = "법률 상담 질문을 만드는 도구입니다. 반드시 JSON 목록만 출력합니다."
            user = (f"'{LABEL[t]}' 유형 질문의 예:\n- " + "\n- ".join(ex) + "\n\n아래 주제마다 같은 유형의 질문을 하나씩, 말투를 다양하게 만드세요. "
                    "JSON 문자열 목록으로만 답하세요.\n주제:\n- " + "\n- ".join(topics))  # fmt: skip
            try:
                qs = llm.parse_json(llm.chat(lcfg, sys, user, 900, 0.8)["text"])
            except Exception:  # noqa: BLE001 — 한 묶음이 실패해도 나머지는 만든다
                continue
            for k, q in enumerate(qs if isinstance(qs, list) else []):
                if isinstance(q, str) and 8 <= len(q) <= 300:
                    out.append({"id": f"llm-{t}-{c}-{k}", "query": q.strip(), "type": t, "how": "llm", "source_ids": []})
    return out


def _vecs(texts: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not texts:
        return np.zeros((0, 1))
    return (
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1).fit_transform(texts).toarray()
    )  # 행마다 L2 정규화돼 있음 → 내적 = 코사인


def diversity(texts: list[str]) -> dict[str, Any]:
    """SD4 다양성: 평균 쌍 유사도(글자 n-gram 코사인) · 서로 다른 2-gram 몫 · 첫 3어절 반복(같은 틀만 늘었나)."""
    if len(texts) < 2:
        return {"n": len(texts), "mean_sim": None, "distinct2": None, "top_prefix_share": None}
    X = _vecs(texts)
    S = X @ X.T
    n = len(texts)
    mean_sim = float((S.sum() - n) / (n * (n - 1)))
    grams = [t[i : i + 2] for t in texts for i in range(len(t) - 1)]
    pref = Counter(" ".join(t.split()[:3]) for t in texts)
    return {
        "n": n,
        "mean_sim": round(mean_sim, 3),
        "distinct2": round(len(set(grams)) / max(1, len(grams)), 3),
        "top_prefix_share": round(pref.most_common(1)[0][1] / n, 3),
    }


def select_diverse(rows: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """SD4: 유형마다 가장 덜 비슷한 것부터 고른다(먼 점 고르기) — 많이보다 다양하게."""
    out = []
    by: dict[str, list[dict[str, Any]]] = {}
    for x in rows:
        by.setdefault(x["type"], []).append(x)
    for xs in by.values():
        if len(xs) <= k:
            out += xs
            continue
        X = _vecs([x["query"] for x in xs])
        chosen = [0]
        best = X @ X[0]
        while len(chosen) < k:
            i = int(np.argmin(best + np.isin(np.arange(len(xs)), chosen) * 9))
            chosen.append(i)
            best = np.maximum(best, X @ X[i])
        out += [xs[i] for i in chosen]
    return out


def clean(
    rows: list[dict[str, Any]], test_queries: list[str], dup: float = 0.8, leak: float = 0.6
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """SD5: 서로 거의 같은 것 · 시험용 실제 질문과 비슷한 것(누수) · 개인정보가 든 것을 뺀다. 뺀 수와 예를 남긴다."""
    kept: list[dict[str, Any]] = []
    rep: dict[str, Any] = {"in": len(rows), "dup": 0, "leak": 0, "pii": 0, "leak_examples": []}
    for x in rows:
        q = x["query"]
        if pii.scan(q):
            rep["pii"] += 1
            continue
        hit = next((t for t in test_queries if similar(q, t) >= leak), None)
        if hit:
            rep["leak"] += 1
            if len(rep["leak_examples"]) < 3:
                rep["leak_examples"].append([q[:60], hit[:60]])
            continue
        if any(similar(q, k["query"]) >= dup for k in kept if k["type"] == x["type"]):
            rep["dup"] += 1
            continue
        kept.append(x)
    rep["out"] = len(kept)
    return kept, rep


def review_sample(rows: list[dict[str, Any]], n: int = 20, seed: int = 0) -> list[dict[str, Any]]:
    """SD6: 유형이 고르게 섞이도록 표본을 뽑는다(사람이 '질문으로 말이 되나 · 유형이 맞나'를 표시)."""
    r = random.Random(seed)
    by: dict[str, list[dict[str, Any]]] = {}
    for x in rows:
        by.setdefault(x["type"], []).append(x)
    out: list[dict[str, Any]] = []
    while len(out) < min(n, len(rows)):
        for xs in by.values():
            left = [x for x in xs if x not in out]
            if left and len(out) < n:
                out.append(r.choice(left))
    return out


def wilson(bad: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """검토 표본의 오류율 95% 구간 — 표본 20건에 오류 0건이어도 위 끝은 16% 다(통과 기준은 위 끝으로 본다)."""
    if not n:
        return 0.0, 1.0
    p = bad / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


def dumps(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
