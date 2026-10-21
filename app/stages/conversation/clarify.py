"""C2 되묻기: 답에 꼭 필요한 정보가 없거나 질문이 너무 모호하면 답하기 전에 되묻는다.

모르면 되묻는 것이 근거 밖에서 지어내는 것보다 낫다(답 없는 질문을 13개 중 1개만 거절했던 법률 실측). 다만 되묻기가 잦으면
상담이 길어지므로, 되물을 이유를 두 가지로 좁힌다:
1. 필수 정보 빠짐 — 고장 문의인데 제품을 모른다(모델마다 조치가 달라 틀린 모델의 조치를 안내하게 됨, AS 실측의 '다른 모델 근거 79%')
2. 검색이 헷갈림 — 질문이 짧고(명사 2개 이하) 검색 1 · 2위 점수 차가 아주 작다(무엇을 묻는지 여러 갈래로 읽힘)
한 대화에서 같은 이유로 두 번 묻지 않는다(고객이 답하지 않으면 그대로 답한다 — 되묻기만 반복하면 상담이 끝나지 않음).
"""

from typing import Any

from app.core.korean import nouns_many
from app.stages.conversation.memory import SYMPTOM

GAP_LOW = 0.02  # 1 · 2위 (차/1위) 가 이보다 작으면 헷갈림 — 6 라우팅의 확신도 라우터와 같은 신호


def check(question: str, mem: dict[str, Any], *, need_model: bool = False, known_models: list[str] | tuple[str, ...] = (),
          signals: dict[str, Any] | None = None, asked: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    """→ {"ask", "reason", "prompt"}. need_model: 제품 모델을 아는 것이 답에 필요한 컬렉션(제품별 매뉴얼)."""
    asked = asked or []
    if need_model and known_models and not mem.get("product_model") and SYMPTOM.search(question or "") and "product_model" not in asked:
        ex = ", ".join(list(known_models)[:3])
        return {
            "ask": True,
            "reason": "product_model",
            "prompt": f"어느 제품(모델)인지 알려 주시겠어요? 모델마다 조치가 다릅니다. 예: {ex}",
        }
    s = signals or {}
    if (
        s.get("n", 0) >= 2
        and s.get("gap") is not None
        and s["gap"] < GAP_LOW
        and len(nouns_many([question])[0]) <= 2
        and "vague" not in asked
    ):
        return {
            "ask": True,
            "reason": "vague",
            "prompt": "조금 더 구체적으로 알려 주시겠어요? 어떤 제품 · 상황 · 증상인지 함께 적어 주시면 정확히 찾겠습니다.",
        }
    return {"ask": False, "reason": "", "prompt": ""}
