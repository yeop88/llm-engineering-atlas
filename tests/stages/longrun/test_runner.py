"""장기 실행 LR1~LR7: 계획 검사 · 체크포인트 · 승인 대기 · 재시도 → 대체 행동 → 재계획 · 범위 상한 · 중단 후 이어 하기 · 멱등 발송 · 되돌리기 · 완료 판정.

실행기 테스트는 시험용 행동(ACTIONS 에 잠시 넣는 것)으로 단계의 성공 · 실패 · 호출 횟수를 정하고, 집계 · 보고서 · 승인 · 발송은 실제 행동을 쓴다.
"""

from pathlib import Path

import pytest

from app.core import llm
from app.core.auth import LOCAL
from app.core.db import LrRun, SessionLocal
from app.stages.longrun import actions, plans, runner, verify
from app.stages.longrun import api as longrun_api

ITEMS = [
    {"intent": "배수", "product": "WM-200", "codes": ["E4"], "status": "open"},
    {"intent": "배수", "product": "WM-200", "codes": ["E4", "E1"], "status": "closed"},
    {"intent": "소음", "product": "RF-10", "codes": [], "status": "open"},
]


@pytest.fixture
def act(monkeypatch):
    """시험용 행동 등록기 — 이름 → 호출 기록. 실패할 횟수(fail)만큼 먼저 예외를 던진다."""
    calls: dict[str, list] = {}

    def add(name, out=None, fail=0, **kw):
        calls[name] = []

        def handler(p, ctx):
            calls[name].append({"params": p, "inputs": dict(ctx.inputs), "idem": ctx.step.idem_key})
            if len(calls[name]) <= fail:
                raise RuntimeError(f"{name} 일시 오류")
            return out(p, ctx) if callable(out) else dict(out or {"ok": True})

        monkeypatch.setitem(actions.ACTIONS, name, actions.Action(name, name, "시험용", handler, **kw))
        return calls[name]

    return add


def _plan(*steps, criteria=None, goal="시험 업무"):
    return {"goal": goal, "steps": [{"name": s[0], "action": s[0], "params": s[1] if len(s) > 1 else {}, "deps": s[2] if len(s) > 2 else []}
                                    for s in steps], "criteria": criteria or []}  # fmt: skip


def _report_plan():
    """모으기 → 집계 → 집계만 보고서 → 완료 조건 → 승인 → 발송(실제 행동). 숫자는 모두 집계에서 나와야 통과한다."""
    return _plan(("t_items",), ("aggregate", {}, [0]), ("draft_simple", {"title": "AS 동향"}, [1]),
                 ("verify_report", {"criteria": ["sections", "numbers_grounded", "citations_valid"]}, [2]),
                 ("approval", {}, [3]), ("deliver", {"target": "file"}, [4]),
                 criteria=["sections", "numbers_grounded", "citations_valid", "approved", "delivered"])  # fmt: skip


def _status(db, run_id):
    return {s.idx: s.status for s in runner.steps_of(db, run_id)}


# ── 계획 검사 (LR1) ─────────────────────────────────────────────────────────
def test_validate_rejects_unknown_and_out_of_scope_actions():
    """없는 행동 · 범위 밖 행동이 섞인 계획은 고치지 않고 거절 — 실행할 수 없는 계획을 만들어 두면 중간에 멈춘다."""
    with pytest.raises(ValueError, match="모르는 행동 'rm_rf'"):
        plans.validate(_plan(("collect_as",), ("rm_rf",)))
    with pytest.raises(ValueError, match="허용하지 않은 행동 'deliver'"):
        plans.validate(_plan(("collect_as",), ("deliver",)), allowed=["collect_as"])
    with pytest.raises(ValueError, match="단계가 없습니다"):
        plans.validate({"steps": []})


def test_validate_inserts_approval_before_irreversible_and_fixes_deps():
    """되돌릴 수 없는 발송 앞에는 승인을 끼우고, 앞에 없는 단계를 가리킨 의존은 뺀다 — LLM 계획을 그대로 믿지 않는 이유."""
    p, notes = plans.validate(_plan(("collect_as",), ("aggregate", {}, [0, 5]), ("deliver", {}, [1])))
    assert [s["action"] for s in p["steps"]] == ["collect_as", "aggregate", "approval", "deliver"]
    assert [s["deps"] for s in p["steps"]] == [[], [0], [1], [2]]  # 끼운 승인 뒤로 번호가 밀린 의존도 따라간다
    assert any("앞에 없는 단계" in n for n in notes) and any("승인을 끼웠습니다" in n for n in notes)
    # 이미 승인 뒤에 있으면 다시 끼우지 않는다
    p2, notes2 = plans.validate(_plan(("approval",), ("deliver", {}, [0])))
    assert [s["action"] for s in p2["steps"]] == ["approval", "deliver"] and notes2 == []


