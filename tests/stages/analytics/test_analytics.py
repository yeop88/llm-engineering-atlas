"""데이터 분석 · Text-to-SQL(DA1~DA7): 예시 자료 · 가드(읽기 전용 · 개인정보 열 · 시간 상한) · 스키마 카드 · 연결 · 의미 계층 ·
실행 검증 · 고치기 · 숫자 검사 · 막대 · 실행 정확도 비교 · API.

LLM 은 가짜 — 첫 시도에 틀린 SQL 을 내고 오류를 받으면 고치게 해, 실행 검증 고리가 실제로 도는지 본다.
"""

import json
import sqlite3

import pytest

from app.stages.analytics import agent, evaluate, guard, schema, source
from tests.helpers import wait_job

NAME = "da_test_demo"


@pytest.fixture(scope="module")
def demo():
    info = source.build_demo(NAME, 600, 7)
    yield source.path_of(NAME)
    source.path_of(NAME).unlink(missing_ok=True)


def test_demo_is_deterministic_and_dated(demo):
    """같은 씨앗이면 같은 자료(평가 정답이 언제나 같게), 날짜는 고정 범위, 출시 전 제품 접수는 없다."""
    g = guard.connect(demo)
    try:
        a = guard.run(g, "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM inquiries")["rows"][0]
        early = guard.run(g, "SELECT COUNT(*) FROM inquiries WHERE product_model = 'WM-500' AND created_at < '2026-05-20'")["rows"][0][0]
    finally:
        g.close()
    assert a[0] == 600 and a[1] >= "2026-04-01" and a[2] < "2026-10-01" and early == 0
    other = "da_test_demo2"
    source.build_demo(other, 600, 7)
    try:
        g2 = guard.connect(source.path_of(other))
        assert (
            guard.run(g2, "SELECT SUM(resolved), COUNT(code) FROM inquiries")["rows"]
            == guard.run(guard.connect(demo), "SELECT SUM(resolved), COUNT(code) FROM inquiries")["rows"]
        )
        g2.close()
    finally:
        source.path_of(other).unlink(missing_ok=True)
    with pytest.raises(ValueError):
        source.path_of("../밖")


def test_guard_text_rules():
    for bad in (
        "",
        "DELETE FROM x",
        "SELECT 1; SELECT 2",
        "PRAGMA query_only = OFF",
        "SELECT 1 FROM x WHERE a IN (SELECT 1) UNION ALL DROP TABLE x",
    ):
        with pytest.raises(guard.Blocked):
            guard.check_text(bad)
    assert guard.check_text("SELECT * FROM t WHERE r = 'DELETE 요청';") == "SELECT * FROM t WHERE r = 'DELETE 요청'"


def test_guard_risky_preset_all_expected(demo):
    """막혀야 할 14개 중 위험한 것은 모두 막히고 정상 질의는 통과 — 별칭 · 하위 질의 · * 로 개인정보 열을 돌아가도 허가 콜백이 잡는다."""
    r = guard.test_risky(demo, source.preset("risky.json"), {"inquiries": {"customer_phone"}})
    assert r["passed"] == r["n"] == 14, [c for c in r["cases"] if not c["ok"]]


def test_guard_row_cap_and_admin_sees_pii(demo):
    g = guard.connect(demo, {})
    try:
        r = guard.run(g, "SELECT id FROM inquiries", max_rows=10)
        assert len(r["rows"]) == 10 and r["truncated"]
        assert guard.run(g, "SELECT customer_phone FROM inquiries LIMIT 1")["rows"][0][0].startswith("010-")
        with pytest.raises(sqlite3.Error):
            guard.run(g, "SELECT nope FROM inquiries")
    finally:
        g.close()


def test_schema_cards_link_and_pii_hidden(demo):
    meta = source.preset("schema_demo.json")
    cs = schema.cards(demo, meta)
    phone = next(c for c in cs["inquiries"]["columns"] if c["name"] == "customer_phone")
    assert phone["pii"] and phone["examples"] == []  # 실제 번호가 맥락에 들어가지 않게
    assert "E4" in next(c for c in cs["inquiries"]["columns"] if c["name"] == "code")["examples"]
    assert "customer_phone" not in schema.card_text(cs) and "customer_phone" in schema.card_text(cs, hide_pii=False)
    lk = schema.link("건조기 제품의 평균 만족도", cs, meta["synonyms"])
    assert {"products", "inquiries"} <= set(lk["tables"])
    lk2 = schema.link("재방문 티켓 비율", cs, meta["synonyms"])
    assert lk2["tables"][0] == "tickets" and "inquiries" in lk2["tables"]  # 외래 키로 이어진 표도 함께
    assert schema.tables_in("SELECT * FROM inquiries i JOIN products p", list(cs)) == {"inquiries", "products"}


