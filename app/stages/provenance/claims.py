"""PV5~PV8 답 → 문장 → 주장 → 인용 · 근거 → 검증 · 부딪힘.

근거 일치 검증(2)은 답 전체의 '근거 있는 문장 비율'을 냈다. 그러면 한 문장 안에 맞는 주장과 틀린 주장이 섞여도 모르고, 어느 문장이
어느 근거에 기대는지 사람이 따라갈 수 없다. 그래서 답을 문장 → 주장(쉼표 · 접속 표현으로 나눈 사실 진술)으로 나누고, 주장마다
(1) 인용 번호가 가리키는 근거, (2) 글자 3-gram 이 가장 많이 겹치는 근거, (3) 주장의 표시(숫자 · 조문 번호 · 코드)가 그 근거에 그대로 있는지를 본다.
표시가 근거에 없으면 겹침이 높아도 '근거 약함' — 숫자 하나가 틀린 답이 가장 위험하다.
부딪힘(CONTRADICTS): 같은 질문(글자가 거의 같은 질문)의 다른 답에서 같은 자리의 표시가 다르면 표시한다.
"""

import re
from typing import Any

SENT = re.compile(r"(?<=[^\d\s][.!?。])\s+|\n+")
SPLIT = re.compile(r"(?:,|，|;| 그리고 | 또한 | 하지만 | 다만 )\s*")
CITE = re.compile(r"\[(\d{1,2}(?:\s*[,，]\s*\d{1,2})*)\]")
MARKS = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?|\b[A-Za-z]{1,3}-?\d{1,4}\b|\d+(?:\.\d+)?\s*(?:%|퍼센트|원|일|개월|년|시간|분|회|건|명|배)?")


def grams(s: str) -> set[str]:
    t = re.sub(r"\s", "", s or "")
    return {t[i : i + 3] for i in range(len(t) - 2)}


def marks(s: str) -> list[str]:
    return [re.sub(r"\s", "", m) for m in MARKS.findall(s or "") if m.strip()]


def split_claims(answer: str) -> list[dict[str, Any]]:
    """→ [{sentence_idx, sentence, claim, cites}] — 인용 번호는 문장 단위로 붙어 있어 그 문장의 주장들이 함께 쓴다."""
    out = []
    for si, sent in enumerate(s for s in SENT.split(answer or "") if s.strip()):
        cites = sorted({int(x) for m in CITE.findall(sent) for x in re.split(r"[,，]", m)})
        body = CITE.sub("", sent).strip()
        parts = [p.strip(" .") for p in SPLIT.split(body) if len(p.strip()) >= 6] or [body]
        for p in parts:
            out.append({"sentence_idx": si, "sentence": body, "claim": p, "cites": cites})
    return out


def support(claim: str, sources: list[dict[str, Any]], cites: list[int]) -> dict[str, Any]:
    """주장 하나의 근거: 인용한 근거 · 가장 겹치는 근거 · 표시 일치 → level(strong · weak · none · uncited)."""
    g = grams(claim)
    best, best_i = 0.0, None
    for i, s in enumerate(sources):
        ov = len(g & grams(s.get("text", ""))) / max(1, len(g))
        if ov > best:
            best, best_i = ov, i
    mk = marks(claim)
    cited_texts = [sources[c - 1].get("text", "") for c in cites if 0 < c <= len(sources)]
    hay = re.sub(r"\s", "", " ".join(cited_texts) if cited_texts else (sources[best_i].get("text", "") if best_i is not None else ""))
    missing = [m for m in mk if m not in hay]
    cite_ok = bool(cites) and all(0 < c <= len(sources) for c in cites)
    cite_hit = best_i is not None and (best_i + 1) in cites
    if not g or best < 0.2:
        level = "none"
    elif missing:
        level = "weak"  # 글은 겹치는데 숫자 · 조문이 근거에 없다 — 가장 위험한 경우
    elif best >= 0.45:
        level = "strong"
    else:
        level = "weak"
    if not cites and level != "none":
        level = "uncited"
    return {"level": level, "overlap": round(best, 3), "best_source": (best_i + 1) if best_i is not None else None, "cite_valid": cite_ok,
            "cite_matches_best": cite_hit, "marks": mk, "marks_missing": missing}  # fmt: skip


def analyze(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    claims = [c | support(c["claim"], sources, c["cites"]) for c in split_claims(answer)]
    n = len(claims) or 1
    lv = [c["level"] for c in claims]
    return {"claims": claims, "n": len(claims), "strong": lv.count("strong") / n, "weak": lv.count("weak") / n, "none": lv.count("none") / n,
            "uncited": lv.count("uncited") / n, "marks_missing": sum(len(c["marks_missing"]) for c in claims),
            "cite_precision": round(sum(c["cite_matches_best"] for c in claims if c["cites"]) / max(1, sum(1 for c in claims if c["cites"])), 3),
            "traceable": round(sum(1 for c in claims if c["level"] == "strong" and c["cite_valid"]) / n, 3)}  # fmt: skip


def same_question(a: str, b: str, th: float = 0.8) -> bool:
    ga, gb = grams(a), grams(b)
    return bool(ga and gb) and len(ga & gb) / max(1, len(ga | gb)) >= th


def contradictions(rows: list[dict[str, Any]], th: float = 0.8) -> list[dict[str, Any]]:
    """rows = [{id, question, answer, at}] → 같은 질문 · 다른 답에서 표시(숫자 · 조문 · 코드) 집합이 다르면 부딪힘 후보."""
    out, seen = [], set()
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if (a["id"], b["id"]) in seen or not same_question(a["question"], b["question"], th):
                continue
            seen.add((a["id"], b["id"]))
            ma, mb = set(marks(CITE.sub("", a["answer"]))), set(marks(CITE.sub("", b["answer"])))
            if ma and mb and ma != mb:
                out.append({"a": a["id"], "b": b["id"], "question": a["question"][:120], "only_a": sorted(ma - mb)[:8], "only_b": sorted(mb - ma)[:8],
                            "a_at": a.get("at"), "b_at": b.get("at")})  # fmt: skip
    return out