def test_template_fills_params_and_is_already_safe():
    p = plans.from_template("as_trend_report", {"days": 30, "collection_id": 7, "unused": None})
    assert p["steps"][0]["params"] == {"days": 30} and p["steps"][2]["params"]["collection_id"] == 7
    v, notes = plans.validate(p)
    # 템플릿은 승인 → 발송 순서가 이미 맞아 검사가 고칠 것이 없다
    assert notes == [] and len(v["steps"]) == len(plans.TEMPLATES["as_trend_report"]["steps"])


def test_llm_plan_goes_through_validation(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **kw: ({"steps": [{"name": "모으기", "action": "collect_as"}, {"name": "보내기", "action": "deliver", "deps": [0]}],
                                                              "criteria": ["delivered"]}, {"usage": {"output_tokens": 5}}))  # fmt: skip
    p = plans.from_llm(llm.LLMConfig("openai", "fake"), "보고서 보내기", {})
    v, notes = plans.validate(p)
    assert p["planner"] == "llm" and [s["action"] for s in v["steps"]] == ["collect_as", "approval", "deliver"] and notes
    monkeypatch.setattr(llm, "chat_json", lambda *a, **kw: (["not", "a", "plan"], {}))
    with pytest.raises(ValueError, match="형식에 맞지 않습니다"):
        plans.from_llm(llm.LLMConfig("openai", "fake"), "g", {})


# ── 체크포인트 · 승인 · 발송 (LR3 · LR4) ────────────────────────────────────
def test_runs_until_approval_then_delivers_after_approve(client, act):
    act("t_items", {"items": ITEMS})
    notes = []
    with SessionLocal() as db:
        run = runner.create(db, _report_plan(), {}, "tester")
        run = runner.advance(db, run.id, LOCAL, None, notify=notes.append, sleep=lambda s: None)
        # 발송 전에 멈춘다 — 승인 전에는 되돌릴 수 없는 행동이 돌지 않는다
        assert run.status == "waiting" and _status(db, run.id) == {0: "done", 1: "done", 2: "done", 3: "done", 4: "waiting", 5: "pending"}
        assert notes[0][0]["kind"] == "longrun_approval" and notes[0][0]["step"] == 4
        steps = runner.steps_of(db, run.id)
        # 단계마다 결과가 저장된다(체크포인트) — 집계 숫자가 그대로
        assert steps[1].output["total"] == 3 and steps[1].output["counts"]["codes"] == {"E4": 2, "E1": 1}
        assert steps[3].output["ok"] is True and run.usage["steps"] == 4

        with pytest.raises(ValueError, match="승인을 기다리는 단계가 아닙니다"):
            runner.approve(db, run, 5, "boss", True, "")
        runner.approve(db, run, 4, "boss", True, "확인")
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        assert run.status == "done" and all(s == "done" for s in _status(db, run.id).values())
        d = runner.steps_of(db, run.id)[5]
        assert Path(d.output["path"]).read_text(encoding="utf-8") == steps[2].output["report"]
        assert run.verdict["ok"] is True and {i["key"]: i["ok"] for i in run.verdict["items"]}["approved"] is True
        assert runner.steps_of(db, run.id)[4].approved_by == "boss"


def test_reject_pauses_run(client, act):
    act("t_items", {"items": ITEMS})
    with SessionLocal() as db:
        run = runner.create(db, _report_plan(), {}, "tester")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        runner.approve(db, run, 4, "boss", False, "숫자 확인 필요")
        st = runner.steps_of(db, run.id)[4]
        assert run.status == "paused" and st.status == "failed" and st.error == "반려: 숫자 확인 필요"
        assert runner.steps_of(db, run.id)[5].status == "pending"  # 반려된 업무는 발송하지 않는다


