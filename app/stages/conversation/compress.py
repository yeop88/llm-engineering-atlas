"""C5 긴 대화 압축 · C6 인계 요약.

긴 대화를 LLM 에 그대로 넣으면 문맥 한도를 넘고 느려진다(로컬 LLM 은 근거 2,000토큰 읽기에 25~31초). 그래서
최근 몇 턴만 원문으로, 그 앞은 메모리의 사실 목록으로 바꿔 넣는다. 사실 목록은 규칙으로 뽑은 것이라 요약이 사실을 바꾸지 않는다.
압축이 무엇을 잃는지는 평가(대화 세트)에서 '압축 뒤에도 재작성 · 검색이 맞나'로 잰다.
"""

import re
from typing import Any

from app.stages.conversation import memory as mem_mod


def history_for_prompt(messages: list[dict[str, Any]], mem: dict[str, Any], keep_turns: int = 4, max_chars: int = 1500) -> dict[str, Any]:
    """→ {"text", "kept", "dropped", "chars"}. 최근 keep_turns 메시지는 원문(각 300자까지), 그 앞은 사실 목록."""
    recent = messages[-keep_turns:]
    dropped = len(messages) - len(recent)
    rows = []
    if dropped and (facts := mem_mod.facts_text(mem)):
        rows.append(f"[앞 대화 {dropped}개 메시지 요약]\n{facts}")
    for m in recent:
        who = "고객" if m.get("role") == "user" else "상담"
        rows.append(f"{who}: {re.sub(r'\s+', ' ', m.get('text', ''))[:300]}")
    text = "\n".join(rows)
    if len(text) > max_chars:  # 그래도 길면 앞에서부터 자른다(최근 말이 가장 중요)
        text = "…" + text[-max_chars:]
    return {"text": text, "kept": len(recent), "dropped": dropped, "chars": len(text)}


def handoff_summary(messages: list[dict[str, Any]], mem: dict[str, Any]) -> dict[str, Any]:
    """상담원 인계 요약 — 상담원이 처음부터 다시 묻지 않게 사실 · 시도한 조치 · 마지막 질문을 한눈에."""
    users = [m["text"] for m in messages if m.get("role") == "user"]
    return {"product_model": mem.get("product_model") or "", "codes": mem.get("codes") or [], "symptoms": mem.get("symptoms") or [],
            "tried": mem.get("tried") or [], "topic": mem.get("topic") or [], "turns": len(users),
            "first_question": users[0] if users else "", "last_question": users[-1] if users else "",
            "text": mem_mod.facts_text(mem)}  # fmt: skip
