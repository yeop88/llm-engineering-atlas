"""서빙 · 추론 최적화 · 비용(S1~S7): llama-server 명령 · 로그 해석, 동시 부하 집계, 디코딩 설정 비교, 예산 고르기 · 파레토 앞줄, 운영 기록.

실제 llama-server 를 띄우거나 모델을 받지 않는다 — 프로세스 · LLM 호출을 가짜로 바꿔 '무엇을 재고 어떻게 모으나'만 검증한다.
"""

import json
import os
import threading
import time
from datetime import timedelta

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import SessionLocal, TestRun, Trace, utcnow
from app.stages.serving import bench, budget, launcher
from tests.helpers import wait_job


# ── S5 llama-server 띄우기 ──────────────────────────────────────────────────
class FakeProc:
    """subprocess.Popen 대신: 정해 둔 로그 줄을 내보내고, 끄라고 하면 기록만 한다."""

    def __init__(self, cmd, lines):
        self.cmd, self.pid = cmd, os.getpid()  # psutil 이 실제로 읽을 수 있는 pid(지금 프로세스)
        self.stdout = iter(ln + "\n" for ln in lines)
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


@pytest.fixture
def fake_server(monkeypatch, tmp_path):
    """llama-server 실행 파일 · 프로세스를 가짜로. 만든 프로세스를 돌려줘 명령 · 종료를 확인한다."""
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"")
    st = get_settings()
    monkeypatch.setattr(st, "llama_server_bin", exe)
    monkeypatch.setattr(st, "llm_models_dir", tmp_path)
    made: list[FakeProc] = []
    lines: list[str] = []

    def popen(cmd, **kw):
        made.append(FakeProc(cmd, lines))
        return made[-1]

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    return {"made": made, "lines": lines, "dir": tmp_path}


def _wait_lines(srv, n):
    for _ in range(100):
        if len(srv.lines) >= n:
            return
        time.sleep(0.01)


def test_server_needs_binary(monkeypatch, tmp_path):
    # 실행 파일이 없으면 프로세스를 만들기 전에 알아듣게 멈춰야 한다(경로 오류가 '서버 시작 실패'로 숨지 않게)
    monkeypatch.setattr(get_settings(), "llama_server_bin", None)
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_BIN"):
        launcher.Server(tmp_path / "m.gguf", launcher.Variant("base"))


def test_server_command_per_variant(fake_server):
    model = fake_server["dir"] / "m.gguf"
    base = launcher.Server(model, launcher.Variant("base"), ctx=4096, ngl=10)
    # f16 기본값은 인자를 붙이지 않는다 — 서버 기본과 같은 설정을 '기준'으로 두어야 짝 비교가 공정하다
    assert "--cache-type-k" not in base.cmd and "-md" not in base.cmd
    assert base.cmd[base.cmd.index("-c") + 1] == "4096" and base.cmd[base.cmd.index("--alias") + 1] == "base"
    assert base.base_url == f"http://127.0.0.1:{base.port}/v1"

    k_only = launcher.Server(model, launcher.Variant("k8", kv_k="q8_0"))
    assert "--cache-type-k" in k_only.cmd and "-fa" not in k_only.cmd  # K 만 양자화하면 flash attention 이 필요 없다
    kv = launcher.Server(model, launcher.Variant("kv4", kv_k="q4_0", kv_v="q4_0"))
    i = kv.cmd.index("--cache-type-v")
    assert kv.cmd[i + 1 : i + 4] == ["q4_0", "-fa", "on"]  # V 양자화는 flash attention 없이 서버가 시작하지 못한다

    spec = launcher.Server(model, launcher.Variant("spec", draft="small.gguf", draft_max=8, extra=["--foo"]))
    # 초안 모델은 LLM_MODELS_DIR 안에서 찾고, 초안도 같은 GPU 층 수로 올린다
    assert spec.cmd[spec.cmd.index("-md") + 1] == str(fake_server["dir"] / "small.gguf")
    assert spec.cmd[spec.cmd.index("--spec-draft-n-max") + 1] == "8" and "-ngld" in spec.cmd and spec.cmd[-1] == "--foo"


