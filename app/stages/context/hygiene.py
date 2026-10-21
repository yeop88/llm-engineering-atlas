"""CX6 맥락 오염 방지: 틀린 중간 결과가 맥락에 남으면 다음 답이 그것을 따른다 — 얼마나 따르는지 재고, 막는 방법을 비교한다.

오염 시험: 정답 근거에 수가 있는 질문만 골라, 그 수를 바꾼 '틀린 이전 단계 결과' 한 개를 맥락에 넣는다(에이전트가 앞 단계에서 잘못
읽은 값을 적어 둔 상황). 답에 바뀐 수가 나오면 오염된 것이다.

막는 방법:
- none: 그대로(다른 근거와 같은 모양으로 섞임)
- label: 출처 · 상태 표시를 붙임 — '[이전 단계 결과 · 검증 실패 · 원문과 다를 수 있음]'
- remove: 검증에 떨어진 결과는 맥락에서 뺌(판정 결과를 맥락 관리가 따름)
- source_first: 원문 근거를 앞에, 이전 단계 결과는 맨 뒤에 '참고'로
정답률(정답 근거 인용)과 오염률을 함께 본다 — 표시만으로 막히는지, 빼야만 막히는지.
"""

import random
import re
from typing import Any

from app.stages.rag import answer, evaluation

MITIGATIONS = ("none", "label", "remove", "source_first")
LABEL = {
    "none": "그대로 섞음",
    "label": "출처 · 실패 표시",
    "remove": "검증 실패 결과 빼기",
    "source_first": "원문 먼저 · 이전 결과는 뒤에",
}
NUM = re.compile(r"(?<![0-9])(\d{1,7})(?![0-9])")


def corrupt(evidence: str, rnd: random.Random) -> tuple[str, str] | None:
    """근거 문장의 첫 수를 다른 수로 — (틀린 문장, 틀린 값). 수가 없으면 None."""
    m = NUM.search(evidence or "")
    if not m:
        return None
    v = int(m.group(1))
    wrong = str(v + rnd.choice([1, 2, 3, 7, 10]) if v < 1000 else v * 2)
    return evidence[: m.start()] + wrong + evidence[m.end() :], wrong


def build(ctx: list[dict[str, Any]], bad: dict[str, Any], how: str) -> list[dict[str, Any]]:
    if how == "remove":
        return list(ctx)
    if how == "label":
        b = bad | {"filename": "[이전 단계 결과 · 검증 실패 · 원문과 다를 수 있음]"}
        return ctx[:1] + [b] + ctx[1:]
    if how == "source_first":
        return list(ctx) + [bad | {"filename": "[참고: 이전 단계 결과 — 원문 근거가 우선]"}]
    return ctx[:1] + [bad] + ctx[1:]  # none: 1위 근거 바로 뒤 — 그럴듯한 자리


def run(cfg, items, contexts, mitigations, max_chars, max_tokens, seed=7, progress=lambda f, m: None) -> dict[str, Any]:
    rnd = random.Random(seed)
    usable = []
    for it, ctx in zip(items, contexts, strict=True):
        evs = evaluation.evidences_of(it)
        c = corrupt(evs[0], rnd) if evs else None
        if c:
            usable.append((it, ctx, c))
    out: dict[str, Any] = {"n_usable": len(usable)}
    total = max(1, len(mitigations) * len(usable))
    for mi, how in enumerate(mitigations):
        rows, hit = [], []
        for i, (it, ctx, (bad_text, wrong)) in enumerate(usable):
            progress((mi * len(usable) + i) / total, f"{LABEL[how]} {i + 1}/{len(usable)}")
            bad = {"document_id": None, "filename": "(이전 단계 결과)", "text": bad_text}
            r = answer.evaluate_one(cfg, it, build(ctx, bad, how), max_chars, max_tokens, no_cache=True)
            rows.append(r)
            hit.append(bool(re.search(rf"(?<![0-9]){wrong}(?![0-9])", r["answer"])))
        out[how] = {"label": LABEL[how], "n": len(rows), "quality": round(sum(r["quality"] for r in rows) / len(rows), 4) if rows else None,
                    "contaminated": round(sum(hit) / len(hit), 4) if hit else None}  # fmt: skip
    return out
