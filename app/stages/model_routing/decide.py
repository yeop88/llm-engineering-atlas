"""MR1~MR6 라우팅 결정: 요청 분류 → 위험도 → 품질 하한 → 지연 · 예산 → 후보 → 점수로 선택.

LLM 맵의 라우터(6)는 '쉬움 · 어려움' 두 갈래였다. 실제 서비스는 소형 · 대형 · 추론 · VLM · 음성 · 로컬과 RAG · GraphRAG · SQL · 에이전트 ·
사람 승인을 요청마다 골라야 한다. 결정은 규칙으로 먼저 하고(싸고 설명 가능), 확신이 낮을 때만 LLM 에 묻는다 — 분류 비용이 라우팅 이득을
먹지 않게. 위험도는 비용보다 먼저다: 고위험(법률 · 의료 · 금전 · 개인정보 · 외부 행동)은 후보를 강한 모델로 좁히고 사람 승인을 붙인다.
점수 = Σ 가중치 × 정규화한 지표(품질 · 근거 · 지연 · 비용 · 신뢰성). 가중치 기본값은 0.35 · 0.20 · 0.15 · 0.15 · 0.15 이고 업무마다 바꾼다.
후보의 품질 · 지연 · 비용은 보정 작업(calibrate)이 같은 평가 세트로 잰 값 — 모르면 종류별 기본값을 쓰고 그 사실을 표시한다.
"""

import re
from typing import Any

from app.core import llm
from app.stages.guardrails import injection

TYPES = {
    "lookup": "사실 검색", "summary": "요약", "aggregate": "집계 · 필터", "relation": "관계 탐색", "trend": "전체 추세",
    "reasoning": "깊은 추론", "code": "코드", "image": "이미지 질문", "voice": "음성 대화", "action": "도구 실행",
}  # fmt: skip
# 작업 유형 → 실행 경로(이 앱의 맵). 경로 실행은 서비스 답변(RAG)이 기본이고 나머지는 추천으로 남긴다(라우팅 기록에서 채점)
PATH = {"lookup": "rag", "summary": "rag", "aggregate": "sql", "relation": "graphrag", "trend": "community", "reasoning": "rag+think",
        "code": "agent", "image": "vlm+rag", "voice": "rag-fast", "action": "agent+approval"}  # fmt: skip
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("action", re.compile(r"보내 ?줘|예약해|접수해|결제|주문해|삭제해|등록해|발송")),
    ("code", re.compile(r"코드|함수|버그|에러 로그|traceback|SQL 문|파이썬|```")),
    ("aggregate", re.compile(r"몇 (?:건|개|명|번)|합계|평균|총 ?\d*|가장 많|비율|월별|연도별|순위|top ?\d", re.I)),
    ("relation", re.compile(r"관계|연결|경로|누가 .*누구|어떤 .*와 관련|사이의|인용한|참조하는")),
    ("trend", re.compile(r"전체 ?동향|추세|흐름|전반적|요즘 .*경향|주요 주제")),
    ("summary", re.compile(r"요약|정리해|간추려|한 줄로")),
    ("reasoning", re.compile(r"왜|이유|비교|차이|만약|어떻게 되나|따져|판단|계산|각각|위험한 것")),
]
RISK = [
    ("legal", re.compile(r"법|조항|계약|소송|판례|위반|처벌|해고|임대차")),
    # "약" 한 글자는 "계약 · 요약" 에도 있어 의료로 잘못 잡았다 — 낱말로만
    ("medical", re.compile(r"처방|약물|약국|복용|병원|치료|수술|질병")),
    ("finance", re.compile(r"결제|송금|환불|대출|투자|계좌|카드")),
    ("pii", re.compile(r"주민(?:등록)?번호|여권|계좌번호|비밀번호|주소|전화번호")),
    ("external", re.compile(r"보내 ?줘|발송|예약해|접수해|삭제해|주문해")),
]
QUALITY_FLOOR = {"low": 0.6, "mid": 0.75, "high": 0.9}
WEIGHTS = {"quality": 0.35, "grounded": 0.20, "latency": 0.15, "cost": 0.15, "reliability": 0.15}
CHANNEL_BUDGET_MS = {
    "voice": 1500,
    "video": 2000,
    "web_chat": 4000,
    "kakao": 5000,
    "messenger": 15000,
    "sms": 30000,
    "email": 600000,
    "api": 10000,
}
# 후보 종류별 기본값(보정 전) — 상대값일 뿐이라 화면에 '추정'으로 표시한다
KIND_DEFAULT = {"small": (0.62, 900, 0.2), "large": (0.75, 3500, 1.0), "reasoning": (0.82, 12000, 3.0), "vlm": (0.7, 5000, 1.5),
                "speech": (0.6, 700, 0.5), "local": (0.68, 2500, 0.3), "api": (0.85, 2500, 5.0)}  # fmt: skip