def test_kv_log_is_not_double_counted():
    # llama.cpp 는 장치별 'KV buffer size' 와 합계 'size =' 를 함께 적는다 — 둘을 더하면 메모리가 두 배로 보인다
    new = ["llama_kv_cache:      CUDA0 KV buffer size =   448.00 MiB",
           "llama_kv_cache: size =  448.00 MiB (  8192 cells,  28 layers,  1/1 seqs), K (f16):  224.00 MiB, V (f16):  224.00 MiB"]  # fmt: skip
    assert launcher.kv_mib(new) == 448.0
    # SWA 모델은 캐시가 둘(전체 · 창) — 합계 줄 둘을 더한다
    iswa = ["llama_kv_cache_iswa: creating non-SWA KV cache", "llama_kv_cache: size =  100.00 MiB (...)",
            "llama_kv_cache: size =   20.50 MiB (...)"]  # fmt: skip
    assert launcher.kv_mib(iswa) == 120.5
    # 합계 줄이 없는 옛 형식은 장치별 버퍼(여러 GPU)를 더한다
    old = ["llama_kv_cache_init:      CUDA0 KV buffer size =   128.00 MiB", "llama_kv_cache_init:      CUDA1 KV buffer size =    64.00 MiB"]
    assert launcher.kv_mib(old) == 192.0
    assert launcher.kv_mib(["llama_new_context_with_model: KV self size  =  256.00 MiB, K (f16): 128.00 MiB"]) == 256.0
    assert launcher.kv_mib(["main: server is listening"]) is None


def test_server_memory_and_stop(fake_server):
    fake_server["lines"] += ["llama_kv_cache: size =  64.00 MiB (4096 cells)", "draft acceptance rate = 0.41000 (41 accepted / 100 generated)",
                             "draft acceptance rate = 0.57000 (57 accepted / 100 generated)"]  # fmt: skip
    srv = launcher.Server(fake_server["dir"] / "m.gguf", launcher.Variant("spec", draft="d.gguf"))
    _wait_lines(srv, 3)
    m = srv.memory()
    # 수락률은 마지막 값 — 서버가 요청마다 누적해 적으므로 마지막 줄이 전체 실측이다
    assert m["kv_cache_mib"] == 64.0 and m["draft_acceptance"] == 0.57 and m["rss_mib"] > 0
    srv.stop()
    assert fake_server["made"][-1].terminated


def test_free_port_skips_used_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        used = s.getsockname()[1]
        # 이미 쓰는 포트에 띄우면 서버가 바로 죽어 '설정 실패'로 오해한다 — 빈 포트를 찾아야 한다
        assert launcher.free_port(used) != used


# ── S4 동시 부하 ───────────────────────────────────────────────────────────
def test_pct_nearest_rank():
    assert bench._pct([], 0.5) is None
    assert bench._pct([30.0, 10.0, 20.0], 0.5) == 20.0 and bench._pct([30.0, 10.0, 20.0], 0.95) == 30.0
    assert bench._pct([float(i) for i in range(1, 101)], 0.95) == 95.0


