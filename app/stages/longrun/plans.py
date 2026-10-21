"""LR1 목표 분해 · 계획: 템플릿 계획과 LLM 계획, 그리고 둘 다 거치는 계획 검사.

LLM 계획을 그대로 믿지 않는 이유: 없는 행동 · 앞에 없는 단계를 가리키는 의존 · 승인 없는 발송이 섞인다. 검사가 고치는 것:
모르는 행동은 거절, 의존은 앞 단계만, 되돌릴 수 없는 행동 앞에는 승인 단계를 끼운다(맵 원칙: 되돌릴 수 없는 행동은 승인 후에).
"""

import json
from typing import Any

from app.core import llm
from app.stages.longrun.actions import ACTIONS

TEMPLATES: dict[str, dict[str, Any]] = {
    "as_trend_report": {
        "title": "AS 문의 동향 보고서",
        "goal": "지난 기간 AS 문의 동향을 집계하고, 많이 나온 오류 코드의 매뉴얼 조치를 찾아 보고서로 만들어 승인 후 발송",
        "params": {"days": 90, "collection_id": None},
        "steps": [
            {"name": "AS 문의 모으기", "action": "collect_as", "params": {"days": "{days}"}},
            {"name": "의도 · 제품 · 코드 집계", "action": "aggregate", "params": {"fields": ["intent", "product", "codes", "status"]}, "deps": [0]},
            {"name": "상위 오류 코드 조치 찾기", "action": "search", "params": {"collection_id": "{collection_id}", "from_counts": "codes", "top": 3}, "deps": [1]},
            {"name": "보고서 초안", "action": "draft_report", "params": {"sections": ["요약", "문의 분포", "주요 오류 코드와 조치", "다음 할 일"]}, "deps": [1, 2]},
            {"name": "완료 조건 검사", "action": "verify_report", "params": {}, "deps": [3]},
            {"name": "팀장 승인", "action": "approval", "params": {"who": "팀장"}, "deps": [4]},
            {"name": "보고서 발송", "action": "deliver", "params": {"target": "file"}, "deps": [5]},
        ],
        "criteria": ["sections", "numbers_grounded", "citations_valid", "supported", "approved", "delivered"],
    },
    "batch_answer": {
        "title": "질문 일괄 답변",
        "goal": "최근 서비스 질문을 모아 근거 답변을 다시 만들고 검증 결과를 남긴다",
        "params": {"days": 7, "collection_id": None, "limit": 10},
        "steps": [
            {"name": "질문 모으기", "action": "collect_questions", "params": {"days": "{days}", "limit": "{limit}"}},
            {"name": "일괄 답변", "action": "answer_batch", "params": {"collection_id": "{collection_id}"}, "deps": [0]},
        ],
        "criteria": [],
    },
}  # fmt: skip


def _fill(v: Any, params: dict[str, Any]) -> Any:
    if isinstance(v, str) and v.startswith("{") and v.endswith("}") and v[1:-1] in params:
        return params[v[1:-1]]
    if isinstance(v, dict):
        return {k: _fill(x, params) for k, x in v.items()}
    if isinstance(v, list):
        return [_fill(x, params) for x in v]
    return v


def from_template(key: str, params: dict[str, Any]) -> dict[str, Any]:
    t = TEMPLATES[key]
    p = t["params"] | {k: v for k, v in params.items() if v is not None}
    return {"planner": "template", "template": key, "title": t["title"], "goal": t["goal"], "params": p,
            "steps": [s | {"params": _fill(s.get("params") or {}, p), "deps": s.get("deps", [])} for s in t["steps"]], "criteria": t["criteria"]}  # fmt: skip


PLANNER_SYSTEM = (
    "당신은 업무 목표를 실행 계획으로 나누는 도구입니다. 아래 [행동]에 있는 action 만 씁니다. 단계마다 name · action · params · deps(앞 단계 번호, 0부터)를 "
    'JSON 으로만 출력합니다: {"steps": [...], "criteria": ["sections", "numbers_grounded", "citations_valid", "supported", "approved", "delivered" 중 필요한 것]}. '
    "되돌릴 수 없는 행동(irreversible) 앞에는 approval 단계를 둡니다."
)


def from_llm(lcfg: llm.LLMConfig, goal: str, params: dict[str, Any], allowed: list[str] | None = None) -> dict[str, Any]:
    acts = [a.spec() for a in ACTIONS.values() if not allowed or a.name in allowed]
    user = f"[행동]\n{json.dumps(acts, ensure_ascii=False)}\n\n[예시]\n{json.dumps(TEMPLATES['as_trend_report']['steps'], ensure_ascii=False)}\n\n[목표]\n{goal}\n[값]\n{json.dumps(params, ensure_ascii=False)}"
    data, res = llm.chat_json(lcfg, PLANNER_SYSTEM, user, max_tokens=1200, temperature=0.0)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("LLM 계획이 형식에 맞지 않습니다")
    return {
        "planner": "llm",
        "goal": goal,
        "params": params,
        "steps": data["steps"],
        "criteria": data.get("criteria") or [],
        "usage": res.get("usage"),
    }


def validate(plan: dict[str, Any], allowed: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """→ (고친 계획, 고친 · 거절한 이유). 모르는 행동이 있으면 ValueError — 실행할 수 없는 계획은 만들지 않는다."""
    notes: list[str] = []
    steps: list[dict[str, Any]] = []
    remap: dict[int, int] = {}
    for i, s in enumerate(plan.get("steps") or []):
        a = ACTIONS.get(str(s.get("action")))
        if a is None:
            raise ValueError(f"단계 {i}: 모르는 행동 '{s.get('action')}'")
        if allowed and a.name not in allowed:
            raise ValueError(f"단계 {i}: 범위(scope)에서 허용하지 않은 행동 '{a.name}'")
        deps = [remap[d] for d in s.get("deps") or [] if isinstance(d, int) and d in remap]
        if len(deps) != len(s.get("deps") or []):
            notes.append(f"단계 {i}: 앞에 없는 단계를 가리킨 의존을 뺐습니다")
        if a.irreversible and not any(steps[d]["action"] == "approval" for d in deps):
            steps.append({"name": f"{s.get('name') or a.title} 전 승인", "action": "approval", "params": {}, "deps": deps})
            notes.append(f"단계 {i}: 되돌릴 수 없는 '{a.name}' 앞에 승인을 끼웠습니다")
            deps = [len(steps) - 1]
        remap[i] = len(steps)
        steps.append({"name": str(s.get("name") or a.title)[:100], "action": a.name, "params": s.get("params") or {}, "deps": deps})
    if not steps:
        raise ValueError("단계가 없습니다")
    return plan | {"steps": steps}, notes
