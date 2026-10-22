"""추론 최적화(IF1~IF9): 워크로드 측정(요청 기록 → 길이 · 단계 시간 · 동시 수) · 미리 채우기 / 생성 나누기 · 사다리 통과 판정 · 칸 설정 · API.

llama-server 를 띄우지 않는다. 사다리의 칸 실행(run_step)은 가짜로 바꿔 '통과한 칸만 누적되고 같은 묶음은 건너뛰는가'를 보고,
탐침은 가짜 LLM(scripted_llm)으로 '작업이 돌고 결과 모양이 맞는가'만 본다. 통과 판정은 품질 짝 비교 · p95 · 처리량 규칙 그대로 잰다.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.db import SessionLocal, Trace, utcnow
from app.stages.inference import ladder, workload
from tests.helpers import wait_job


# ── IF1 워크로드 ─────────────────────────────────────────────────────────
def test_pct_and_dist():
    assert workload.pct([], 0.5) is None
    assert workload.pct([1, 2, 3, 4, 5], 0.5) == 3
    d = workload.dist([10.0, 20.0, 30.0])
    assert d["n"] == 3 and d["mean"] == 20.0 and d["max"] == 30.0 and d["p50"] == 20.0
    assert workload.dist([])["mean"] is None


def test_profile_counts_concurrency_and_steps(client):  # client: 앱이 뜰 때 마이그레이션으로 표가 생긴다
    """요청 셋 중 둘이 시간상 겹친다 — 동시 수 최대 2. 단계 시간은 이름별로 모이고 LLM 몫이 계산된다."""
    now = utcnow()
    with SessionLocal() as db:
        db.query(Trace).filter(Trace.kind == "if_test").delete()
        db.add_all([
            Trace(kind="if_test", created_at=now, total_ms=2000, tokens_in=1000, tokens_out=100,
                  steps=[{"name": "search", "ms": 200}, {"name": "llm", "ms": 1800}]),
            Trace(kind="if_test", created_at=now - timedelta(seconds=1), total_ms=2000, tokens_in=2000, tokens_out=50,
                  steps=[{"name": "llm", "ms": 1500}, {"name": "verify", "ms": 500}]),
            Trace(kind="if_test", created_at=now - timedelta(seconds=60), total_ms=1000, tokens_in=500, tokens_out=20, steps=[{"name": "llm", "ms": 900}]),
        ])  # fmt: skip
        db.commit()
        p = workload.profile(db, 1, kinds=["if_test"])
    assert p["n"] == 3 and p["kinds"] == {"if_test": 3}
    assert p["concurrency"]["peak"] == 2  # 끝 − 총 시간으로 되살린 구간 두 개가 겹친다
    assert p["steps"]["llm"]["n"] == 3 and set(p["steps"]) == {"search", "llm", "verify"}
    assert p["llm_share"] == round((1800 + 1500 + 900) / 5000, 3)
    assert p["tokens_in"]["max"] == 2000.0


def test_profile_empty(client):
    with SessionLocal() as db:
        assert workload.profile(db, 1, kinds=["없는_종류"]) == {"n": 0}


def test_split_picks_bottleneck():
    """프롬프트가 긴 워크로드(RAG)는 미리 채우기가, 답이 긴 워크로드는 생성이 병목 — 같은 탐침 속도로 갈린다."""
    probes = [{"prompt_tps": 100.0, "gen_tps": 10.0}, {"prompt_tps": 120.0, "gen_tps": 12.0}]
    rag = {"n": 5, "tokens_in": {"p50": 3000, "p95": 6000}, "tokens_out": {"p50": 50, "p95": 100}}
    long_out = {"n": 5, "tokens_in": {"p50": 200, "p95": 400}, "tokens_out": {"p50": 800, "p95": 1500}}
    a, b = workload.split(rag, probes), workload.split(long_out, probes)
    assert a["available"] and a["bottleneck"] == "prefill" and a["p50"]["prefill_share"] > 0.5
    assert b["bottleneck"] == "decode" and "추측 디코딩(IF7)" in b["advice"]
    assert workload.split({"n": 0}, probes) == {"available": False}
    assert workload.split(rag, [{"prompt_tps": None}]) == {"available": False}


# ── IF3~IF9 사다리 ────────────────────────────────────────────────────────
def test_config_apply_is_cumulative_and_copies():
    base = ladder.Config()
    c = base.apply(ladder.STEPS["kv_q8"], None, None).apply(ladder.STEPS["slots_4"], None, None)
    assert c.kv == ("q8_0", "q8_0") and c.slots == 4 and base.kv == ("f16", "f16") and base.slots == 1  # 원본은 그대로
    d = c.apply(ladder.STEPS["spec"], "draft.gguf", None).apply(ladder.STEPS["quant_alt"], None, Path("alt.gguf"))
    assert d.draft == "draft.gguf" and d.model == Path("alt.gguf")
    assert c.apply(ladder.STEPS["prefix"], None, None).prefix is True
    v = d.variant("x")
    assert v.extra[:3] == ["-np", "4", "--cont-batching"]


def _row(q: list[float], p95: float, tps: float) -> dict:
    return {"status": "ok", "rows": [{"quality": x} for x in q], "p95_ms": p95, "tokens_per_s": tps}


def test_gate_rules():
    base = _row([1, 1, 0, 1, 1, 0, 1, 1], 1000, 10)
    assert ladder.gate(base, _row([1, 1, 0, 1, 1, 0, 1, 1], 800, 10))["pass"]  # 품질 같고 p95 20% 빨라짐
    slow = ladder.gate(base, _row([1, 1, 0, 1, 1, 0, 1, 1], 990, 10.1))
    assert not slow["pass"] and "이득 3% 미만" in slow["why"]
    worse = ladder.gate(base, _row([0, 0, 0, 0, 0, 0, 1, 1], 500, 20))
    assert not worse["pass"] and "품질 하락" in worse["why"]  # 빨라도 품질이 떨어지면 떨어짐
    assert ladder.gate(base, {"status": "error"}) == {"pass": False, "why": "실패"}


def test_climb_keeps_passing_steps_and_skips_family(monkeypatch):
    """kv_q8 통과 → kv_q4 는 같은 묶음이라 건너뜀, slots_2 는 품질이 떨어져 떨어짐, 초안이 없으면 spec 건너뜀."""
    seen = []

    def fake_step(model, cfg, label, items, contexts, prompts, conc, ctx, max_chars, max_tokens):
        seen.append((label, cfg.kv, cfg.slots))
        good = [1.0] * 8
        if label == "baseline":
            return _row(good, 1000, 10) | {"label": label, "device_s_per_success": 2.0}
        if label == "slots_2":
            return _row([0.0] * 8, 400, 30) | {"label": label, "device_s_per_success": 1.0}
        return _row(good, 700, 12) | {"label": label, "device_s_per_success": 1.5}

    monkeypatch.setattr(ladder, "run_step", fake_step)
    res = ladder.climb(Path("m.gguf"), ["kv_q8", "kv_q4", "slots_2", "spec"], [], [], [], 2)
    by = {r["step"]: r for r in res["steps"]}
    assert by["baseline"]["gate"]["pass"] and by["kv_q8"]["gate"]["pass"]
    assert by["kv_q4"]["status"] == "skipped" and by["spec"]["status"] == "skipped"
    assert not by["slots_2"]["gate"]["pass"]
    assert ("slots_2", ("q8_0", "q8_0"), 2) in seen  # 통과한 kv_q8 위에서 다음 칸을 잰다(누적)
    assert res["summary"]["kept"] == ["kv_q8"] and res["summary"]["p95_change"] == 0.7
    assert all("rows" not in r for r in res["steps"])  # 큰 행 목록은 결과에서 뺀다


def test_climb_stops_when_baseline_fails(monkeypatch):
    monkeypatch.setattr(ladder, "run_step", lambda *a, **k: {"status": "error", "error": "OOM"})
    res = ladder.climb(Path("m.gguf"), ["kv_q8"], [], [], [], 2)
    assert [r["step"] for r in res["steps"]] == ["baseline"] and not res["steps"][0]["gate"]["pass"]


# ── API ──────────────────────────────────────────────────────────────────
def test_workload_and_steps_api(client):
    w = client.get("/api/inference/workload?days=1").json()
    assert "n" in w
    steps = client.get("/api/inference/steps").json()["steps"]
    assert {"baseline", "kv_q8", "prefix", "spec"} <= set(steps)


def test_probe_job_with_fake_llm(client, scripted_llm):
    job = client.post("/api/inference/probe", json={"prompt_tokens": [64], "out_tokens": [8], "days": 1}).json()
    res = wait_job(client, job)
    assert res["status"] == "done", res
    r = res["result"]
    assert len(r["probes"]) == 1 and r["probes"][0]["prompt_target"] == 64 and r["run_id"]
    assert r["split"] == {"available": False}  # 가짜 LLM 은 timings 를 주지 않는다 — 나누기는 '알 수 없음'


def test_ladder_validation(client, monkeypatch, tmp_path):
    body = {"model": "m.gguf", "eval_set_id": 1}
    monkeypatch.setattr(get_settings(), "llama_server_bin", None)
    assert client.post("/api/inference/ladder", json=body).status_code == 400  # 실행 파일 없음
    monkeypatch.setattr(get_settings(), "llama_server_bin", "llama-server")
    monkeypatch.setattr(get_settings(), "llm_models_dir", tmp_path)
    r = client.post("/api/inference/ladder", json=body)
    assert r.status_code == 400 and "GGUF" in r.json()["detail"]  # 폴더 밖 · 없는 파일
    (tmp_path / "m.gguf").write_bytes(b"GGUF")
    r = client.post("/api/inference/ladder", json=body | {"steps": ["kv_q8", "무엇"]})
    assert r.status_code == 400 and "모르는 칸" in r.json()["detail"]
    r = client.post("/api/inference/ladder", json=body | {"eval_set_id": 999999})
    assert r.status_code == 400 and "평가 세트" in r.json()["detail"]
    assert client.post("/api/inference/ladder", json={"model": "m.gguf"}).status_code == 422


@pytest.mark.parametrize("url", ["/inference/workload", "/inference/ladder"])
def test_pages_open(client, url):
    assert client.get(url).status_code == 200
