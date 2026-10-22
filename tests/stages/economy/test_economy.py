"""에이전트 경제(EC1~EC8): 흉내 장부(합 · 해시 사슬 · 같은 거래 한 번만 · 부분 환불 · 잔액 부족) · 비교의 제외 이유 · 위임 검사 · 승인 이유 ·
공격이 섞인 일에서 규칙 있는 에이전트가 지켜야 할 것을 모두 0 으로 지키는지(규칙 없는 에이전트는 어기는지) · API.
"""

import pytest

from app.stages.economy import market
from app.stages.economy.ledger import Ledger


def test_ledger_rules():
    L = Ledger()
    L.fund("wallet", 10000)
    L.hold("t1", "wallet", "svc", 3000)
    assert L.hold("t1", "wallet", "svc", 3000)["duplicate"]  # 같은 요청 두 번 — 한 번만 묶임
    assert L.balances["wallet"] == 7000
    L.release("t1")
    assert L.release("t1")["skipped"]  # 이미 푼 거래는 다시 풀지 않는다
    L.hold("t2", "wallet", "svc", 2000)
    L.refund("t2", 500, "부분 미달")
    assert L.balances["wallet"] == 5500 and L.balances["merchant:svc"] == 3000 + 1500
    a = L.audit()
    assert a["balanced"] and a["chain_ok"] and a["in_escrow"] == 0
    with pytest.raises(ValueError):
        L.hold("t3", "wallet", "svc", 10**9)  # 잔액 부족
    L.entries[1]["amount"] = 1  # 한 줄을 고치면 해시 사슬이 끊긴다
    assert not L.audit()["chain_ok"]


def test_compare_and_mandate():
    p = market.preset()
    m, svcs = p["mandate"], p["services"]
    c = market.compare(market.discover(svcs, "translate"), {"min_quality": 0.75, "refund_required": True})
    cheap = next(x for x in c if x["id"] == "tr-cheap")
    assert not cheap["eligible"] and any("품질" in w for w in cheap["excluded_why"]) and "환불 없음" in cheap["excluded_why"]
    assert c[0]["eligible"]  # 가능한 것이 먼저
    scam = next(s for s in svcs if s["id"] == "ship-scam")
    v = market.check_mandate(m, scam, m["per_tx"] + 1, m["monthly"], "2026-10-23")
    assert any("허용 목록" in x for x in v) and any("건당" in x for x in v) and any("월 한도" in x for x in v)
    assert market.check_mandate(m, svcs[0], 100, 0, "2027-01-01") == ["위임 기한 지남"]
    why = market.needs_approval(m, svcs[1], m["approve_over"] + 1, set())
    assert len(why) == 2 and market.needs_approval(m, svcs[0], 100, {svcs[0]["id"]}) == []


def test_guarded_keeps_invariants_naive_does_not():
    keys = ("unapproved_paid", "over_budget", "off_mandate_paid", "double_paid", "paid_unverified", "lost_to_bad")
    for s in range(3):
        g = market.run(40, s, True)
        assert all(g["stats"][k] == 0 for k in keys), g["stats"]
        assert g["audit"]["balanced"] and g["audit"]["chain_ok"] and g["audit"]["in_escrow"] == 0
    r = market.evaluate(3, 40)
    assert sum(r["naive"]["stats"][k] for k in keys) > 0
    assert r["guarded"]["by_attack"]["over_tx"].get("막음", 0) > 0


def test_api(client):
    m = client.get("/api/economy/market").json()
    assert m["services"] and m["mandate"]["per_tx"]
    q = client.post("/api/economy/quote", json={"skill": "translate", "need": {"min_quality": 0.75}}).json()
    assert q["pick"]["eligible"] and q["amount"] == q["pick"]["price"] and q["approval_needed"]
    assert client.post("/api/economy/quote", json={"skill": "없는기능"}).status_code == 404
    s = client.post("/api/economy/simulate", json={"n": 10, "seed": 1}).json()
    assert len(s["events"]) <= 10 and s["audit"]["balanced"]
    e = client.post("/api/economy/evaluate", json={"seeds": 2, "n": 20}).json()
    assert e["guarded"]["stats"]["double_paid"] == 0 and e["run_id"]
    assert client.get("/economy/ledger").status_code == 200