def test_load_test_aggregates(monkeypatch):
    lock = threading.Lock()
    state = {"now": 0, "peak": 0, "n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert (
            body["temperature"] == 0.0 and body["cache_prompt"] is False
        )  # 캐시를 끄지 않으면 같은 질문 반복이 공짜가 돼 처리량이 부풀려진다
        with lock:
            state["now"] += 1
            state["n"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.02)
        with lock:
            state["now"] -= 1
        if "실패" in body["messages"][-1]["content"]:
            return httpx.Response(400, json={"error": "bad"})  # 재시도하지 않는 오류 — 오류 수로 집계돼야 한다
        return httpx.Response(200, json={"choices": [{"message": {"content": "네"}}], "usage": {"completion_tokens": 5}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    cfg = llm.LLMConfig("openai", "fake", "http://local/v1")
    seen = []
    rows = bench.load_test(cfg, ["질문1", "질문2", "실패"], [1, 3], progress=lambda f, m: seen.append(m))
    # 동시 수의 두 배를 보낸다 — 슬롯보다 많은 요청이 줄을 서는 모습까지 p95 에 담으려고
    assert [r["requests"] for r in rows] == [2, 6] and state["n"] == 8
    assert rows[0]["errors"] == 0 and rows[1]["errors"] == 2  # 질문 3개를 돌려 6개 → '실패' 가 두 번
    assert state["peak"] <= 3  # 동시 수를 넘겨 보내지 않는다
    r = rows[1]
    # 처리량은 성공한 요청만: 출력 토큰/초 ÷ 요청/초 = 요청당 토큰(5) — 실패한 요청의 토큰을 세면 처리량이 부풀려진다
    assert r["tokens_per_s"] / r["req_per_s"] == pytest.approx(5, rel=0.05) and r["p50_ms"] <= r["p95_ms"]
    assert seen == ["동시 1 · 요청 2", "동시 3 · 요청 6"]


# ── S5 디코딩 설정 비교 ────────────────────────────────────────────────────
def test_decode_compare_pairs_with_first(monkeypatch, tmp_path):
    started, stopped = [], []

    class FakeServer:
        def __init__(self, model, v, ctx):
            if v.draft == "bad.gguf":  # 초안 모델 어휘가 달라 서버가 못 뜨는 경우
                raise RuntimeError("vocab mismatch")
            self.v, self.cmd, self.base_url = v, ["llama-server", "--alias", v.label], f"http://x/{v.label}/v1"
            started.append(v.label)

        def wait(self):
            pass

        def memory(self):
            return {"kv_cache_mib": {"f16": 100.0, "q8": 50.0}.get(self.v.label), "rss_mib": 1.0, "draft_acceptance": None}

        def stop(self):
            stopped.append(self.v.label)

    def fake_eval(items, contexts, cfgs, max_chars, max_tokens, job):
        q = {"f16": [1.0, 1.0, 0.0], "q8": [1.0, 0.0, 0.0]}[cfgs[0].model]
        gen = {"f16": 10.0, "q8": 15.0}[cfgs[0].model]
        return [{"status": "ok", "quality": sum(q) / 3, "generation_per_second": gen, "rows": [{"quality": x} for x in q]}]

    monkeypatch.setattr(bench.launcher, "Server", FakeServer)
    monkeypatch.setattr(bench.llm_bits, "evaluate", fake_eval)
    vs = [launcher.Variant("f16"), launcher.Variant("q8", kv_k="q8_0"), launcher.Variant("spec", draft="bad.gguf")]
    out = bench.decode_compare(tmp_path / "m.gguf", vs, [{}] * 3, [[]] * 3, 4096, 1000, 64)
    by = {o["label"]: o for o in out}
    assert started == stopped == ["f16", "q8"]  # 띄운 서버는 모두 끈다(남으면 다음 설정의 메모리 · 포트를 차지)
    assert by["spec"]["status"] == "error" and "vocab mismatch" in by["spec"]["error"]  # 한 설정이 실패해도 나머지는 잰다
    # 첫 설정이 기준: 같은 질문끼리 짝지은 품질 차이 · 속도 배율
    assert "vs_first" not in by["f16"] and by["q8"]["vs_first"]["against"] == "f16"
    assert by["q8"]["vs_first"]["diff"] == pytest.approx(-1 / 3, abs=1e-3)
    assert by["q8"]["speedup"] == 1.5 and by["q8"]["kv_cache_mib"] == 50.0 and by["q8"]["command"] == "llama-server --alias q8"
    assert all("rows" not in o for o in out)  # 질문별 행은 결과에서 뺀다(기록이 커지지 않게)


# ── S7 예산 ────────────────────────────────────────────────────────────────
def _c(label, q, ms, cost=None, es="A"):
    return {"eval_set": es, "label": label, "quality": q, "latency_ms": ms, "p95_ms": None, "cost": cost}


def test_choose_best_within_targets_and_front():
    cs = [_c("small", 0.6, 300, 0.001), _c("mid", 0.8, 900, 0.004), _c("big", 0.9, 3000, 0.02), _c("slow-bad", 0.5, 2000),
          _c("same-lat-worse", 0.7, 900)]  # fmt: skip
    r = budget.choose(cs, max_ms=1000, max_cost=None, min_quality=None)["sets"][0]
    assert r["within"] and r["best"]["label"] == "mid" and r["n"] == 5  # 지연 목표 안에서 품질 최고
    # 파레토 앞줄: 품질을 더 올리려면 지연이 늘어야 하는 후보만 — 느리고 나쁜 후보, 같은 지연에 품질만 낮은 후보는 빠진다
    assert [c["label"] for c in r["front"]] == ["small", "mid", "big"]
    r2 = budget.choose(cs, max_ms=None, max_cost=0.01, min_quality=None)["sets"][0]
    assert r2["best"]["label"] == "mid"  # big 은 비용 초과 → 그다음 품질
    assert any("비용" in o for o in next(c for c in cs if c["label"] == "big")["over"])
    # 비용을 모르는 후보(None)는 비용으로 거르지 않는다 — 로컬 모델처럼 비용 기록이 없는 경로가 늘 탈락하면 안 된다
    assert budget.choose([_c("local", 0.95, 100)], None, 0.0001, None)["sets"][0]["within"]


def test_choose_nothing_within_shows_nearest():
    cs = [_c("a", 0.6, 1500), _c("b", 0.9, 5000)]
    r = budget.choose(cs, max_ms=1000, max_cost=None, min_quality=0.7)["sets"][0]
    # 목표 안 후보가 없으면 '가장 덜 넘긴' 후보와 무엇을 넘었는지 — 빈 답을 주면 목표를 어떻게 고칠지 알 수 없다
    assert not r["within"] and r["best"]["label"] == "b" and r["best"]["over"] == ["지연 5000ms > 1000"]
    assert sorted(len(c["over"]) for c in cs) == [1, 2]


def test_choose_groups_by_eval_set():
    # 다른 평가 세트의 품질은 서로 비교할 수 없다 — 세트마다 따로 고른다
    r = budget.choose([_c("x", 0.9, 100, es="A"), _c("y", 0.5, 100, es="B")], None, None, None)["sets"]
    assert {s["eval_set"]: s["best"]["label"] for s in r} == {"A": "x", "B": "y"}


def test_candidates_from_runs_and_live(client):
    with SessionLocal() as db:
        runs = [TestRun(kind="quant_llm", title="t", result={"eval_set": {"name": "예산세트"}, "results": [
                    {"status": "ok", "model": "q4", "quality": 0.7, "mean_seconds": 1.2}, {"status": "error", "model": "bad"}]}),
                TestRun(kind="flow_eval", title="t", result={"eval_set": {"name": "예산세트"}, "results": [
                    {"label": "rag", "answer": {"quality": 0.8}, "latency_ms": {"mean": 900, "p95": 1500}, "cost_per_q": 0.002},
                    {"label": "skip", "status": "error"}, {"label": "noq", "answer": {}}]}),
                TestRun(kind="routing_eval", title="t", params={"eval_set_id": 999}, result={"results": [
                    {"router": "rule", "quality": 0.75, "latency_ms": {"mean": 400}}]})]  # fmt: skip
        db.add_all(runs)
        now = utcnow()
        db.add_all([Trace(kind="answer", route="rag", model="m1", total_ms=float(ms), cost=0.001, status="ok", created_at=now) for ms in (100, 200, 3000)]
                   + [Trace(kind="answer", route="rag", model="m1", total_ms=99999, status="error", created_at=now),
                      Trace(kind="answer", route="rag", model="old", total_ms=1, status="ok", created_at=now - timedelta(days=30))])  # fmt: skip
        db.commit()
        ids = [r.id for r in runs]
        try:
            cs = [c for c in budget.candidates(db) if c["source"].endswith(tuple(f"#{i}" for i in ids))]
            by = {c["label"]: c for c in cs}
            # 실패 · 품질 없는 결과는 후보가 아니다 — 재지 못한 설정이 '0 지연'으로 뽑히면 안 된다
            assert set(by) == {"q4", "rag", "rule"}
            assert by["q4"]["latency_ms"] == 1200 and by["rag"]["p95_ms"] == 1500 and by["rag"]["cost"] == 0.002
            assert by["rule"]["eval_set"] == 999  # 세트 이름이 없으면 번호로 묶는다

            live = {(x["route"], x["model"]): x for x in budget.live(db, days=7, max_ms=1000, max_cost=0.0005)}
            row = live[("answer/rag", "m1")]
            # 오류 기록 · 기간 밖 기록은 빼고, 목표를 넘긴 비율을 함께 — '평균은 괜찮은데 꼬리가 넘는' 경우를 보려고
            assert row["n"] == 3 and row["p95_ms"] == 3000 and row["over_latency"] == pytest.approx(1 / 3, abs=1e-3)
            assert row["over_cost"] == 1.0 and ("answer/rag", "old") not in live
        finally:
            db.query(TestRun).filter(TestRun.id.in_(ids)).delete()
            db.query(Trace).filter(Trace.model.in_(("m1", "old"))).delete()
            db.commit()


# ── API ────────────────────────────────────────────────────────────────────
def test_api_budget_resources_and_validation(client, scripted_llm, monkeypatch, tmp_path):
    r = client.post("/api/serving/budget", json={"max_ms": 1000, "days": 3}).json()
    assert {"sets", "live", "targets"} <= set(r) and r["targets"]["max_ms"] == 1000

    (tmp_path / "a.gguf").write_bytes(b"x")
    monkeypatch.setattr(get_settings(), "llm_models_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "llama_server_bin", None)
    res = client.get("/api/serving/resources").json()
    assert res["gguf"] == ["a.gguf"] and res["llama_server"] is False and {"cache", "models", "memory"} <= set(res)

    assert client.post("/api/serving/load", json={"levels": [33]}).status_code == 400  # 동시 수 상한(실수로 서버를 마비시키지 않게)
    # llama-server 가 없거나 GGUF 가 없으면 작업을 만들기 전에 거절한다
    body = {"model": "a.gguf", "variants": [{"label": "f16"}], "eval_set_id": 1}
    assert client.post("/api/serving/decode", json=body).status_code == 400
    assert (
        client.post("/api/serving/decode", json=body | {"variants": [{"label": "bad label!"}]}).status_code == 422
    )  # 별칭은 명령 인자로 들어간다

    job = client.post("/api/serving/load", json={"levels": [1, 2], "prompts": ["연차휴가는?"], "max_tokens": 16}).json()
    done = wait_job(client, job)
    assert done["status"] == "done", done
    rows = done["result"]["rows"]
    assert [x["concurrency"] for x in rows] == [1, 2] and rows[1]["tokens_per_s"] > 0 and done["result"]["run_id"]
