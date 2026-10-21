"""장기 실행 API: 행동 · 템플릿 목록 · 계획 미리 보기 · 업무 실행(백그라운드) · 승인 대기 목록 · 승인 권한 · 반려 후 이어 하기 · 되돌리기 확인 · 취소,
그리고 실제 템플릿(as_trend_report)을 끝까지 — 초안의 숫자 검사와 발송 파일 내용이 템플릿의 의존 연결로도 맞는지."""

import re
import secrets
import time
from pathlib import Path

import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import AsSession, SessionLocal
from app.stages.longrun import actions
from tests.helpers import wait_job


@pytest.fixture
def t_ok(monkeypatch):
    calls = []

    def handler(p, ctx):
        calls.append(p)
        return {"report": "## 요약\n전체 0건", "sections": ["요약"], "total": 0, "counts": {}}

    monkeypatch.setitem(actions.ACTIONS, "t_ok", actions.Action("t_ok", "시험", "시험용", handler))
    return calls


def _plan(*steps):
    return {
        "goal": "API 시험",
        "steps": [{"name": a, "action": a, "params": {}, "deps": d} for a, d in steps],
        "criteria": ["approved", "delivered"],
    }


def _wait(client, job, headers):
    """인증을 켠 테스트용 wait_job — 작업 조회에도 토큰이 필요하다."""
    for _ in range(400):
        job = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


@pytest.fixture
def users(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "api_token", "admin-tok")
    monkeypatch.setattr(st, "api_users", [{"token": "user-tok", "name": "kim", "role": "user"}])
    return {"admin": {"Authorization": "Bearer admin-tok"}, "user": {"Authorization": "Bearer user-tok"}}


def test_catalog_lists_actions_and_templates(client):
    d = client.get("/api/longrun/catalog").json()
    acts = {a["name"]: a for a in d["actions"]}
    # 연결 계층 행동(검색 · 일괄 답변)은 api 가 등록해야 준비됨(ready) — 빠지면 그 행동을 쓰는 계획이 실행 중에 멈춘다
    assert acts["search"]["ready"] and acts["answer_batch"]["ready"] and acts["verify_report"]["ready"]
    assert acts["deliver"]["irreversible"] and acts["deliver"]["compensable"] and acts["draft_report"]["fallback"] == "draft_simple"
    assert set(d["templates"]) == {"as_trend_report", "batch_answer"} and d["default_scope"]["max_steps"] == 30


def test_plan_preview(client):
    p = client.post("/api/longrun/plan", json={"template": "as_trend_report", "params": {"days": 14}, "goal": "2주 동향"}).json()
    assert p["plan"]["goal"] == "2주 동향" and p["plan"]["steps"][0]["params"] == {"days": 14} and p["notes"] == []
    assert client.post("/api/longrun/plan", json={"template": "nope"}).status_code == 404
    # 범위가 허용하지 않는 행동이 템플릿에 있으면 미리 보기에서 바로 거절 — 실행 중에 알게 되면 늦다
    r = client.post("/api/longrun/plan", json={"template": "as_trend_report", "scope": {"actions": ["collect_as"]}})
    assert r.status_code == 400 and "허용하지 않은 행동" in r.json()["detail"]