def test_semantic_compile_and_reject_unknown(demo):
    sem = source.preset("semantic_demo.json")
    sql = schema.compile_plan(
        {
            "metric": "해결률",
            "dimensions": ["제품 종류"],
            "filters": {"의도": "고장"},
            "date_from": "2026-09-01",
            "order": "asc",
            "limit": 2,
        },
        sem,
    )
    g = guard.connect(demo)
    try:
        res = guard.run(g, sql)
        gold = guard.run(g, "SELECT p.kind, ROUND(100.0 * SUM(i.resolved) / COUNT(i.id), 1) r FROM inquiries i JOIN products p ON p.model = i.product_model "
                            "WHERE i.intent = '고장' AND i.created_at >= '2026-09-01' GROUP BY p.kind ORDER BY r ASC LIMIT 2")  # fmt: skip
    finally:
        g.close()
    assert evaluate.same(gold, res, True)
    for bad in (
        {"metric": "지어낸 지표"},
        {"metric": "해결률", "dimensions": ["없는 차원"]},
        {"metric": "해결률", "filters": {"없는 필터": 1}},
    ):
        with pytest.raises(ValueError):
            schema.compile_plan(bad, sem)
    assert "''" in schema.compile_plan({"metric": "접수 건수", "filters": {"제품 모델": "A'B"}}, sem)  # 따옴표를 벗어나지 못하게


def test_generate_and_run_repairs(demo, monkeypatch):
    """1차: 없는 열 → SQL 오류를 붙여 다시. 2차: 표기가 틀려 0 건(COUNT 는 0 한 줄) → 한 번만 다시. 3차: 맞음 — 시도마다 남는다."""
    answers = iter(
        [
            "```sql\nSELECT nope FROM inquiries\n```",
            "SELECT COUNT(*) FROM inquiries WHERE code = 'e4'",
            "```sql\nSELECT COUNT(*) AS n FROM inquiries WHERE code = 'E4';\n```",
        ]
    )
    prompts = []

    def chat(cfg, system, user, max_tokens=2048, temperature=0.3, **kw):
        prompts.append(user)
        return {"text": next(answers), "seconds": 0.1, "usage": {}}

    monkeypatch.setattr(agent.llm, "chat", chat)
    g = guard.connect(demo, {"inquiries": {"customer_phone"}})
    try:
        out = agent.generate_and_run(None, g, "E4 접수 건수", "스키마", [], max_tries=3)
    finally:
        g.close()
    assert out["tries"] == 3 and out["ok"] and out["result"]["rows"][0][0] > 0
    assert "SQL 오류" in prompts[1] and "결과가 0" in prompts[2]
    assert out["attempts"][1]["issues"] and "error" in out["attempts"][0]


def test_anomalies_numbers_chart():
    res = {"columns": ["kind", "rate"], "rows": [["세탁기", 120.0], ["건조기", 30.5]]}
    assert any("100" in x for x in agent.anomalies(res))
    assert agent.anomalies({"columns": ["n"], "rows": []})[0].startswith("결과가 비었습니다")
    ok = agent.number_check("세탁기 120 · 건조기 30.5 이고 2개 종류", res, "")
    assert ok["ok"]
    bad = agent.number_check("건조기는 45.0 입니다", res, "")
    assert not bad["ok"] and 45 in bad["not_in_result"]
    assert agent.number_check("비율은 25%", {"columns": ["r"], "rows": [[0.25]]}, "")["ok"]  # 0~1 비율의 백분율
    c = agent.chart(res)
    assert c["label"] == "rate" and c["bars"][0]["max"] == 120.0 and agent.chart({"columns": ["a"], "rows": [[1], [2]]}) is None
    assert agent.extract_sql("설명\n```sql\nWITH x AS (SELECT 1) SELECT * FROM x;\n```") == "WITH x AS (SELECT 1) SELECT * FROM x"


