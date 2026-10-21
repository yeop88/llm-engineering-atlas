"""RS5 생각 과정 검사 · RS6 추론 증류 데이터.

생각 글도 출력이다 — 기록하거나 사용자에게 보이면 개인정보 · 근거 밖 주장이 그대로 나간다. 풀이마다 본다:
- 생각-답 불일치: 생각의 마지막 결론(끝 300자의 마지막 조문 번호 · 수)과 최종 답이 다른가 — 다르면 답을 믿기 어렵다
- 근거 밖 주장: 생각에 나온 조문 번호가 자료 · 질문에 없음 / 수가 자료 · 집계 · 그 합이 아님
- 개인정보: 생각 글의 개인정보 탐지(G2)
- 지시 따르기: 생각 글에 인젝션 표현(G1) — 자료 속 숨은 지시를 생각이 받아 적었는지
그리고 각 표시가 정답률과 어떻게 엮이는지(표시된 풀이의 정답률 vs 아닌 풀이)를 함께 낸다 — 검사가 쓸모 있는 신호인지 보려고.

증류 데이터: 저장소에서 맞은 풀이(선택: 검증기 · 생각 검사도 통과)만 골라 SFT 행(messages)으로 만든다. 생각을 함께 넣을지(풀이 증류) ·
답만 넣을지(답 증류)를 고를 수 있어 두 방식을 같은 모델 · 같은 과제로 비교할 수 있다. 학습 · 평가는 후학습 화면(LoRA SFT)과
RLVR 평가(pt-<번호>)가 맡는다.
"""

import re
from typing import Any

from app.stages.guardrails import injection, pii
from app.stages.reasoning.select import NUM, evidence_text, graph_numbers
from app.stages.reasoning.solve import norm_final
from app.stages.rlvr import tasks as tk


def _conclusion(task: dict[str, Any], thinking: str) -> str | None:
    tail = thinking[-300:]
    if task["kind"] == "article":
        ms = list(tk.ARTICLE.finditer(tail))
        return (f"제{ms[-1].group(1)}조" + (f"의{ms[-1].group(2)}" if ms[-1].group(2) else "")) if ms else None
    if task["kind"] == "number":
        ns = NUM.findall(tail.replace(",", ""))
        return ns[-1] if ns else None
    return None


def audit_one(task: dict[str, Any], s: dict[str, Any], obs: dict[str, Any]) -> dict[str, Any]:
    th = s.get("thinking") or ""
    out: dict[str, Any] = {"task_id": task["id"], "i": s["i"], "correct": s["correct"], "has_thinking": bool(th)}
    if not th:
        return out | {"flags": []}
    flags = []
    concl = _conclusion(task, th)
    final = norm_final(task, s.get("final"))
    if concl is not None and final is not None and concl != final:
        flags.append("생각-답 불일치")
        out["conclusion"] = concl
    ev = evidence_text(obs) + "\n" + task["q"]
    ev_arts = {m.group(0).replace(" ", "") for m in tk.ARTICLE.finditer(ev)}
    ev_nums = {int(x) for x in NUM.findall(ev)} | graph_numbers(obs)
    bad_arts = sorted({m.group(0).replace(" ", "") for m in tk.ARTICLE.finditer(th)} - ev_arts)
    bad_nums = sorted({int(x) for x in NUM.findall(re.sub(r"제\s*\d+\s*조(의\s*\d+)?", "", th))} - ev_nums - {0, 1, 2, 3})
    if bad_arts or bad_nums:
        flags.append("근거 밖 주장")
        out["unsupported"] = {"articles": bad_arts[:5], "numbers": bad_nums[:5]}
    if hits := pii.counts(pii.scan(th)):
        flags.append("개인정보")
        out["pii"] = hits
    if injection.detect(th).get("suspicious"):
        flags.append("지시 따르기 의심")
    return out | {"flags": flags, "think_chars": len(th)}


def audit(items: list[dict[str, Any]], bank: dict[str, list[dict[str, Any]]], obs_of) -> dict[str, Any]:
    rows = []
    for t in items:
        for s in bank.get(t["id"]) or []:
            rows.append(audit_one(t, s, obs_of(t)))
    with_th = [r for r in rows if r["has_thinking"]]
    names = ["생각-답 불일치", "근거 밖 주장", "개인정보", "지시 따르기 의심"]
    flags = {}
    for f in names:
        yes = [r for r in with_th if f in r["flags"]]
        no = [r for r in with_th if f not in r["flags"]]
        flags[f] = {"n": len(yes), "rate": round(len(yes) / len(with_th), 4) if with_th else None,
                    "acc_flagged": round(sum(r["correct"] for r in yes) / len(yes), 3) if yes else None,
                    "acc_clean": round(sum(r["correct"] for r in no) / len(no), 3) if no else None}  # fmt: skip
    return {"n": len(rows), "with_thinking": len(with_th), "flags": flags, "examples": [r for r in with_th if r["flags"]][:30]}


def distill_rows(
    items: list[dict[str, Any]],
    bank: dict[str, list[dict[str, Any]]],
    prompt_of,
    include_thinking: bool,
    clean_only: bool,
    obs_of,
    max_think_chars: int = 2000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """과제마다 맞은 풀이 하나(생각이 가장 짧은 것 — 긴 풀이를 배우면 작은 모델도 길게 생각한다)."""
    rows, skipped = [], {"no_correct": 0, "flagged": 0}
    for t in items:
        good = [s for s in bank.get(t["id"]) or [] if s["correct"] and not s.get("forced")]
        if clean_only:
            ok = [s for s in good if not audit_one(t, s, obs_of(t))["flags"]]
            skipped["flagged"] += len(good) > 0 and not ok
            good = ok
        if not good:
            skipped["no_correct"] += 1
            continue
        s = min(good, key=lambda x: len(x.get("thinking") or ""))
        system, user, _ = prompt_of(t)
        th = (s.get("thinking") or "")[:max_think_chars]
        target = f"{th}\n\n{s['text']}".strip() if include_thinking and th else s["text"]
        rows.append({"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}, {"role": "assistant", "content": target}],
                     "_src": f"reasoning:{t['id']}", "type": t["type"]})  # fmt: skip
    rep = {"n": len(rows), "skipped": skipped, "include_thinking": include_thinking, "clean_only": clean_only,
           "mean_target_chars": round(sum(len(r["messages"][-1]["content"]) for r in rows) / len(rows), 1) if rows else None,
           "by_type": {ty: sum(r["type"] == ty for r in rows) for ty in sorted({r["type"] for r in rows})}}  # fmt: skip
    return rows, rep
