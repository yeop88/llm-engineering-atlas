"""C3 대화 요약 메모리: 대화에서 중요한 사실(제품 · 오류 코드 · 증상 · 이미 안내한 조치 · 주제)을 뽑아 기억한다.

LLM 요약 대신 규칙으로 뽑는 이유: 메모리는 매 턴 갱신되므로 LLM 을 부르면 턴마다 수 초가 더 들고, 요약이 사실을 바꾸거나
빠뜨려도 알아채기 어렵다(근거 압축이 정답 문장을 버려 품질 −10 이었던 경험). 제품 · 코드처럼 목록이 있는 사실은 규칙이 정확하고,
메모리는 '대화 기록 전체'에서 매번 다시 계산할 수 있어 따로 저장하지 않아도 된다(저장하면 기록과 어긋날 수 있다).

개인정보는 메모리에 남기지 않는다(맵 원칙) — 증상 문장은 가린 뒤 넣는다.
"""

import re
from typing import Any

from app.core.korean import noun_phrases_many
from app.stages.guardrails import pii

SYMPTOM = re.compile(
    r"안\s*(돼|되|빠|켜|열|닫|나와)|새(요|고|는)|샙|소리|냄새|멈(춰|췄|춤)|떠요|뜨고|떠서|오류|에러|고장|진동|흔들|안\s*들어|작동"
)
STEP = re.compile(r"^\s*\d{1,2}[.)]\s*(.+)$")
CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,2}\d{1,2}|\d?[A-Za-z]{1,2}E|[A-Za-z]E)(?![A-Za-z0-9])")
MAX_SYMPTOMS, MAX_TRIED = 5, 8


def empty() -> dict[str, Any]:
    return {"product_model": "", "codes": [], "symptoms": [], "tried": [], "topic": [], "turns": 0}


def _norm_model(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s).upper()


def find_models(text: str, known_models: list[str] | tuple[str, ...]) -> list[str]:
    """알려진 모델명이 글에 있나 — 'WM200' · 'wm-200' 처럼 써도 'WM-200' 으로."""
    t = _norm_model(text or "")
    return [m for m in known_models if _norm_model(m) and _norm_model(m) in t]


def find_codes(text: str, known_codes: list[str] | tuple[str, ...]) -> list[str]:
    known = {c.upper(): c for c in known_codes}
    out = []
    for m in CODE.finditer(text or ""):
        c = known.get(m.group(1).upper())
        if c and c not in out:
            out.append(c)
    return out


# 주제로 쓰기엔 너무 일반적인 말 — '조건 · 며칠 · 얼마' 를 덧붙이면 검색만 흐려진다
GENERIC = {"조건", "며칠", "얼마", "경우", "방법", "오류", "문제", "질문", "정도", "때문", "이유", "어디", "무엇", "확인"}


def topic_of(text: str, k: int = 2) -> list[str]:
    """대화 주제: 첫 질문의 명사구 중 긴 것부터, 서로 겹치지 않게 k 개. 영문 · 숫자 조각(모델 · 코드는 따로 기억)과 일반적인 말은 뺀다."""
    phrases = [p for p in (noun_phrases_many([text])[0] or []) if re.search(r"[가-힣]", p) and p not in GENERIC]
    phrases = [" ".join(w for w in p.split() if re.search(r"[가-힣]", w) and w not in GENERIC) for p in phrases]
    out: list[str] = []
    for p in sorted({p for p in phrases if p}, key=len, reverse=True):
        if not any(p in o or o in p for o in out):
            out.append(p)
    return out[:k]


def update(
    mem: dict[str, Any], role: str, text: str, known_models=(), known_codes=(), model_codes: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """메시지 하나로 메모리를 갱신한 새 dict. 고객 말에서 제품 · 코드 · 증상 · 주제, 답변에서 이미 안내한 조치를 뽑는다.
    model_codes(모델 → 그 모델 매뉴얼의 코드)를 주면, 제품을 모를 때 코드가 한 모델에만 있으면 그 모델로 본다('건조기 d80' → DR-300)."""
    m = {k: (list(v) if isinstance(v, list) else v) for k, v in (mem or empty()).items()}
    if role == "user":
        m["turns"] = m.get("turns", 0) + 1
        models = find_models(text, known_models)
        if models:  # 고객이 다른 모델을 말하면 바꾼다 — 마지막에 말한 제품이 지금 이야기하는 제품
            m["product_model"] = models[-1]
        new_codes = find_codes(text, known_codes)
        for c in new_codes:
            if c not in m["codes"]:
                m["codes"].append(c)
        if not m["product_model"] and new_codes and model_codes:
            # 코드만으로 제품을 알 수 있으면 되묻지 않는다 — 여러 모델이 같은 코드를 쓰면(E 계열) 추정하지 않고 되묻는다
            cands = {mdl for mdl, cs in model_codes.items() if any(c in cs for c in new_codes)}
            if len(cands) == 1:
                m["product_model"], m["model_from_code"] = cands.pop(), True
        if SYMPTOM.search(text or ""):
            s = pii.mask(text.strip())[0][:120]
            if s not in m["symptoms"]:
                m["symptoms"] = (m["symptoms"] + [s])[-MAX_SYMPTOMS:]
        if not m["topic"]:  # 첫 질문의 명사구 = 대화 주제(짧은 후속 질문을 풀어 쓸 때 씀)
            m["topic"] = topic_of(text)
    else:
        for ln in (text or "").splitlines():
            if (st := STEP.match(ln)) and (step := re.sub(r"\s*\[\d+(?:[,，]\s*\d+)*\]", "", st.group(1)).strip()):
                if step not in m["tried"]:
                    m["tried"] = (m["tried"] + [step[:100]])[-MAX_TRIED:]
    return m


def from_messages(messages: list[dict[str, Any]], known_models=(), known_codes=(), base: dict[str, Any] | None = None,
                  model_codes: dict[str, list[str]] | None = None) -> dict[str, Any]:  # fmt: skip
    """대화 기록 전체에서 메모리를 다시 계산한다(저장하지 않고 매번)."""
    m = dict(base or empty())
    for msg in messages:
        m = update(m, msg.get("role", "user"), msg.get("text", ""), known_models, known_codes, model_codes)
    return m


def facts_text(mem: dict[str, Any]) -> str:
    """LLM 프롬프트 · 인계 요약에 넣는 짧은 사실 목록."""
    rows = []
    if mem.get("product_model"):
        rows.append(f"제품: {mem['product_model']}")
    if mem.get("codes"):
        rows.append(f"오류 코드: {', '.join(mem['codes'])}")
    if mem.get("symptoms"):
        rows.append("증상: " + " / ".join(mem["symptoms"][-3:]))
    if mem.get("tried"):
        rows.append("이미 안내한 조치: " + " / ".join(mem["tried"][-5:]))
    if mem.get("topic"):
        rows.append(f"대화 주제: {', '.join(mem['topic'])}")
    return "\n".join(rows)