def test_execution_accuracy_compare():
    gold = {"columns": ["k", "n"], "rows": [["a", 2], ["b", 1]]}
    assert evaluate.same(gold, {"columns": ["x", "y"], "rows": [["b", 1], ["a", 2.0]]}, False)  # 순서 무관 · 정수=실수
    assert not evaluate.same(gold, {"columns": ["x", "y"], "rows": [["b", 1], ["a", 2]]}, True)
    assert evaluate.same(gold, {"columns": ["k", "extra", "n"], "rows": [["a", "설명", 2], ["b", "설명", 1]]}, False)  # 설명 열을 더 붙여도
    assert evaluate.same({"columns": ["r"], "rows": [[33.333]]}, {"columns": ["r"], "rows": [[33.3333]]}, False)
    assert not evaluate.same(gold, None, False)
    s = evaluate.summarize(
        [{"type": "집계", "correct": True, "tries": 1, "link_ok": True}, {"type": "조인", "correct": False, "tries": 3, "link_ok": False}]
    )
    assert s["acc"] == 0.5 and s["by_type"]["조인"]["acc"] == 0.0 and s["link_recall"] == 0.5


def test_api_flow(client, monkeypatch):
    name = "da_api_demo"
    try:
        r = client.post("/api/analytics/sources", json={"name": name, "kind": "demo", "n": 300})
        assert r.status_code == 200 and r.json()["tables"]["inquiries"] == 300
        assert client.post("/api/analytics/sources", json={"name": "demo_x", "kind": "app"}).status_code == 400
        assert any(s["name"] == name for s in client.get("/api/analytics/sources").json()["sources"])
        assert client.get(f"/api/analytics/sources/{name}/schema").json()["pii"] == {"inquiries": ["customer_phone"]}
        gold = {q["q"]: q["sql"] for q in source.preset("eval_demo.json")}

        def chat(cfg, system, user, max_tokens=2048, temperature=0.3, **kw):
            if "질의 결과 표만" in system:
                return {"text": "결과는 표와 같습니다.", "seconds": 0.1, "usage": {}}
            q = user.rsplit("[질문]\n", 1)[1].split("\n\n")[0].strip()
            return {"text": f"```sql\n{gold.get(q, 'SELECT 1')}\n```", "seconds": 0.1, "usage": {}}

        def chat_json(cfg, system, user, max_tokens=800, temperature=0.0, **kw):
            return {"metric": "접수 건수", "dimensions": [], "filters": {"제품 모델": "WM-200", "오류 코드": "E4"}}, {}

        monkeypatch.setattr(agent.llm, "chat", chat)
        monkeypatch.setattr(schema.llm, "chat_json", chat_json)
        a = client.post("/api/analytics/ask", json={"source": name, "question": "WM-200 의 E4 오류 접수는 몇 건?", "model": "fake"}).json()
        assert a["ok"] and a["tries"] == 1 and a["answer"]["check"]["ok"] and "inquiries" in a["link"]["tables"]
        s = client.post(
            "/api/analytics/ask", json={"source": name, "question": "WM-200 의 E4 오류 접수는 몇 건?", "mode": "semantic", "model": "fake"}
        ).json()
        assert s["result"]["rows"][0][0] == a["result"]["rows"][0][0] and s["plan"]["metric"] == "접수 건수"
        run = client.post("/api/analytics/run", json={"source": name, "sql": "SELECT customer_phone FROM inquiries LIMIT 1"}).json()
        assert not run["ok"] and "권한" in run["attempts"][0]["error"]
        assert client.post("/api/analytics/guard/test", json={"source": name}).json()["passed"] == 14
        r = wait_job(
            client,
            client.post(
                "/api/analytics/eval", json={"source": name, "modes": ["sql"], "model": "fake", "ids": ["q1", "q3", "q8", "q12"]}
            ).json(),
        )
        res = r["result"]
        assert res["modes"]["sql"]["acc"] == 1.0 and res["modes"]["sql"]["n"] == 4 and res["run_id"]
        assert client.post("/api/analytics/eval", json={"source": "app_x", "model": "fake"}).status_code == 400
        assert client.get("/api/analytics/sources/없는자료/schema").status_code in (400, 404)
    finally:
        source.path_of(name).unlink(missing_ok=True)


def test_eval_questions_all_run_on_demo(demo):
    """정답 SQL 24개가 예시 자료에서 모두 실행되고 결과가 비지 않는다 — 평가 세트가 깨지면 정확도 숫자가 뜻을 잃는다."""
    g = guard.connect(demo, {})
    try:
        for q in source.preset("eval_demo.json"):
            assert guard.run(g, q["sql"], 5000)["rows"], q["id"]
    finally:
        g.close()
    assert len(json.loads((source.PRESETS / "eval_demo.json").read_text(encoding="utf-8"))) == 24
