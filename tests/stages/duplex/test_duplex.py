"""풀듀플렉스 타이밍(FD4~FD7): 말끝 규칙 · 정책 순서(침묵 1.4초는 끊지 않고 · 침묵 0.5초가 말끝 규칙보다 더 끊고 · 미리 준비가 간격을 줄임) ·
맞장구는 그 순간 들은 것만으로 · 안전 경고가 차례를 기다리는 것보다 빠름 · 말하는 중 고객 맞장구에 멈추지 않음 · API.
"""

from app.stages.duplex import sim


def test_finished_and_continues():
    assert sim.finished("물이 안 빠져요") and sim.finished("괜찮을까")
    assert not sim.finished("세탁기가") and not sim.finished("그랬는데")
    assert sim.continues("어제부터 그랬는데")


def test_policy_order():
    r = {p["policy"]: p for p in (sim.run_policy(x, 20) for x in sim.POLICIES)}
    assert r["silence1400"]["cut_in"] == 0
    assert r["silence500"]["cut_in"] > r["ending"]["cut_in"]
    assert r["ending_prepare"]["gap_p50"] < r["ending"]["gap_p50"] < r["silence1400"]["gap_p50"]
    assert r["ending_prepare"]["cut_in"] == r["ending"]["cut_in"]  # 준비만 앞당기고 판단은 같다


def test_cut_in_counts_mid_turn_decisions():
    # 차례 중간의 긴 쉼에서 '끝'이라 판단하면, 고객이 다시 말하기 전에 시작했어도 끊어 먹은 것
    turn = {
        "words": [{"w": "세탁기가", "start": 0, "end": 500}, {"w": "고장났어요", "start": 2500, "end": 3200}],
        "end": 3200,
        "prep": 700,
        "lag": 200,
    }
    assert sim._decide("silence500", turn)[2] is True
    assert sim._decide("ending", turn)[2] is True  # 1.4초도 넘는 쉼(2초)
    turn["words"][1]["start"] = 1200
    assert sim._decide("ending", turn)[2] is False and sim._decide("silence500", turn)[2] is True


def test_backchannel_safety_duplex():
    for b in (sim.backchannel(20, w) for w in (200, 700)):
        assert b["placed"] <= b["chances"] and 0 <= b["overlap_rate"] <= 1
    s = sim.safety(20)
    assert s["n"] > 0 and s["latency_ms"] < s["wait_policy_latency_ms"] and s["before_turn_end"] == 1.0
    d = sim.duplex_stop(20)
    assert d["length_text"]["false_stop"] == 0 and d["length_only"]["false_stop"] > 0
    assert d["length_text"]["missed_barge"] == 0


def test_api(client):
    p = client.post("/api/duplex/preview", json={"seed": 1}).json()
    assert len(p["turns"]) == 4 and set(p["turns"][0]["policies"]) == set(sim.POLICIES)
    e = client.post("/api/duplex/evaluate", json={"seeds": 10}).json()
    assert len(e["policies"]) == 4 and e["run_id"] and len(e["backchannel"]) == 3
    assert client.post("/api/duplex/evaluate", json={"seeds": 0}).status_code == 422
    assert client.get("/duplex/timing").status_code == 200
