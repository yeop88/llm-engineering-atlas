"""C1 대화 맥락 질의 재작성: '그거 말고 다른 모델은요?' 같은 후속 질문을 혼자 읽혀도 되는 검색 질문으로 바꾼다.

검색은 앞 대화를 모른다. '필터는 어디 있어요?' 를 그대로 검색하면 모든 제품의 필터가 나오고, '그럼 수습 기간에도요?' 는
무엇을 묻는지조차 없다. 그래서 검색 전에 질문을 풀어 쓴다(4 검색 향상의 질의 재작성을 대화로 넓힌 것).

방법(평가에서 비교):
- none: 그대로(기준)
- history: 앞 고객 말을 이어 붙임 — 가장 단순하지만 주제가 바뀌면 옛 주제가 검색을 끌고 간다
- rule: 메모리의 제품 · 대화 주제 중 질문에 없는 것만 덧붙임 — LLM 없이, 지어내지 않음
- llm: 대화 기록 + 메모리로 LLM 이 다시 씀 — 가장 자연스럽지만 느리고, 엉뚱하게 바꿀 수 있어 결과를 검사한다
- auto: 앞 대화에 기대는 질문일 때만 llm(LLM 이 없으면 rule) — 독립 질문은 바꾸지 않는다(바꿀수록 망가질 기회만 늘어서)
"""

import re
from typing import Any

from app.core import llm
from app.core.korean import nouns_many
from app.stages.conversation import memory as mem_mod

# 앞 대화를 가리키는 말 — 이게 있으면 질문만으로는 무엇을 묻는지 모른다
DEICTIC = re.compile(
    r"그거|그것|이거|이것|저거|저것|거기|여기서|그럼|그러면|그렇다면|아까|방금|위에서|앞에서|그건|이건|그때|해당|그대로|"
    r"다른\s*(모델|제품|거|것|경우|방법)|(^|\s)그\s+[가-힣]+|이\s*(모델|제품|경우)|"
    r"^(그리고|또|그런데|근데)\b"
)
# 말을 줄인 끝맺음 — '신입은요?' · '야간에도 똑같나요?' · '퇴사하면요?' 는 앞 질문의 주제를 이어받는다
ELLIPSIS = re.compile(r"[가-힣](은요|는요|이면요|면요|에도|도)\b|(은요|는요|면요)\??\s*$")
METHODS = ("none", "history", "rule", "llm", "auto")
SYSTEM = (
    "당신은 상담 대화의 마지막 질문을 검색용 질문으로 다시 쓰는 도구입니다. 앞 대화 없이도 무엇을 묻는지 알 수 있게, "
    "앞 대화에 나온 제품 · 대상 · 조건을 채워 한 문장으로 쓰세요. 앞 대화에 없는 사실을 지어내지 말고, 질문이 이미 혼자 "
    "이해되면 그대로 두세요. 다시 쓴 질문만 출력합니다."
)


def depends(question: str, history: list[dict[str, Any]], mem: dict[str, Any] | None = None) -> tuple[bool, str]:
    """앞 대화에 기대는 질문인가 → (기대나, 이유)."""
    if not history:
        return False, "첫 질문"
    if DEICTIC.search(question or ""):
        return True, "앞 대화를 가리키는 말"
    if ELLIPSIS.search(question or ""):
        return True, "말을 줄인 끝맺음"
    nouns = nouns_many([question])[0]
    if len(nouns) <= 1:  # '필터는 어디 있어요?' — 무엇의 필터인지 없음
        return True, "대상이 빠진 짧은 질문"
    if (pm := (mem or {}).get("product_model")) and not mem_mod.find_models(question, [pm]) and len(nouns) <= 3:
        return True, "제품이 빠진 질문"  # '필터 청소는 어떻게 해요?' — 제품마다 답이 다르다
    return False, "혼자 읽히는 질문"


def by_history(question: str, history: list[dict[str, Any]], turns: int = 2) -> str:
    prev = [m["text"] for m in history if m.get("role") == "user"][-turns:]
    return " ".join(prev + [question])


def by_rule(question: str, mem: dict[str, Any]) -> str:
    """메모리의 제품 · 주제 중 질문에 없는 것만 앞에 붙인다(지어내지 않음)."""
    add = []
    if (pm := mem.get("product_model")) and not mem_mod.find_models(question, [pm]):
        add.append(pm)
    q_nouns = set(nouns_many([question])[0])
    add += [t for t in mem.get("topic") or [] if not set(t.split()) & q_nouns][:2]
    return f"{' '.join(add)} {question}".strip() if add else question


def _history_text(history: list[dict[str, Any]], turns: int = 6) -> str:
    rows = []
    for m in history[-turns:]:
        who = "고객" if m.get("role") == "user" else "상담"
        rows.append(f"{who}: {re.sub(r'\s+', ' ', m.get('text', ''))[:300]}")
    return "\n".join(rows)


def by_llm(lcfg: llm.LLMConfig, question: str, history: list[dict[str, Any]], mem: dict[str, Any]) -> str | None:
    """LLM 재작성. 결과가 비었거나 너무 길면(설명을 붙임) None — 부르는 쪽이 규칙으로 물러난다."""
    facts = mem_mod.facts_text(mem)
    user = f"[앞 대화]\n{_history_text(history)}\n\n" + (f"[기억한 사실]\n{facts}\n\n" if facts else "") + f"[마지막 질문]\n{question}"
    r = llm.chat(lcfg, SYSTEM, user, 120, 0.0)
    out = re.sub(r"\s+", " ", (r["text"] or "").strip().strip('"').strip()).removeprefix("다시 쓴 질문:").strip()
    if not out or len(out) > max(150, len(question) * 5):
        return None
    return out


def rewrite(question: str, history: list[dict[str, Any]], mem: dict[str, Any], method: str = "auto",
            lcfg: llm.LLMConfig | None = None) -> dict[str, Any]:  # fmt: skip
    """→ {"query", "method"(실제로 쓴 방법), "changed", "depends", "reason"}."""
    dep, reason = depends(question, history, mem)
    if method == "none" or (method == "auto" and not dep):
        return {"query": question, "method": "none", "changed": False, "depends": dep, "reason": reason}
    if method == "history":
        q = by_history(question, history)
        return {"query": q, "method": "history", "changed": q != question, "depends": dep, "reason": reason}
    if method in ("llm", "auto") and lcfg is not None:
        try:
            q = by_llm(lcfg, question, history, mem)
        except llm.LLMError:
            q = None
        if q:
            return {"query": q, "method": "llm", "changed": q != question, "depends": dep, "reason": reason}
    q = by_rule(question, mem)
    return {"query": q, "method": "rule", "changed": q != question, "depends": dep, "reason": reason}