def classify(text: str, has_image: bool = False, channel: str = "api", cfg: llm.LLMConfig | None = None) -> dict[str, Any]:
    """→ {type, label, modality, by, why}. 모달리티가 정해 주는 것(사진 · 음성)을 먼저, 그다음 규칙, 규칙이 아무것도 못 찾고 cfg 가 있으면 LLM."""
    if has_image:
        return {"type": "image", "label": TYPES["image"], "modality": "image", "by": "modality", "why": "사진이 붙은 질문"}
    if channel in ("voice", "video"):
        base = {"modality": "audio", "by": "modality", "why": f"{channel} 채널 — 지연 예산이 짧다"}
        t = next((k for k, rx in RULES if rx.search(text or "")), "voice")
        return base | {"type": "voice" if t in ("lookup", "summary") else t, "label": TYPES["voice" if t in ("lookup", "summary") else t]}
    for k, rx in RULES:
        if m := rx.search(text or ""):
            return {"type": k, "label": TYPES[k], "modality": "text", "by": "rule", "why": f"'{m.group(0)}'"}
    if cfg is not None and len(text or "") > 40:
        # 규칙이 못 찾은 긴 질문만 LLM 에 — 짧은 질문은 대개 사실 검색이라 묻는 비용이 아깝다
        try:
            data, _ = llm.chat_json(
                cfg, '질문의 작업 유형 하나를 고릅니다. JSON 만: {"type": "' + "|".join(TYPES) + '"}', text, max_tokens=40, temperature=0.0
            )
            t = (data or {}).get("type")
            if t in TYPES:
                return {"type": t, "label": TYPES[t], "modality": "text", "by": "llm", "why": "규칙 없음 → LLM"}
        except llm.LLMError, ValueError, AttributeError:
            pass
    return {"type": "lookup", "label": TYPES["lookup"], "modality": "text", "by": "default", "why": "해당 규칙 없음 — 사실 검색으로"}


def risk(text: str) -> dict[str, Any]:
    """→ {level, domains, injection, require_strong, require_human}. 외부 행동 · 인젝션 의심은 사람 승인."""
    domains = [d for d, rx in RISK if rx.search(text or "")]
    inj = injection.detect(text or "")
    level = "high" if ("external" in domains or inj["suspicious"] or len(domains) >= 2) else ("mid" if domains else "low")
    return {"level": level, "domains": domains, "injection": inj["suspicious"], "require_strong": level == "high",
            "require_human": "external" in domains or inj["suspicious"]}  # fmt: skip


def floor(task: str, level: str) -> float:
    """품질 하한: 위험도가 기본, 깊은 추론 · 집계는 한 단계 높게(틀리면 숫자가 틀림)."""
    f = QUALITY_FLOOR[level]
    return round(min(0.95, f + (0.05 if task in ("reasoning", "aggregate") else 0.0)), 2)


