"""라우터: 질문 하나를 쉬움(easy) / 어려움(hard)으로 나눈다. 세 가지 방식을 같은 평가로 비교하려고 모아 둔다.

- 규칙(rule): 질문 글만 본다(길이 · 이유/방법/비교를 묻는 말 · 여러 요구). 비용 0, 설명 가능하지만 문서와 무관하다.
- 검색 확신도(confidence): 싼 경로로 먼저 검색해 1위와 2위 점수 차가 크면(검색이 확신) 쉬움, 작으면 어려움.
  검색은 어차피 해야 하므로 추가 비용이 거의 없고, '이 문서 모음에서' 어려운지를 본다는 점이 규칙과 다르다.
- LLM 판단(llm): LLM 에게 난이도를 묻는다. 가장 유연하지만 질문마다 LLM 호출 시간이 붙는다.
"""

import re
import time
from typing import Any

from app.core import llm

EASY, HARD = "easy", "hard"
ROUTERS = {"rule": "규칙 (질문 형태)", "confidence": "검색 확신도", "llm": "LLM 판단"}

# 이유 · 방법 · 비교 · 조건을 묻는 말 — 근거 하나를 그대로 옮기기보다 여러 근거를 엮어야 하는 질문의 신호.
# '어떤'은 단순 사실 질문("어떤 문자로 쓰나요")에도 흔해 넣지 않았다.
HARD_WORDS = ["왜", "이유", "어떻게", "방법", "절차", "차이", "비교", "경우에", "만약", "각각", "동시에", "불이익",
              "why", "how ", "compare", "difference", "versus", " vs"]  # fmt: skip
_JOIN = re.compile(r"그리고|및|또는|, |와 |과 ")


def rule_features(question: str) -> dict[str, Any]:
    q = question.strip()
    return {
        "chars": len(q),
        "hard_words": [w.strip() for w in HARD_WORDS if w in q.lower()],
        "joins": len(_JOIN.findall(q)),
        "questions": max(1, q.count("?")),
    }


def route_rule(question: str, max_chars: int = 45) -> tuple[str, str]:
    """→ (경로, 이유). 기준값 45자: 직접 작성 평가 세트의 사실 확인형 질문 대부분이 이보다 짧았다(문서에 측정 기록)."""
    f = rule_features(question)
    why = []
    if f["hard_words"]:
        why.append(f"'{f['hard_words'][0]}' 을(를) 물음")
    if f["chars"] > max_chars:
        why.append(f"{f['chars']}자로 김(>{max_chars})")
    if f["joins"] >= 2 or f["questions"] >= 2:
        why.append("여러 가지를 함께 물음")
    return (HARD, " · ".join(why)) if why else (EASY, f"짧은 단일 질문({f['chars']}자)")


def confidence(results: list[dict[str, Any]]) -> float | None:
    """검색 확신도 = (1위 − 2위) / |1위|. 의미 검색 점수(코사인)가 있으면 그것을, 없으면 결과 점수를 쓴다.

    점수 자체(1위 점수)는 모델 · 질문 길이마다 수준이 달라 기준을 잡기 어렵다. 1 · 2위 차이는 '다른 후보보다
    얼마나 뚜렷한가'라서 모델이 바뀌어도 비교적 안정적이다. 결과가 1개 이하이면 판단할 수 없어 None.
    """

    def s(r: dict[str, Any]) -> float:
        return float((r.get("scores") or {}).get("dense", r["score"]))

    if len(results) < 2:
        return None
    s1, s2 = s(results[0]), s(results[1])
    return (s1 - s2) / max(abs(s1), 1e-9)


def route_confidence(results: list[dict[str, Any]], threshold: float) -> tuple[str, str]:
    c = confidence(results)
    if c is None:
        return HARD, "검색 결과가 부족해 판단 불가 → 어려움으로"
    return (
        (EASY, f"1·2위 차이 {c:.3f} ≥ {threshold}")
        if c >= threshold
        else (HARD, f"1·2위 차이 {c:.3f} < {threshold} — 검색이 확신하지 못함")
    )


LLM_SYSTEM = (
    "당신은 질문 난이도 분류기입니다. 문서 검색 기반 질의응답 시스템에 들어온 질문을 보고, "
    "문서 한 곳에서 사실 하나를 찾아 그대로 답하면 되는 질문이면 easy, "
    "여러 근거를 종합 · 비교하거나 이유 · 절차 · 조건을 설명해야 하거나 상황 설명이 길어 핵심을 찾아야 하면 hard 로 분류하세요. "
    '{"level": "easy" 또는 "hard", "reason": "한 문장"} 형식의 JSON 만 출력하세요.'
)


def route_llm(cfg: llm.LLMConfig, question: str) -> tuple[str, str, float]:
    """→ (경로, 이유, 걸린 초). 형식이 어긋나면 어려움으로 보낸다 — 잘못 쉬움으로 보내 품질을 잃는 쪽이 더 나쁘다."""
    t = time.perf_counter()
    try:
        obj, _ = llm.chat_json(cfg, LLM_SYSTEM, question, max_tokens=120, temperature=0)
        level = str(obj.get("level", "")).strip().lower() if isinstance(obj, dict) else ""
        reason = str(obj.get("reason", "")) if isinstance(obj, dict) else ""
    except llm.LLMError as exc:
        level, reason = "", f"판단 실패({exc})"
    secs = time.perf_counter() - t
    if level not in (EASY, HARD):
        return HARD, f"LLM 응답을 해석하지 못해 어려움으로 — {reason}"[:200], secs
    return level, reason[:200], secs
