"""MA7 품질 검증 에이전트(Critic): 답이 근거와 맞는지 · 질문에 답하는지 · 규정을 어기지 않는지 보고 통과 · 수정 요청 · 반려를 정한다.

검사는 이미 있는 것을 그대로 쓴다 — 문장별 근거 일치 · 질문 관련성(2 RAG 검증), 출력 정책 · 개인정보(G4 · G2), 분석 결과와 숫자가
맞는지. 수정 요청은 어느 문장이 왜 문제인지 지적을 작성 에이전트에게 돌려준다(재작성 루프, 횟수 제한). 반려는 규정 위반 —
고쳐 쓰게 두지 않고 막는다(정책 차단과 같은 기준).
"""

import re
from typing import Any

from app.stages.guardrails import pii, policy
from app.stages.rag import answer

MIN_SUPPORT = 0.6


def review(
    question: str, text: str, sources: list[dict[str, Any]], analysis: dict[str, Any] | None, domain: str = "general"
) -> dict[str, Any]:
    v = answer.verify(text, sources, question=question)
    pol = policy.check(text, domain, v)
    issues: list[str] = []
    if pol["action"] == "block":
        return {
            "decision": "reject",
            "issues": [f"규정 위반: {', '.join(x.get('rule', '') for x in pol['violations'])}"],
            "verify": v,
            "policy": pol["action"],
        }
    unsupported = [s["text"] for s in v.get("sentences") or [] if not s.get("supported")]
    if v.get("supported_ratio") is not None and v["supported_ratio"] < MIN_SUPPORT:
        issues.append(f"근거 일치 {v['supported_ratio']} < {MIN_SUPPORT} — 근거 없는 문장: " + " / ".join(unsupported[:3]))
    if v.get("invalid_citations"):
        issues.append(f"없는 근거 번호 {v['invalid_citations']}")
    if (v.get("relevant_ratio") or 1) < 0.5:
        issues.append("질문과 상관없는 문장이 많습니다")
    if analysis and analysis.get("ok"):  # 분석 결과의 숫자가 답에 있어야 — 다른 숫자를 지어냈으면 지적
        want = {n for n in re.findall(r"\d+(?:\.\d+)?", str(analysis.get("result"))) if len(n) > 0}
        if want and not any(n in text for n in want):
            issues.append(f"분석 결과의 숫자({', '.join(sorted(want)[:5])})가 답에 없습니다")
    if pii.scan(text):
        issues.append("개인정보가 들어 있습니다 — 가려 쓰세요")
    if v.get("refused"):
        return {"decision": "pass", "issues": ["근거가 부족해 답하지 않음(거절) — 그대로 통과"], "verify": v, "policy": pol["action"]}
    return {"decision": "revise" if issues else "pass", "issues": issues, "verify": v, "policy": pol["action"]}
