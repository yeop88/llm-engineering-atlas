"""LR6 결과 검증 · 완료 판정: '다 했다'는 에이전트의 말이 아니라 결과 검사로 끝을 정한다.

검사 항목(계획의 criteria): 필수 절이 있나 · 보고서의 숫자가 모두 집계에 있나(지어낸 숫자) · 인용 번호가 자료 범위 안인가 ·
자료 문장과의 근거 일치가 기준 이상인가 · 승인을 받았나 · 발송했나. 하나라도 못 미치면 '완료'가 아니라 '검토 필요'로 끝난다.
"""

import re
from typing import Any

from app.stages.longrun.actions import NUM, Ctx, _first_input
from app.stages.rag import answer

DEFAULT = ["sections", "numbers_grounded", "citations_valid", "supported"]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUM.findall(text)}


def check(report: str, sections: list[str], counts: dict[str, Any] | None, total: Any, sources: list[dict[str, Any]],
          criteria: list[str], min_support: float = 0.6) -> dict[str, Any]:  # fmt: skip
    items: list[dict[str, Any]] = []
    if "sections" in criteria:
        missing = [s for s in sections if not re.search(rf"^#+\s*{re.escape(s)}\s*$", report, re.M)]
        items.append(
            {"key": "sections", "ok": not missing, "detail": f"없는 절: {', '.join(missing)}" if missing else f"절 {len(sections)}개"}
        )
    if "numbers_grounded" in criteria:
        allowed = {str(total)} | {str(v) for c in (counts or {}).values() for v in c.values()}
        allowed |= {
            re.sub(r"\D", "", k) for c in (counts or {}).values() for k in c if re.search(r"\d", k)
        }  # 코드 · 모델 이름 속 숫자(E4 · WM-200)
        for s in sources:  # 자료(매뉴얼)에 있는 숫자는 그 자료를 인용한 것
            allowed |= _numbers(s.get("text") or "")
        made = sorted(
            n for n in _numbers(re.sub(r"\[S\d+\]", "", report)) if n not in allowed and len(n) > 0 and not re.fullmatch(r"20\d\d", n)
        )
        items.append(
            {
                "key": "numbers_grounded",
                "ok": not made,
                "detail": f"집계 · 자료에 없는 숫자: {', '.join(made[:10])}" if made else "모든 숫자가 집계 · 자료에서",
            }
        )
    if "citations_valid" in criteria:
        cited = {int(x) for x in re.findall(r"\[S(\d+)\]", report)}
        bad = sorted(c for c in cited if not 1 <= c <= len(sources))
        items.append({"key": "citations_valid", "ok": not bad, "detail": f"없는 자료 번호: {bad}" if bad else f"인용 {len(cited)}개"})
    if "supported" in criteria and sources:
        v = answer.verify(re.sub(r"\[S(\d+)\]", lambda m: f"[{m.group(1)}]", report), sources)
        r = v.get("supported_ratio")
        items.append({"key": "supported", "ok": r is None or r >= min_support, "detail": f"근거 일치 {r} (기준 {min_support})", "value": r})
    return {"ok": all(i["ok"] for i in items), "items": items}


def verify_report(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    report = _first_input(ctx, "report") or ""
    sections = _first_input(ctx, "sections") or []
    out = check(report, sections, _first_input(ctx, "counts"), _first_input(ctx, "total"), _first_input(ctx, "sources") or [],
                p.get("criteria") or DEFAULT, float(p.get("min_support") or 0.6))  # fmt: skip
    if not out["ok"] and p.get("strict"):
        raise ValueError("완료 조건 미달: " + "; ".join(i["detail"] for i in out["items"] if not i["ok"]))
    return out
