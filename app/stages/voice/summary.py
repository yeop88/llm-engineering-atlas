"""VC7 통화 요약 · 후처리: 전사 → 정해진 양식(문의 · 제품 · 코드 · 진단 · 안내한 조치 · 약속 · 다음 할 일) → 항목마다 전사와 맞는지 검증.

요약이 틀리면 다음 상담에서 잘못된 정보로 이어진다. 그래서 LLM 이 쓴 항목을 그대로 믿지 않고 전사로 확인한다:
제품 모델 · 오류 코드 · 날짜 · 시각은 전사에 같은 표기가 있어야 하고(정확 일치), 문장 항목(진단 · 조치 · 약속)은 글자 3-gram 이
전사의 한 발화와 충분히 겹쳐야 한다(근거 일치 검증과 같은 방식). 맞지 않는 항목은 '확인 필요'로 표시해 상담원이 고친다.
LLM 이 없거나 실패하면 규칙 요약(분류 · 코드 · 마지막 안내)으로 대신한다.
"""

import re
from typing import Any

from app.core import llm
from app.stages.as_service import triage

FIELDS = {
    "inquiry": "고객 문의 한 문장",
    "product_model": "제품 모델명(전사에 나온 그대로, 없으면 빈 글)",
    "codes": "오류 코드 목록",
    "diagnosis": "진단(원인 추정) 한 문장",
    "actions": "상담에서 안내한 조치 목록",
    "resolved": "해결됨이면 true, 아니면 false",
    "promise": "고객과 한 약속(방문 일정 · 회신 등), 없으면 빈 글",
    "next": "다음 할 일 목록",
}
SYSTEM = "통화 전사를 상담 기록 양식으로 정리합니다. 전사에 없는 내용은 쓰지 않습니다. 반드시 JSON 만 출력합니다."
DATE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}/\d{1,2}|(내일|모레|다음\s*주|이번\s*주)\s*[가-힣]*요일?|오전|오후|\d{1,2}\s*시")


def transcript_text(turns: list[dict[str, Any]]) -> str:
    return "\n".join(f"{'고객' if t['role'] == 'customer' else '상담'}: {t['text']}" for t in turns if t.get("text"))


def _grams(s: str) -> set[str]:
    s = re.sub(r"\s", "", s)
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _support(value: str, turns: list[dict[str, Any]]) -> float:
    g = _grams(value)
    if not g:
        return 1.0
    return max((len(g & _grams(t["text"])) / len(g) for t in turns if t.get("text")), default=0.0)


def verify(summary: dict[str, Any], turns: list[dict[str, Any]], min_support: float = 0.4) -> dict[str, Any]:
    full = re.sub(r"\s", "", transcript_text(turns)).upper()
    checks = []

    def exact(field: str, v: str) -> None:
        checks.append({"field": field, "value": v, "ok": re.sub(r"\s", "", v).upper() in full, "how": "표기 일치"})

    if summary.get("product_model"):
        exact("product_model", summary["product_model"])
    for c in summary.get("codes") or []:
        exact("codes", str(c))
    for field in ("diagnosis", "promise"):
        if v := summary.get(field):
            s = _support(v, turns)
            checks.append({"field": field, "value": v, "ok": s >= min_support, "support": round(s, 2), "how": "글자 겹침"})
            for d in DATE.findall(v) if field == "promise" else []:
                d = d if isinstance(d, str) else d[0]
                if d:
                    exact("promise", d)
    for a in summary.get("actions") or []:
        s = _support(str(a), turns)
        checks.append({"field": "actions", "value": a, "ok": s >= min_support, "support": round(s, 2), "how": "글자 겹침"})
    bad = [c for c in checks if not c["ok"]]
    return {"checks": checks, "ok": not bad, "n": len(checks), "n_bad": len(bad)}


def rule_summary(turns: list[dict[str, Any]], memory: dict[str, Any]) -> dict[str, Any]:
    cust = [t["text"] for t in turns if t["role"] == "customer"]
    agent = [t["text"] for t in turns if t["role"] != "customer"]
    codes = list(dict.fromkeys(c for t in cust for c in triage.codes(t)))
    return {"inquiry": cust[0] if cust else "", "product_model": memory.get("product_model", ""), "codes": codes, "diagnosis": "",
            "actions": agent[-2:], "resolved": False, "promise": "", "next": ["상담원 확인"], "by": "rule"}  # fmt: skip


def summarize(turns: list[dict[str, Any]], memory: dict[str, Any], lcfg: llm.LLMConfig | None) -> dict[str, Any]:
    if lcfg is None or not turns:
        s = rule_summary(turns, memory)
    else:
        schema = "{" + ", ".join(f'"{k}": {v}' for k, v in FIELDS.items()) + "}"
        try:
            data, _ = llm.chat_json(lcfg, SYSTEM, f"양식: {schema}\n\n전사:\n{transcript_text(turns)}", max_tokens=600, temperature=0.0)
            s = {k: data.get(k, [] if k in ("codes", "actions", "next") else "") for k in FIELDS} | {"by": "llm"}
            for k in ("codes", "actions", "next"):
                if isinstance(s[k], str):
                    s[k] = [s[k]] if s[k] else []
        except (llm.LLMError, ValueError, AttributeError) as exc:
            s = rule_summary(turns, memory) | {"llm_error": str(exc)[:200]}
    v = verify(s, turns)
    # 통화를 만들 때 받은 제품 모델(고객 기록)은 전사에 없어도 맞는 정보다 — 비어 있으면 채우고 '통화 정보'로 표시
    if not s.get("product_model") and memory.get("product_model"):
        s["product_model"] = memory["product_model"]
        v["checks"].append({"field": "product_model", "value": s["product_model"], "ok": True, "how": "통화 정보"})
        v["n"] += 1
    return {"summary": s, "verify": v}