def test_deliver_is_idempotent_per_step_key(client, act):
    """재시도 · 이어 하기로 발송 단계가 다시 와도 같은 열쇠면 다시 보내지 않는다."""
    act("t_items", {"items": ITEMS})
    with SessionLocal() as db:
        run = runner.create(db, _report_plan(), {}, "tester")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        runner.approve(db, run, 4, "boss", True, "")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        steps = runner.steps_of(db, run.id)
        ctx = actions.Ctx(db=db, run=run, step=steps[5], user=LOCAL, lcfg=None, inputs={2: steps[2].output})
        again = actions.deliver({"target": "file"}, ctx)
        assert again["already"] is True and again["path"] == steps[5].output["path"]
        # 단계마다 열쇠가 다르다 — 다른 업무 · 다른 단계의 발송을 막지 않게
        assert len({s.idem_key for s in steps}) == len(steps)


def test_webhook_delivery_requires_url(client, act, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "alert_webhook", None)
    with SessionLocal() as db:
        run = runner.create(db, _plan(("approval",), ("deliver", {"target": "webhook"}, [0])), {}, "t")
        st = runner.steps_of(db, run.id)[1]
        with pytest.raises(RuntimeError, match="ALERT_WEBHOOK"):
            actions.deliver({"target": "webhook"}, actions.Ctx(db=db, run=run, step=st, user=LOCAL, lcfg=None))


def test_rollback_compensates_in_reverse(client, act):
    """되돌리기는 보상 작업이 있는 끝난 단계만 거꾸로 — 발송 파일은 지우고, 부작용 없는 집계는 그대로 둔다."""
    act("t_items", {"items": ITEMS})
    with SessionLocal() as db:
        run = runner.create(db, _report_plan(), {}, "tester")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        runner.approve(db, run, 4, "boss", True, "")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        path = Path(runner.steps_of(db, run.id)[5].output["path"])
        assert path.exists()
        res = runner.rollback(db, run, LOCAL)
        assert [r["step"] for r in res] == [5] and res[0]["result"] == {"removed": str(path)} and not path.exists()
        assert run.status == "rolled_back" and _status(db, run.id)[5] == "compensated" and _status(db, run.id)[1] == "done"
        assert runner.advance(db, run.id, LOCAL, None) is run and run.status == "rolled_back"  # 끝난 업무는 다시 돌지 않는다


# ── 복구 (LR2 · LR5) ─────────────────────────────────────────────────────────
def test_retry_then_success(client, act):
    calls = act("t_flaky", fail=1)
    slept = []
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_flaky",)), {}, "t")
        run = runner.advance(db, run.id, LOCAL, None, sleep=slept.append)
        s = runner.steps_of(db, run.id)[0]
        assert run.status == "done" and s.attempts == 2 and s.error == "" and slept == [1.0] and len(calls) == 2
        # 재시도는 같은 단계라 같은 멱등 열쇠 — 외부 쪽이 두 번 받아도 하나로 처리하게
        assert calls[0]["idem"] == calls[1]["idem"]


def test_llm_draft_falls_back_to_simple_report(client, act):
    """LLM 이 없으면(서버 멈춤) 초안 단계는 재시도 후 대체 행동(집계만 보고서)으로 — 업무가 숫자 보고서로는 끝나게."""
    act("t_items", {"items": ITEMS})
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_items",), ("aggregate", {}, [0]), ("draft_report", {"title": "AS"}, [1])), {}, "t")
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        s = runner.steps_of(db, run.id)[2]
        assert run.status == "done" and s.action == "draft_simple" and s.output["fallback"] is True
        assert "전체 3건" in s.output["report"] and "- codes: E4 2건, E1 1건" in s.output["report"]
        assert [x["kind"] for x in run.log if x["kind"] == "recover"] == ["recover"]


def test_failure_without_recovery_fails_run(client, act):
    act("t_ok")
    act("t_broken", fail=99)
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",), ("t_broken", {}, [0]), ("t_ok", {}, [1])), {}, "t")
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        assert run.status == "failed" and _status(db, run.id) == {0: "done", 1: "failed", 2: "pending"}
        assert run.log[-1]["kind"] == "fail" and "t_broken 일시 오류" in run.log[-1]["error"]


