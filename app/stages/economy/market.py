"""EC1~EC4 · EC6 · EC8 고르기 · 위임 · 승인 · 검증 · 분쟁, 그리고 규칙을 깨려는 시나리오로 시험.

흐름: 서비스 찾기(기능으로) → 비교(가격 · 품질 · 납기 · 환불 조건, 요구를 못 맞추는 것은 뺌) → 위임 검사(기능 · 상대 · 건당 · 월 한도 · 기한)
→ 승인(금액이 크거나 처음 보는 상대면 사람) → 에스크로 묶기 → 결과 받기 → 검증(받기 기준) → 정산 또는 환불 · 분쟁.

'승인 없는 거래 0 · 예산 초과 0'은 정상 흐름이 아니라 깨려는 흐름에서 지켜져야 의미가 있다. 그래서 시나리오에 에이전트의 실수 ·
공격을 섞는다: 한도 넘는 구매, 위임 밖 상대, 같은 요청 두 번(이중 지불), 승인 뒤 가격이 바뀜(승인한 것과 다른 것을 결제),
결과를 안 주는 판매자, 엉터리 결과. 같은 시나리오를 '규칙 없는 에이전트'(찾은 것 중 가장 싼 것을 바로 결제)와 나란히 돌린다.
"""

import json
import random
from datetime import date
from pathlib import Path
from typing import Any

from app.stages.economy.ledger import Ledger

PRESET = Path(__file__).parent / "presets" / "market.json"


def preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def discover(services: list[dict[str, Any]], skill: str) -> list[dict[str, Any]]:
    """EC1: 기능(skill)으로 찾기 — 에이전트 카드의 기술 목록과 같은 자리."""
    return [s for s in services if s["skill"] == skill]


def compare(cands: list[dict[str, Any]], need: dict[str, Any]) -> list[dict[str, Any]]:
    """EC2: 요구(최소 품질 · 최대 납기 · 환불 필요)를 못 맞추면 빼고, 남은 것을 '품질 대비 가격'으로 줄 세운다. 뺀 이유를 남긴다."""
    out = []
    for s in cands:
        why = []
        if s["quality"] < need.get("min_quality", 0):
            why.append(f"품질 {s['quality']} < {need['min_quality']}")
        if s["deliver_s"] > need.get("max_deliver_s", 10**9):
            why.append(f"납기 {s['deliver_s']}초 > {need['max_deliver_s']}초")
        if need.get("refund_required") and s["refund"] == "환불 없음":
            why.append("환불 없음")
        out.append(s | {"eligible": not why, "excluded_why": why, "value": round(s["quality"] / max(1, s["price"]) * 10000, 3)})
    return sorted(out, key=lambda x: (not x["eligible"], -x["value"]))


def check_mandate(m: dict[str, Any], s: dict[str, Any], amount: int, spent: int, today: str) -> list[str]:
    """EC3: 위임 범위 — 기능 · 상대 허용 목록 · 건당 · 월 한도 · 기한. 어긴 것 목록(비면 통과)."""
    v = []
    if s["skill"] not in m["skills"]:
        v.append(f"위임 밖 기능 {s['skill']}")
    if s["id"] not in m["allow"]:
        v.append(f"허용 목록 밖 상대 {s['name']}")
    if amount > m["per_tx"]:
        v.append(f"건당 한도 {m['per_tx']} 초과({amount})")
    if spent + amount > m["monthly"]:
        v.append(f"월 한도 {m['monthly']} 초과(누적 {spent + amount})")
    if today > m["expires"]:
        v.append("위임 기한 지남")
    return v


def needs_approval(m: dict[str, Any], s: dict[str, Any], amount: int, seen: set[str]) -> list[str]:
    """EC4: 사람 승인이 필요한 이유 — 금액이 기준을 넘음 · 처음 거래하는 상대."""
    why = []
    if amount > m["approve_over"]:
        why.append(f"{m['approve_over']}원 초과")
    if s["id"] not in seen:
        why.append("처음 거래하는 상대")
    return why


