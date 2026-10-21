"""대화 한 턴: 메모리 → 재작성(C1) → 되묻기(C2) → 답변(긴 대화는 압축 C5) → 메모리 갱신.

검색 · 답변은 API 가 넘겨주는 함수로 한다(연결 계층의 서비스 답변 — 가드레일 · 요청 기록이 다른 화면과 같게).
되묻기는 재작성한 질문으로 먼저 검색해 본 신호(1 · 2위 차)를 쓴다 — 그 검색은 답변 검색과 같아 결과를 다시 쓰지 않고 버린다(0.2~0.6초).
"""

from collections.abc import Callable
from typing import Any

from app.core import llm
from app.stages.conversation import clarify, compress, rewrite
from app.stages.conversation import memory as mem_mod


def turn(
    question: str,
    history: list[dict[str, Any]],
    *,
    start: dict[str, Any] | None = None,
    known_models: list[str] | tuple[str, ...] = (),
    known_codes: list[str] | tuple[str, ...] = (),
    model_codes: dict[str, list[str]] | None = None,
    need_model: bool = False,
    method: str = "auto",
    lcfg: llm.LLMConfig | None = None,
    signals_fn: Callable[[str], dict[str, Any]] | None = None,
    answer_fn: Callable[[str, dict[str, Any], str], dict[str, Any]],
    asked: list[str] | None = None,
    keep_turns: int = 4,
) -> dict[str, Any]:
    mem = mem_mod.from_messages(history, known_models, known_codes, base=start, model_codes=model_codes)
    mem = mem_mod.update(mem, "user", question, known_models, known_codes, model_codes)
    rw = rewrite.rewrite(question, history, mem, method, lcfg)
    signals = signals_fn(rw["query"]) if signals_fn else None
    cl = clarify.check(question, mem, need_model=need_model, known_models=known_models, signals=signals, asked=asked)
    if cl["ask"]:
        return {"reply": cl["prompt"], "clarify": cl, "rewrite": rw, "memory": mem, "answered": False}
    hist = compress.history_for_prompt(history, mem, keep_turns=keep_turns)
    res = answer_fn(rw["query"], mem, hist["text"])
    mem = mem_mod.update(mem, "assistant", res.get("answer", ""), known_models, known_codes)
    return {"reply": res.get("answer", ""), "clarify": cl, "rewrite": rw, "memory": mem, "answered": True, "history_prompt": hist,
            "sources": res.get("sources"), "verify": res.get("verify"), "guard": res.get("guard"), "trace_id": res.get("trace_id"), "notice": res.get("notice")}  # fmt: skip