def _metric(c: dict[str, Any], task: str) -> tuple[float, float, float, bool]:
    """→ (품질, p95 ms, 호출 비용, 잰 값인가)."""
    q, p95, cost = KIND_DEFAULT.get(c.get("kind", "large"), KIND_DEFAULT["large"])
    measured = c.get("quality", {})
    qv = measured.get(task, measured.get("all"))
    return (qv if qv is not None else q, c.get("p95_ms") or p95, c.get("cost") if c.get("cost") is not None else cost, qv is not None)


def choose(cands: list[dict[str, Any]], task: dict[str, Any], rk: dict[str, Any], budget_ms: float, weights: dict[str, float] | None = None,
           max_cost: float | None = None) -> dict[str, Any]:  # fmt: skip
    """후보 거르기(모달리티 · 지연 · 비용 · 위험) → 점수 → 정렬. 하한을 넘는 후보가 없으면 품질이 가장 높은 것(승격 사슬의 끝은 사람)."""
    w = WEIGHTS | (weights or {})
    need = {"image": "image", "voice": "audio"}.get(task["type"])
    fl = floor(task["type"], rk["level"])
    rows = []
    for c in cands:
        q, p95, cost, measured = _metric(c, task["type"])
        why = []
        if need and need not in c.get("modalities", ["text"]):
            why.append(f"{need} 못 받음")
        if p95 > budget_ms:
            why.append(f"지연 {int(p95)}ms > 예산 {int(budget_ms)}")
        if max_cost is not None and cost > max_cost:
            why.append("비용 상한 초과")
        if rk["require_strong"] and c.get("kind") in ("small", "speech"):
            why.append("고위험 — 작은 모델 제외")
        rows.append({"name": c["name"], "kind": c.get("kind"), "quality": round(q, 3), "p95_ms": int(p95), "cost": round(cost, 3), "measured": measured,
                     "reliability": c.get("reliability", 0.95), "grounded": c.get("grounded", q), "excluded": why, "meets_floor": q >= fl})  # fmt: skip
    ok = [r for r in rows if not r["excluded"]]
    if ok:
        lat = [r["p95_ms"] for r in ok]
        cst = [r["cost"] for r in ok]

        def inv(v: float, vs: list[float]) -> float:  # 작을수록 좋은 지표를 0~1 로(가장 좋은 것 1)
            lo, hi = min(vs), max(vs)
            return 1.0 if hi == lo else (hi - v) / (hi - lo)

        for r in ok:
            r["score"] = round(w["quality"] * r["quality"] + w["grounded"] * r["grounded"] + w["latency"] * inv(r["p95_ms"], lat)
                               + w["cost"] * inv(r["cost"], cst) + w["reliability"] * r["reliability"], 4)  # fmt: skip
        # 하한을 넘는 후보가 앞 — 그 안에서 점수 순. 하한을 넘는 것이 없으면 점수 순(승격으로 보완)
        ok.sort(key=lambda r: (not r["meets_floor"], -r["score"]))
    chain = [r["name"] for r in ok] + ["사람"]
    return {"floor": fl, "budget_ms": budget_ms, "weights": w, "candidates": rows, "chain": chain, "pick": ok[0]["name"] if ok else None,
            "path": PATH[task["type"]], "human_approval": rk["require_human"]}  # fmt: skip


def decide(text: str, cands: list[dict[str, Any]], channel: str = "api", has_image: bool = False, budget_ms: float | None = None,
           weights: dict[str, float] | None = None, max_cost: float | None = None, cfg: llm.LLMConfig | None = None) -> dict[str, Any]:  # fmt: skip
    task = classify(text, has_image, channel, cfg)
    rk = risk(text)
    b = budget_ms or CHANNEL_BUDGET_MS.get(channel, CHANNEL_BUDGET_MS["api"])
    return {"task": task, "risk": rk, "channel": channel} | choose(cands, task, rk, b, weights, max_cost)