def deliver(s: dict[str, Any], rnd: random.Random) -> dict[str, Any]:
    """흉내 판매자: reliability 확률로 납품, quality 확률로 받기 기준을 넘는 결과."""
    if rnd.random() > s["reliability"]:
        return {"delivered": False}
    return {"delivered": True, "good": rnd.random() < s["quality"]}


def verify(result: dict[str, Any]) -> dict[str, Any]:
    """EC6 받기 기준: 납품됐고 결과가 기준을 넘는가(번역 · OCR 은 표본 검사, 배송은 접수 번호 확인 — 흉내는 good 값으로)."""
    if not result["delivered"]:
        return {"pass": False, "reason": "납품 안 됨(기한 넘김)"}
    return {"pass": bool(result["good"]), "reason": "기준 통과" if result["good"] else "받기 기준 미달"}


def refund_amount(s: dict[str, Any], amount: int, reason: str) -> int:
    """EC8: 환불 조건대로 — 전액 · 50% · 없음. 납품 자체가 없으면 조건과 상관없이 전액(이행이 없었음)."""
    if reason.startswith("납품 안 됨"):
        return amount
    return {"불합격 시 전액": amount, "미접수 시 전액": amount, "불합격 시 50%": amount // 2}.get(s["refund"], 0)


TASKS = [("translate", {"min_quality": 0.75, "max_deliver_s": 900, "refund_required": True}, 1),
         ("ocr", {"min_quality": 0.85, "refund_required": True}, 20),
         ("shipping", {"min_quality": 0.9, "refund_required": True}, 1)]  # fmt: skip
ATTACKS = ("over_tx", "over_month", "off_list", "double", "price_swap", "no_delivery", "bad_result")


def run(n: int = 40, seed: int = 0, guarded: bool = True, approve_rate: float = 0.9) -> dict[str, Any]:
    """n 건의 일(정상 + 공격 섞임)을 처리 → 지킨 것 · 어긴 것 · 돈의 흐름. guarded=False 는 규칙 없는 에이전트."""
    p = preset()
    m, services = p["mandate"], p["services"]
    rnd = random.Random(seed)
    L = Ledger()
    L.fund("wallet", 2_000_000)  # 지갑은 넉넉히 — 막는 것이 잔액이 아니라 위임 · 승인이어야 규칙을 시험한다
    spent, seen = 0, set()
    ev: list[dict[str, Any]] = []
    stats = {"unapproved_paid": 0, "over_budget": 0, "off_mandate_paid": 0, "double_paid": 0, "paid_unverified": 0, "lost_to_bad": 0, "refunded": 0,
             "blocked": 0, "approvals_asked": 0, "spent": 0}  # fmt: skip
    today = date(2026, 10, 23).isoformat()
    for i in range(n):
        skill, need, qty = rnd.choice(TASKS)
        attack = rnd.choice(ATTACKS) if rnd.random() < 0.5 else None
        cands = compare(discover(services, skill), need)
        pick = next((c for c in cands if c["eligible"]), None) if guarded else min(cands, key=lambda c: c["price"])
        if attack == "off_list":
            pick = next((s for s in services if s["skill"] == skill and s["id"] not in m["allow"]), pick)
        if pick is None:
            ev.append({"i": i, "skill": skill, "result": "맞는 서비스 없음"})
            continue
        amount = pick["price"] * qty * (4 if attack == "over_tx" else 1)
        if attack == "over_month":
            amount = max(amount, m["monthly"] - spent + 1000)
        tx = f"t{i}"
        rec = {"i": i, "skill": skill, "service": pick["name"], "amount": amount, "attack": attack}
        if guarded:
            viol = check_mandate(m, pick, amount, spent, today)
            if viol:
                stats["blocked"] += 1
                ev.append(rec | {"result": "막음", "why": viol})
                continue
            why = needs_approval(m, pick, amount, seen)
            if why:
                stats["approvals_asked"] += 1
                if rnd.random() > approve_rate:
                    ev.append(rec | {"result": "사람이 거절", "why": why})
                    continue
            approved_amount = amount
            if attack == "price_swap":
                amount = int(amount * 1.6)  # 승인 뒤 판매자가 값을 올림 — 승인한 금액과 다르면 다시 승인
                if amount != approved_amount:
                    stats["blocked"] += 1
                    ev.append(rec | {"amount": amount, "result": "막음", "why": [f"승인 금액 {approved_amount} ≠ 결제 금액 {amount}"]})
                    continue
            L.hold(tx, "wallet", pick["id"], amount)
            if attack == "double":
                dup = L.hold(tx, "wallet", pick["id"], amount)  # 같은 요청을 다시 보냄 — 같은 tx 라 한 번만
                stats["double_paid"] += 0 if dup.get("duplicate") else 1
            res = deliver(
                pick | ({"reliability": 0.0} if attack == "no_delivery" else {}) | ({"quality": 0.0} if attack == "bad_result" else {}), rnd
            )
            v = verify(res)
            if v["pass"]:
                L.release(tx)
                spent += amount
                seen.add(pick["id"])
                ev.append(rec | {"result": "정산", "verify": v["reason"]})
            else:
                back = refund_amount(pick, amount, v["reason"])
                if back:
                    L.refund(tx, back, v["reason"])
                    stats["refunded"] += back
                else:
                    L.release(tx)
                stats["lost_to_bad"] += amount - back
                spent += amount - back
                ev.append(
                    rec
                    | {"result": "환불" if back == amount else "부분 환불" if back else "환불 없음", "verify": v["reason"], "refund": back}
                )
        else:
            # 규칙 없는 에이전트: 찾은 것 중 가장 싼 것을 바로 결제(묶지 않고 바로 판매자에게), 결과는 보지 않는다
            if attack == "price_swap":
                amount = int(amount * 1.6)
            L._post(tx, "pay", "wallet", f"merchant:{pick['id']}", amount, "바로 결제")
            if attack == "double":
                L._post(tx + "-dup", "pay", "wallet", f"merchant:{pick['id']}", amount, "다시 보냄")
                stats["double_paid"] += 1
                spent += amount
            stats["unapproved_paid"] += 1 if (amount > m["approve_over"] or pick["id"] not in seen) else 0
            stats["off_mandate_paid"] += 1 if check_mandate(m, pick, amount, 0, today) else 0
            res = deliver(
                pick | ({"reliability": 0.0} if attack == "no_delivery" else {}) | ({"quality": 0.0} if attack == "bad_result" else {}), rnd
            )
            if not verify(res)["pass"]:
                stats["paid_unverified"] += 1
                stats["lost_to_bad"] += amount
            spent += amount
            seen.add(pick["id"])
            ev.append(rec | {"result": "바로 결제"})
        if spent > m["monthly"]:
            stats["over_budget"] = max(stats["over_budget"], spent - m["monthly"])
    stats["spent"] = spent
    by: dict[str, dict[str, int]] = {}
    for e in ev:
        k = e.get("attack") or "정상"
        by.setdefault(k, {})
        by[k][e["result"]] = by[k].get(e["result"], 0) + 1
    return {"guarded": guarded, "stats": stats, "audit": L.audit(), "by_attack": by, "events": ev, "ledger": L.entries[-30:]}


def evaluate(seeds: int = 20, n: int = 40) -> dict[str, Any]:
    """규칙 있는 에이전트 vs 규칙 없는 에이전트를 같은 씨앗 · 같은 일로 — 지켜야 할 것(0 이어야 함)과 돈의 흐름."""
    out = {}
    for g in (True, False):
        tot: dict[str, int] = {}
        by: dict[str, dict[str, int]] = {}
        audits = []
        for s in range(seeds):
            r = run(n, s, g)
            for k, v in r["stats"].items():
                tot[k] = tot.get(k, 0) + v
            for a, rs in r["by_attack"].items():
                for res, c in rs.items():
                    by.setdefault(a, {})
                    by[a][res] = by[a].get(res, 0) + c
            audits.append(r["audit"])
        out["guarded" if g else "naive"] = {"stats": tot, "by_attack": by, "balanced": all(a["balanced"] for a in audits), "chain_ok": all(a["chain_ok"] for a in audits),
                                            "escrow_left": sum(a["in_escrow"] for a in audits)}  # fmt: skip
    return {"seeds": seeds, "n": n} | out
