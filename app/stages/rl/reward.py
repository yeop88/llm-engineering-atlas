"""보상 함수: RAG 답변이 '좋은 답'인지 숫자 하나로. 강화학습 · 선호 학습 · Best-of-N 선택이 모두 이 점수를 쓴다.

무엇을 좋다고 볼지(이 프로젝트의 기준)
- 문장마다 인용한 근거에 실제로 있는 내용일 것(문장 근거율) — 환각을 줄이는 핵심
- 정답 근거가 있으면 그것을 인용할 것(평가 세트처럼 정답 근거를 알 때만)
- 없는 근거 번호를 인용하지 말 것, 근거가 있는데 '찾을 수 없다'고 거절하지 말 것
- 근거가 정말 없으면 지어내지 말고 거절할 것(정직한 거절은 보상)
- 지나치게 길지 않을 것 — 길게 쓰면 근거 밖 문장이 섞일 기회가 늘어난다

가중치는 설명 가능한 단순 합으로 둔다. 학습된 보상 모델은 판단 이유를 알기 어렵고, 보상 해킹(점수만 올리는 답)을 찾기도 어렵다.
"""

from typing import Any

from app.stages.rag import answer, evaluation

WEIGHTS = {
    "support": 1.0,
    "evidence_cited": 1.0,
    "invalid_citation": -0.5,
    "false_refusal": -1.0,
    "honest_refusal": 0.5,
    "too_long": -0.2,
    "hallucination": -1.0,  # 답 없는 질문에 답함(지어냄)
}
MAX_CHARS = 600  # 이보다 긴 답은 감점 (근거 5개 RAG 답변의 보통 길이 기준)


def reward(text: str, sources: list[dict[str, Any]], evidence: str = "", weights: dict[str, float] | None = None,
           item: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """item 을 주면(평가 세트) 그 질문의 근거들 · 답 없음 여부로 채점한다. 답 없는 질문에 답하면 지어낸 것이라 감점."""
    w = WEIGHTS | (weights or {})
    check = answer.verify(text, sources)
    parts: dict[str, float] = {}
    if item is not None and not evaluation.answerable(item):
        parts["honest_refusal" if check["refused"] else "hallucination"] = w["honest_refusal"] if check["refused"] else w["hallucination"]
        return {"total": round(sum(parts.values()), 4), "parts": parts, "check": check}
    if item is not None:
        evidence = (evaluation.evidences_of(item) or [""])[0]
    has_ev = bool(evidence) and any(evaluation.contains_evidence(s["text"], evidence) for s in sources)
    if check["refused"]:
        # 근거에 답이 있는데 거절하면 감점, 답할 근거가 없을 때 거절하면 보상(정답 근거를 모르면 판단하지 않음)
        if evidence:
            parts["false_refusal" if has_ev else "honest_refusal"] = w["false_refusal"] if has_ev else w["honest_refusal"]
    else:
        parts["support"] = w["support"] * float(check["supported_ratio"] or 0.0)
        if evidence and has_ev:
            ev_idx = {i + 1 for i, s in enumerate(sources) if evaluation.contains_evidence(s["text"], evidence)}
            parts["evidence_cited"] = w["evidence_cited"] * float(bool(ev_idx & set(check["cited_sources"])))
        if check["invalid_citations"]:
            parts["invalid_citation"] = w["invalid_citation"] * min(2, len(check["invalid_citations"]))
        if len(text) > MAX_CHARS:
            parts["too_long"] = w["too_long"]
    return {"total": round(sum(parts.values()), 4), "parts": {k: round(v, 4) for k, v in parts.items()}, "check": check}
