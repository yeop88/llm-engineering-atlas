"""LLM 목록형(listwise) 리랭커: 번호 붙인 후보들을 한 번에 보여 주고 질문에 관련 있는 순서를 받는다.

왜 목록형인가: 후보마다 LLM 을 부르는(pointwise) 방식은 후보 수만큼 호출해 로컬 LLM 으로는 너무 느리다(호출당 수 초).
한 번에 보여 주면 호출 1번으로 끝나고, 후보끼리 비교하며 순서를 정할 수 있다. 대신 후보 글을 짧게 잘라야 문맥에 들어간다.
LLM 이 일부 번호만 돌려주거나 형식을 어기면, 돌려준 번호를 앞에 두고 나머지는 원래 순서를 유지한다(검색 결과를 잃지 않게).
"""

import time
from typing import Any

from app.core import llm

SYSTEM = (
    "당신은 검색 결과 재정렬기입니다. 질문과 번호 붙은 후보 지문들을 보고, 질문에 답하는 데 도움이 되는 순서대로 후보 번호를 나열하세요. "
    "관련 없는 후보는 빼도 됩니다. "
    '{"order": [번호, 번호, ...]} 형식의 JSON 만 출력하세요.'
)


def prompt(query: str, texts: list[str], max_chars: int) -> str:
    lines = [f"질문: {query}", "", "후보:"]
    lines += [f"[{i + 1}] {' '.join(t.split())[:max_chars]}" for i, t in enumerate(texts)]
    return "\n".join(lines)


def rerank(cfg: llm.LLMConfig, query: str, texts: list[str], max_chars: int = 300) -> tuple[list[float], dict[str, Any]]:
    """→ (후보별 점수, 정보). 점수는 순위를 숫자로 바꾼 것(1위가 가장 큼)이라 크로스 인코더 점수와 척도가 다르다."""
    t = time.perf_counter()
    info: dict[str, Any] = {"model": cfg.model}
    try:
        obj, res = llm.chat_json(cfg, SYSTEM, prompt(query, texts, max_chars), max_tokens=200, temperature=0)
        raw = obj.get("order") if isinstance(obj, dict) else obj
        order = [int(x) - 1 for x in raw if str(x).strip().lstrip("[").rstrip("]").isdigit()] if isinstance(raw, list) else []
        info["output_tokens"] = res["usage"].get("output_tokens")
    except (llm.LLMError, ValueError, TypeError) as exc:
        order, info["error"] = [], str(exc)[:200]
    seen: list[int] = []
    for i in order:
        if 0 <= i < len(texts) and i not in seen:
            seen.append(i)
    info["returned"] = len(seen)
    full = seen + [i for i in range(len(texts)) if i not in seen]  # LLM 이 빠뜨린 후보는 원래 순서대로 뒤에
    scores = [0.0] * len(texts)
    for rank, i in enumerate(full):
        scores[i] = float(len(texts) - rank)
    info["seconds"] = round(time.perf_counter() - t, 2)
    return scores, info