def test_llm_plan_without_llm_is_400(client, monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "openai_model", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    r = client.post("/api/longrun/plan", json={"planner": "llm", "goal": "보고서"})
    assert r.status_code == 400 and "템플릿 계획을 쓰세요" in r.json()["detail"]


def test_llm_plan_preview_with_scripted_llm(client, scripted_llm, monkeypatch):
    real = llm.chat

    def chat(cfg, system, user, **kw):
        if "실행 계획" in system:  # 계획 요청만 정해진 답 — 나머지는 가짜 LLM 그대로
            return {"text": '{"steps": [{"name": "모으기", "action": "collect_as"}, {"name": "발송", "action": "deliver", "deps": [0]}]}'}
        return real(cfg, system, user, **kw)

    monkeypatch.setattr(llm, "chat", chat)
    d = client.post("/api/longrun/plan", json={"planner": "llm", "goal": "보고서 발송"}).json()
    assert [s["action"] for s in d["plan"]["steps"]] == ["collect_as", "approval", "deliver"] and d["notes"]


def test_create_run_rejects_bad_plan(client):
    r = client.post("/api/longrun/runs", json={"plan": {"steps": [{"action": "format_disk"}]}, "start": False})
    assert r.status_code == 400 and "모르는 행동" in r.json()["detail"]


def test_run_waits_for_approval_and_only_admin_approves(client, t_ok, users):
    r = client.post("/api/longrun/runs", json={"plan": _plan(("t_ok", []), ("deliver", [0]))}, headers=users["user"])
    assert r.status_code == 201
    run = r.json()
    # 계획 검사가 발송 앞에 승인을 끼웠다 — 사용자가 만든 계획이어도
    assert [s["action"] for s in run["steps"]] == ["t_ok", "approval", "deliver"] and run["by"] == "kim"
    assert run["steps"][2]["irreversible"] is True
    _wait(client, run["job"], users["user"])
    got = client.get(f"/api/longrun/runs/{run['id']}", headers=users["user"]).json()
    assert got["status"] == "waiting" and [s["status"] for s in got["steps"]] == ["done", "waiting", "pending"]
    pend = [a for a in client.get("/api/longrun/approvals", headers=users["user"]).json() if a["run_id"] == run["id"]]
    assert pend and pend[0]["idx"] == 1 and pend[0]["goal"] == "API 시험"

    # 사람 승인 지점은 '누가' 승인했는지가 남아야 의미가 있다 — 관리자만
    assert client.post(f"/api/longrun/runs/{run['id']}/steps/1/approve", json={}, headers=users["user"]).status_code == 403
    ap = client.post(f"/api/longrun/runs/{run['id']}/steps/1/approve", json={"note": "좋음"}, headers=users["admin"]).json()
    _wait(client, ap["job"], users["admin"])
    done = client.get(f"/api/longrun/runs/{run['id']}", headers=users["admin"]).json()
    assert done["status"] == "done" and done["steps"][1]["approved_by"] == "admin" and done["verdict"]["ok"] is True
    assert Path(done["steps"][2]["output"]["path"]).read_text(encoding="utf-8") == "## 요약\n전체 0건"
    assert client.post(f"/api/longrun/runs/{run['id']}/go", json={}, headers=users["admin"]).status_code == 400
    assert client.post(f"/api/longrun/runs/{run['id']}/cancel", headers=users["admin"]).status_code == 400


def test_reject_then_go_asks_approval_again(client, t_ok):
    """반려 뒤 이어 하기는 반려된 승인 단계를 다시 대기로 — 반려를 그냥 지나쳐 발송하면 안 된다."""
    run = client.post("/api/longrun/runs", json={"plan": _plan(("t_ok", []), ("deliver", [0]))}).json()
    wait_job(client, run["job"])
    rej = client.post(f"/api/longrun/runs/{run['id']}/steps/1/approve", json={"ok": False, "note": "다시"}).json()
    assert rej["status"] == "paused" and "job" not in rej
    wait_job(client, client.post(f"/api/longrun/runs/{run['id']}/go", json={}).json())
    got = client.get(f"/api/longrun/runs/{run['id']}").json()
    assert got["status"] == "waiting" and got["steps"][1]["status"] == "waiting" and got["steps"][2]["status"] == "pending"
    assert len(t_ok) == 1  # 끝난 단계는 다시 하지 않는다(체크포인트)


def test_rollback_needs_confirm_and_cancel(client, t_ok):
    run = client.post("/api/longrun/runs", json={"plan": _plan(("t_ok", [])), "start": False}).json()
    assert run["status"] == "planned" and "job" not in run
    assert client.post(f"/api/longrun/runs/{run['id']}/rollback").status_code == 400
    assert client.post(f"/api/longrun/runs/{run['id']}/rollback", params={"confirm": "true"}).json()["status"] == "rolled_back"
    other = client.post("/api/longrun/runs", json={"plan": _plan(("t_ok", [])), "start": False}).json()
    c = client.post(f"/api/longrun/runs/{other['id']}/cancel").json()
    assert c["status"] == "canceled" and c["log"][-1]["kind"] == "cancel"
    assert client.get("/api/longrun/runs/999999").status_code == 404
    assert any(x["id"] == other["id"] for x in client.get("/api/longrun/runs").json())


def test_extend_is_admin_only(client, t_ok, users):
    run = client.post("/api/longrun/runs", json={"plan": _plan(("t_ok", [])), "start": False}, headers=users["admin"]).json()
    assert client.post(f"/api/longrun/runs/{run['id']}/extend", json={"max_steps": 5}, headers=users["user"]).status_code == 403
    r = client.post(f"/api/longrun/runs/{run['id']}/extend", json={"max_steps": 5}, headers=users["admin"]).json()
    assert r["scope"]["max_steps"] == 35


def test_as_trend_template_end_to_end(client, rag_collection, scripted_llm, monkeypatch):
    """실제 템플릿 그대로: 초안 → 완료 조건 → 승인 → 발송. 완료 조건 · 발송은 초안 · 승인 단계만 의존으로 받는데도
    집계 숫자로 검사하고(지어낸 숫자 9173 은 잡고), 승인받은 보고서를 그대로 발송해야 한다."""
    with SessionLocal() as db:
        for intent, codes in (("배수", ["E4"]), ("배수", ["E4", "E1"]), ("소음", [])):
            db.add(
                AsSession(
                    id=secrets.token_hex(8), product_model="WM-200", intent=intent, messages=[{"role": "user", "text": "x", "codes": codes}]
                )
            )
        db.commit()

    def chat(cfg, system, user, **kw):
        assert "업무 보고서" in system
        agg = user.split("[집계]")[1].split("[자료]")[0].strip().splitlines()
        body = "\n".join(agg[1:])  # 집계 줄을 그대로 옮긴다 — 숫자는 모두 집계에서
        return {
            "text": f"## 요약\n{agg[0]}.\n## 문의 분포\n{body}\n## 주요 오류 코드와 조치\n배수 필터를 청소하세요 [S1].\n## 다음 할 일\n추가로 9173건을 점검한다."
        }

    monkeypatch.setattr(llm, "chat", chat)
    run = client.post(
        "/api/longrun/runs", json={"template": "as_trend_report", "params": {"days": 30, "collection_id": rag_collection["cid"]}}
    ).json()
    wait_job(client, run["job"])
    got = client.get(f"/api/longrun/runs/{run['id']}").json()
    assert got["status"] == "waiting", got["log"]
    steps = got["steps"]
    assert steps[2]["output"]["queries"] and steps[2]["output"]["queries"][0] == "E4 오류 조치"  # 집계 상위 코드로 찾았다
    check = {i["key"]: i for i in steps[4]["output"]["items"]}
    assert check["sections"]["ok"] is True
    # 집계 숫자(3 · 2 · 1)는 통과, 지어낸 9173 만 남는다 — 다른 테스트의 상담 기록이 집계에 섞여도 나올 리 없는 수
    assert check["numbers_grounded"]["ok"] is False and check["numbers_grounded"]["detail"].endswith(": 9173")
    ap = client.post(f"/api/longrun/runs/{run['id']}/steps/5/approve", json={"note": "숫자 확인함"}).json()
    wait_job(client, ap["job"])
    done = client.get(f"/api/longrun/runs/{run['id']}").json()
    assert done["status"] == "done"
    sent = Path(done["steps"][6]["output"]["path"]).read_text(encoding="utf-8")
    assert sent == steps[3]["output"]["report"] and re.search(r"^## 요약$", sent, re.M)
    v = {i["key"]: i["ok"] for i in done["verdict"]["items"]}
    # 숫자 검사가 실패했으니 '완료'가 아니라 '검토 필요' — 승인 · 발송은 했어도
    assert v["approved"] and v["delivered"] and not v["numbers_grounded"] and done["verdict"]["ok"] is False
