"""정기 점검 · 경보: 주기 판단, 실행 기록에서 경보 계산(레드팀 하락 · 과잉 차단 · 드리프트 · 회귀), 주기 실행 · 지금 점검 API."""

from datetime import timedelta

from sqlalchemy import delete

from app.core import crud
from app.core.config import get_settings
from app.core.db import SessionLocal, TestRun, utcnow
from app.stages.evalops import api as evalops_api
from app.stages.evalops import watch
from tests.helpers import wait_job


def _rt(rate: float, benign: float = 1.0, mode: str = "enforce", inj: float = 1.0) -> dict:
    return {"mode": mode, "summary": {"attack_pass_rate": rate, "benign_pass_rate": benign,
                                      "by_type": {"injection_direct": {"rate": inj}, "benign": {"rate": benign}}}}  # fmt: skip


def _clear(db) -> None:
    db.execute(delete(TestRun).where(TestRun.kind.in_(list(watch.KINDS))))
    db.commit()


def test_redteam_alerts_compare_same_mode(client):
    with SessionLocal() as db:
        _clear(db)
        crud.record_run(db, "redteam", [], "rt1", {}, _rt(1.0), 0)
        crud.record_run(db, "redteam", [], "rt-off", {}, _rt(0.5, mode="off"), 0)  # 다른 모드와는 비교하지 않는다
        r3 = crud.record_run(db, "redteam", [], "rt3", {}, _rt(0.9, inj=0.8), 0)
        msgs = watch.run_alerts(db, r3)
        assert len(msgs) == 1 and "100% → 90%" in msgs[0] and "injection_direct" in msgs[0]
        r4 = crud.record_run(db, "redteam", [], "rt4", {}, _rt(0.95, benign=0.83), 0)  # 올랐지만 정상 질문을 막음
        msgs = watch.run_alerts(db, r4)
        assert len(msgs) == 1 and "정상 질문" in msgs[0]
        # 드리프트 · 회귀는 실행이 낸 경보를 그대로
        crud.record_run(db, "drift", [], "d", {}, {"alerts": ["새로운 질문이 늘었습니다(2% → 80%)"], "reason": "schedule"}, 0)
        crud.record_run(db, "regression", [], "g", {}, {"alerts": ["법률 세트"]}, 0)
        al = watch.alerts(db, 30)
        assert [a["kind"] for a in al] == ["regression", "drift", "redteam", "redteam"]
        assert al[1]["scheduled"] and "법률 세트" in al[0]["message"]
        _clear(db)


def test_due_and_status(client, monkeypatch):
    st = get_settings()
    with SessionLocal() as db:
        _clear(db)
        assert not watch.due(db, "drift", 0)  # 0 = 끔
        assert watch.due(db, "drift", 6)  # 기록이 없으면 바로
        r = crud.record_run(db, "drift", [], "d", {}, {}, 0)
        assert not watch.due(db, "drift", 6)
        r.created_at = utcnow() - timedelta(hours=7)
        db.commit()
        assert watch.due(db, "drift", 6)
        monkeypatch.setattr(st, "watch_drift_hours", 6)
        s = {x["kind"]: x for x in watch.status(db)}
        assert s["drift"]["enabled"] and s["drift"]["last_run_id"] == r.id and s["drift"]["next_at"] and not s["redteam"]["enabled"]
        _clear(db)


def test_run_watch_starts_due_jobs_once(client, monkeypatch, scripted_llm):
    st = get_settings()
    started = []
    monkeypatch.setattr(st, "watch_redteam_hours", 1)
    monkeypatch.setattr(st, "watch_regression_hours", 1)  # 회귀 세트가 없으면 띄우지 않는다
    monkeypatch.setattr(evalops_api.jobs, "submit", lambda kind, title, fn, **kw: started.append((kind, title)))
    with SessionLocal() as db:
        _clear(db)
    assert evalops_api.run_watch() == ["redteam"] and started[0][0] == "redteam" and "정기 레드팀" in started[0][1]


def test_watch_api_and_manual_run(client, scripted_llm, monkeypatch):
    with SessionLocal() as db:
        _clear(db)
    w = client.get("/api/evalops/watch").json()
    assert {s["kind"] for s in w["schedules"]} == set(watch.KINDS) and w["alerts"] == [] and not w["webhook"]
    assert client.post("/api/evalops/watch/nope/run").status_code == 404
    # 테스트의 요청 기록은 모두 방금 생겨 기준 기간(최근 7일 앞)이 비었다 — 실패 작업을 만들지 않고 이유를 알려 준다
    r = client.post("/api/evalops/watch/drift/run")
    assert r.status_code == 400 and "기준 기간" in r.json()["detail"]
    assert next(s for s in client.get("/api/evalops/watch").json()["schedules"] if s["kind"] == "drift")["not_ready"]
    job = client.post("/api/evalops/watch/redteam/run").json()
    done = wait_job(client, job, steps=2400)
    assert done["status"] == "done", done
    assert done["result"]["reason"] == "manual" and done["result"]["alerts_sent"]["to"] == "local"
    w = client.get("/api/evalops/watch").json()
    assert next(s for s in w["schedules"] if s["kind"] == "redteam")["last_run_id"] == done["result"]["run_id"]


def test_notify_webhook(monkeypatch):
    st = get_settings()
    sent = []

    class _R:
        status_code = 204

    monkeypatch.setattr(watch.httpx, "post", lambda url, json, timeout: sent.append((url, json)) or _R())
    assert watch.notify([{"message": "x"}])["to"] == "local"  # 주소가 없으면 화면에만
    monkeypatch.setattr(st, "alert_webhook", "http://hook.local/a")
    assert watch.notify([])["n"] == 0 and not sent  # 경보가 없으면 보내지 않는다
    r = watch.notify([{"kind": "redteam", "message": "공격 방어율이 떨어졌습니다"}])
    assert r == {"to": "http://hook.local/a", "status": 204, "n": 1} and sent[-1][1]["alerts"][0]["kind"] == "redteam"
