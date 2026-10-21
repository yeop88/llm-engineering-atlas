"""VC6 상담원 실시간 보조: 통화 전사를 따라가며 고객 발화마다 근거 · 추천 답 · 확인할 질문을 띄우고, 상담원의 채택 · 수정 · 무시를 잰다.

자동 음성 응답은 지연 · 정확도 모두 어렵지만(이 PC 실측 답 수십 초), 상담원 보조는 사람이 최종 판단을 하므로 몇 초 늦어도 쓸모가 있고
틀린 추천은 무시하면 된다. 그래서 같은 통화 흐름을 '자동 답' 대신 '추천'으로 내보낸다.

확인할 질문은 상담에 빠진 정보에서 나온다: 제품 모델 모름(모델마다 조치가 다름) · 오류 코드가 사전에 없음 · 안전 증상 · 시도한 조치
모름. 채택률은 추천마다 상담원이 누른 결과(채택 · 고쳐서 씀 · 무시)로 — 채택률이 낮은 의도 · 유형이 다음에 고칠 곳이다.
"""

from collections import Counter
from typing import Any


def questions(text: str, memory: dict[str, Any], vocab: dict[str, Any], urgency: str, codes: list[str]) -> list[str]:
    qs = []
    if urgency == "safety":
        qs.append("지금 전원 플러그를 뽑으셨는지, 연기 · 냄새가 계속 나는지 먼저 확인하세요(안전 안내 후 기사 접수).")
    if vocab.get("models") and not memory.get("product_model"):
        qs.append(f"제품 모델명을 확인하세요(예: {', '.join(vocab['models'][:3])}) — 모델마다 조치가 다릅니다.")
    unknown = [c for c in codes if vocab.get("codes") and c not in vocab["codes"]]
    if unknown:
        qs.append(f"{', '.join(unknown)} 는 자료에 없는 코드입니다 — 표시창 코드를 다시 불러 달라고 하세요.")
    if any(w in text for w in ("안 돼", "안돼", "그대로", "해 봤", "해봤")) and not memory.get("tried"):
        qs.append("이미 해 본 조치가 무엇인지 물어보세요(같은 안내 반복 방지).")
    return qs[:3]


def adoption(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    """채택 · 고쳐서 씀 · 무시 비율 — 의도별로도. 상담원이 아무것도 누르지 않은 추천은 세지 않는다(못 본 것일 수 있음)."""
    rated = [s for s in suggestions if s.get("feedback")]
    c = Counter(s["feedback"] for s in rated)
    by: dict[str, Counter] = {}
    for s in rated:
        by.setdefault(s.get("intent") or "-", Counter())[s["feedback"]] += 1
    n = len(rated)
    return {"n": len(suggestions), "rated": n, "adopted": round(c["adopted"] / n, 3) if n else None, "edited": round(c["edited"] / n, 3) if n else None,
            "ignored": round(c["ignored"] / n, 3) if n else None,
            "by_intent": {k: {"n": sum(v.values()), "adopted": round((v["adopted"] + v["edited"]) / sum(v.values()), 3)} for k, v in by.items()}}  # fmt: skip