def test_replan_replaces_remaining_steps_with_llm_plan(client, act, monkeypatch):
    """대체 행동도 없으면 남은 단계를 LLM 으로 다시 계획 — 끝난 단계는 그대로 두고, 새 첫 단계가 끝난 결과를 모두 받는다."""
    act("t_ok", {"made": 1})
    act("t_broken", fail=99)
    alt = act("t_alt", {"alt": True})
    prompts = []

    def fake_plan(cfg, system, user, **kw):
        prompts.append(user)
        return {"steps": [{"name": "다른 길", "action": "t_alt", "params": {}}], "criteria": []}, {}

    monkeypatch.setattr(llm, "chat_json", fake_plan)
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",), ("t_broken", {}, [0]), ("t_ok", {}, [1])), {}, "t")
        run = runner.advance(db, run.id, LOCAL, llm.LLMConfig("openai", "fake"), sleep=lambda s: None)
        steps = runner.steps_of(db, run.id)
        assert run.status == "done" and [(s.idx, s.action, s.status) for s in steps] == [(0, "t_ok", "done"), (1, "t_alt", "done")]
        assert alt[0]["inputs"] == {0: {"made": 1}}
        assert "실패한 단계 1 t_broken" in prompts[0] and "이미 끝난 단계: 0:t_ok" in prompts[0]
        assert [x["kind"] for x in run.log].count("replan") == 1


def test_replan_is_capped(client, act, monkeypatch):
    """재계획은 두 번까지 — 매번 실패하는 계획을 끝없이 다시 세우면 업무가 끝나지 않는다."""
    act("t_broken", fail=99)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **kw: ({"steps": [{"name": "또", "action": "t_broken"}]}, {}))
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_broken",)), {}, "t")
        run = runner.advance(db, run.id, LOCAL, llm.LLMConfig("openai", "fake"), sleep=lambda s: None)
        assert run.status == "failed" and [x["kind"] for x in run.log].count("replan") == runner.MAX_REPLANS


def test_irreversible_step_is_never_replanned(client, act, monkeypatch):
    """발송이 실패했다고 LLM 이 다른 발송 계획을 세우게 두면 두 번 보낼 수 있다 — 되돌릴 수 없는 행동은 재계획하지 않는다."""
    act("t_send", fail=99, irreversible=True)
    asked = []
    monkeypatch.setattr(llm, "chat_json", lambda *a, **kw: asked.append(1) or ({"steps": []}, {}))
    with SessionLocal() as db:
        run = runner.create(db, _plan(("approval",), ("t_send", {}, [0])), {}, "t")
        runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        runner.approve(db, run, 0, "boss", True, "")
        run = runner.advance(db, run.id, LOCAL, llm.LLMConfig("openai", "fake"), sleep=lambda s: None)
        assert run.status == "failed" and asked == []


# ── 범위 · 상한 (LR7) ───────────────────────────────────────────────────────
def test_step_limit_pauses_and_extend_resumes(client, act):
    act("t_ok")
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",), ("t_ok", {}, [0]), ("t_ok", {}, [1])), {"max_steps": 1}, "t")
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        assert run.status == "paused" and _status(db, run.id) == {0: "done", 1: "pending", 2: "pending"}
        assert run.log[-1]["kind"] == "limit" and "단계 상한 1" in run.log[-1]["msg"]
        runner.extend(db, run, {"max_steps": 5, "max_seconds": 0}, "boss")
        assert run.status == "planned" and run.scope["max_steps"] == 6 and run.scope["max_seconds"] == 3600
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        assert run.status == "done" and run.usage["steps"] == 3


def test_cost_limit_pauses(client, act):
    act("t_ok")
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",), ("t_ok", {}, [0])), {"max_cost": 0.5}, "t")
        run.usage = run.usage | {"cost": 0.6}
        db.commit()
        run = runner.advance(db, run.id, LOCAL, None)
        assert run.status == "paused" and "비용 상한" in run.log[-1]["msg"]


def test_scope_blocks_other_collections(client, act):
    """범위에 없는 컬렉션을 건드리는 단계는 실행하지 않고 실패 — 계획이 바뀌어도(재계획) 허락한 자료 밖으로 나가지 않게."""
    calls = act("t_read")
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_read", {"collection_id": 9})), {"collections": [1, 2]}, "t")
        run = runner.advance(db, run.id, LOCAL, None)
        s = runner.steps_of(db, run.id)[0]
        assert run.status == "failed" and s.status == "failed" and s.error == "범위에 없는 컬렉션: 9" and calls == []


def test_scope_actions_restrict_plan_at_create(client):
    with pytest.raises(ValueError, match="허용하지 않은 행동"):
        with SessionLocal() as db:
            runner.create(db, _plan(("collect_as",), ("aggregate", {}, [0])), {"actions": ["collect_as"]}, "t")


