"""실시간 스트리밍(RT1~RT8): 조각 · 망 · 지터 버퍼 순서, 씨앗 재현, 확정 · 상태 갱신, 검색 미리 시작, 끼어들기 멈춤, 끊김 복구 전략, API.

재생기는 계산만이라 실제 수치를 그대로 본다. LLM 첫 토큰 실측(live)은 가짜 chat_stream 으로 — 첫 조각 · 첫 문장 · 토큰 간격이
결과 모양대로 모이는지만 본다(LLM 속도는 재지 않는다).
"""

import random
import time

import pytest

from app.core import llm
from app.stages.realtime import sim
from tests.helpers import wait_job

TEXT = "세탁기 WM-200 에서 E4 에러가 떠요 어떻게 해야 하나요?"
KM, KC = ("WM-200", "DR-300"), ("E4", "d80")


def test_chunks_cover_words_in_order():
    p = sim.Params(chunk_ms=250, word_ms=330)
    cs = sim.chunks(6, p)
    # 낱말마다 정확히 한 조각에 끝이 들어가야 한다 — 빠지거나 겹치면 인식기가 낱말을 잃거나 두 번 듣는다
    assert sorted(w for c in cs for w in c["words"]) == list(range(6))
    assert cs[-1]["sent"] == 6 * 330


def test_deliver_keeps_order_and_retransmit():
    p = sim.Params(net=sim.Net(base_ms=50, jitter_ms=80, loss=0.5, retransmit=True))
    out = sim.deliver(sim.chunks(20, p), p, random.Random(1))
    outs = [c["out"] for c in out]
    # 지터 버퍼는 순서대로 내보낸다 — 늦은 조각 뒤의 조각도 먼저 나갈 수 없다
    assert outs == sorted(outs)
    assert any(c["lost"] for c in out) and not any(c["dropped"] for c in out)
    p2 = sim.Params(net=sim.Net(loss=0.5, retransmit=False))
    assert any(c["dropped"] for c in sim.deliver(sim.chunks(20, p2), p2, random.Random(1)))


def test_turn_is_deterministic_per_seed():
    p = sim.Params()
    a, b = sim.turn(TEXT, p, 7, KM, KC), sim.turn(TEXT, p, 7, KM, KC)
    assert a == b
    assert a["first_sound_ms"] > a["first_token_ms"] > 0
    # 검색을 미리 시작해도 줄일 수 있는 것은 검색 몫(120ms)뿐
    assert 0 <= a["early_saved_ms"] <= 120


def test_state_updated_after_final_commit():
    """회귀: 끝점에서 남은 잠정까지 확정한 뒤 상태를 갱신 — 빠뜨리면 agree=3 의 상태 정확이 88% 로 나왔다."""
    p = sim.Params(agree=3, noise=0.4)
    rs = [sim.turn(TEXT, p, s, KM, KC) for s in range(20)]
    assert all(r["commit_errors"] == 0 for r in rs)
    assert all(r["state_ok"] for r in rs)


def test_barge_client_stops_sooner_than_server():
    p = sim.Params(net=sim.Net(base_ms=70, jitter_ms=80))
    srv = [sim.barge(sim._with(p, cancel_mode="server"), s)["stop_ms"] for s in range(30)]
    cli = [sim.barge(sim._with(p, cancel_mode="client"), s)["stop_ms"] for s in range(30)]
    assert sum(cli) / 30 < sum(srv) / 30


def test_recover_strategies():
    p = sim.Params()
    rs = {st: [sim.recover(TEXT, p, s, st) for s in range(20)] for st in ("none", "server", "server+replay")}
    assert all(r["recovered"] for r in rs["server+replay"])
    assert not any(r["recovered"] for r in rs["none"])
    # 서버가 확정분을 들고 있으면 새 세션보다 덜 잃는다
    assert sum(r["lost_share"] for r in rs["server"]) < sum(r["lost_share"] for r in rs["none"])


def test_run_and_sweep_shape():
    r = sim.run([TEXT], sim.Params(), seeds=5, known_models=KM, known_codes=KC)
    assert r["n_turns"] == 5 and set(r["stages"]) == set(sim.STAGES)
    assert set(r["barge"]) == {"server", "client"}
    sw = sim.sweep([TEXT], sim.Params(), {"좋음": {"base_ms": 20, "jitter_ms": 10, "loss": 0.0, "retransmit": True}}, [100, 500], [0], 3)
    assert len(sw["rows"]) == 2


def test_api_run_sweep(client):
    pre = client.get("/api/realtime/preset").json()
    assert pre["utterances"] and pre["networks"]
    r = client.post("/api/realtime/run", json={"seeds": 2, "utterances": [TEXT]}).json()
    assert r["n_turns"] == 2 and r["run_id"]
    assert client.post("/api/realtime/run", json={"params": {"chunk_ms": 5}}).status_code == 422
    job = client.post("/api/realtime/sweep", json={"chunk_ms": [250], "buffer_ms": [0], "networks": ["좋음(유선)"], "seeds": 1}).json()
    done = wait_job(client, job, 1200)
    assert done["status"] == "done" and len(done["result"]["rows"]) == 1


@pytest.fixture
def fake_stream(monkeypatch, scripted_llm):
    def stream(cfg, system, user, max_tokens=2048, temperature=0.3, images=None):
        for piece in ["배수 필터를 ", "청소하세요. ", "그래도 안 되면 ", "연락 주세요."]:
            time.sleep(0.005)  # 0ms 첫 토큰은 실측에서 버리는 값이라(> 0 만 중앙값에) 조금 기다린다
            yield {"delta": piece}
        yield {"done": True, "text": "…", "usage": {"completion_tokens": 9}}

    monkeypatch.setattr(llm, "chat_stream", stream)


def test_api_live(client, fake_stream):
    job = client.post("/api/realtime/live", json={"n": 2}).json()
    r = wait_job(client, job)["result"]
    assert len(r["rows"]) == 2 and r["ttft_ms"] is not None and r["first_sentence_ms"] is not None
    assert r["rows"][0]["tokens"] == 9 and r["run_id"]


def test_page(client):
    assert client.get("/realtime/stream").status_code == 200