# ── 중단 · 이어 하기 (LR3) ───────────────────────────────────────────────────
def test_interrupted_run_resumes_from_checkpoint(client, act):
    """서버가 단계 중간에 죽으면: 업무는 paused, 돌던 단계는 pending — 이어 하면 끝난 단계는 다시 하지 않고 그 단계부터."""
    first = act("t_first", {"a": 1})
    second = act("t_second", {"b": 2})
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_first",), ("t_second", {}, [0])), {}, "t")
        s0, s1 = runner.steps_of(db, run.id)
        s0.status, s0.output = "done", {"a": 1}
        s1.status = "running"
        run.status = "running"
        db.commit()
        run_id = run.id

    assert longrun_api.mark_interrupted() >= 1  # 앱 시작(lifespan)이 부르는 함수
    with SessionLocal() as db:
        run = db.get(LrRun, run_id)
        assert run.status == "paused" and _status(db, run_id) == {0: "done", 1: "pending"}
        assert run.log[-1]["kind"] == "interrupted"
        run = runner.advance(db, run_id, LOCAL, None)
        assert run.status == "done" and first == [] and second[0]["inputs"] == {0: {"a": 1}}


def test_mark_interrupted_leaves_other_runs(client, act):
    act("t_ok")
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",)), {}, "t")
        run.status = "waiting"  # 승인 대기 업무는 서버가 다시 떠도 그대로 — 이어 하기가 아니라 승인을 기다린다
        db.commit()
        rid = run.id
    longrun_api.mark_interrupted()
    with SessionLocal() as db:
        assert db.get(LrRun, rid).status == "waiting"


# ── 완료 판정 (LR6) ─────────────────────────────────────────────────────────
def test_done_but_criteria_missing_needs_review(client, act):
    """모든 단계를 마쳐도 완료 조건을 검사할 단계가 없으면 '완료'가 아니다 — 끝은 에이전트의 말이 아니라 검사로 정한다."""
    act("t_ok")
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_ok",), criteria=["sections", "delivered"]), {}, "t")
        run = runner.advance(db, run.id, LOCAL, None)
        items = {i["key"]: i for i in run.verdict["items"]}
        assert run.status == "done" and run.verdict["ok"] is False
        assert items["sections"]["detail"] == "검사할 단계가 계획에 없습니다" and items["delivered"]["ok"] is False
        assert "완료 조건 미달" in run.log[-1]["msg"]


def test_check_finds_missing_sections_made_up_numbers_and_bad_citations():
    report = "## 요약\n전체 3건, E4 오류 2건, 2026년 기준 [S1].\n## 문의 분포\n배수 17건 [S3]."
    out = verify.check(report, ["요약", "문의 분포", "다음 할 일"], {"codes": {"E4": 2}}, 3, [{"text": "필터"}],
                       ["sections", "numbers_grounded", "citations_valid"])  # fmt: skip
    by = {i["key"]: i for i in out["items"]}
    assert out["ok"] is False
    assert by["sections"]["detail"] == "없는 절: 다음 할 일"
    # 17 은 집계에 없는 숫자(지어냄) · 연도(2026)와 코드 속 숫자(E4 → 4)는 허용
    assert by["numbers_grounded"]["detail"] == "집계 · 자료에 없는 숫자: 17"
    assert by["citations_valid"]["detail"] == "없는 자료 번호: [3]"


def test_check_allows_numbers_from_sources():
    out = verify.check("## 요약\n필터는 30분마다 청소 [S1].", ["요약"], {}, 0, [{"text": "필터는 30분마다 청소하세요"}],
                       ["sections", "numbers_grounded", "citations_valid"])  # fmt: skip
    assert out["ok"] is True


def test_strict_verify_fails_step(client, act):
    """strict 이면 완료 조건 미달이 단계 실패가 된다 — 미달 보고서가 승인 · 발송으로 넘어가지 않게."""
    act("t_draft", {"report": "## 요약\n99건", "sections": ["요약"], "total": 3, "counts": {}})
    with SessionLocal() as db:
        run = runner.create(db, _plan(("t_draft",), ("verify_report", {"strict": True, "criteria": ["numbers_grounded"]}, [0]),
                                      ("approval", {}, [1])), {}, "t")  # fmt: skip
        run = runner.advance(db, run.id, LOCAL, None, sleep=lambda s: None)
        s = runner.steps_of(db, run.id)[1]
        assert run.status == "failed" and "완료 조건 미달" in s.error and _status(db, run.id)[2] == "pending"
