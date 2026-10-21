"""코딩 에이전트(CD1~CD6): 식별자 낱말 · 함수 단위 색인 · 기호 · 호출 그래프 검색, 돌연변이 후보 · 적용, 작업 공간 도구(정확한 교체 ·
문법 되돌리기 · 경로 밖 금지 · diff), 깬 코드 과제 만들기, 에이전트 고리(가짜 LLM), 규칙 리뷰, API.

저장소 전체를 복사하는 대신 작은 가짜 저장소(app/pkg/calc.py + tests/test_calc.py)를 tmp 에 만들어 작업 공간 원본으로 쓴다 — 테스트가
실제 pytest 를 하위 프로세스로 돌리므로 작아야 빠르다.
"""

import json
from pathlib import Path

import pytest

from app.stages.coding import agent, index, review
from app.stages.coding import workspace as wsp

CALC = '''"""작은 계산 모듈."""


def clamp(x, lo, hi):
    """lo 와 hi 사이로 자른다."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def total(items):
    return sum(clamp(i, 0, 10) for i in items)
'''
TEST = """from app.pkg import calc


def test_clamp():
    assert calc.clamp(-1, 0, 10) == 0
    assert calc.clamp(11, 0, 10) == 10
    assert calc.clamp(5, 0, 10) == 5


def test_total():
    assert calc.total([1, 20, -3]) == 11
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    base = tmp_path / "coding" / "base"
    (base / "app" / "pkg").mkdir(parents=True)
    (base / "tests").mkdir()
    for f in (base / "app" / "__init__.py", base / "app" / "pkg" / "__init__.py", base / "tests" / "__init__.py"):
        f.write_text("", encoding="utf-8")
    (base / "app" / "pkg" / "calc.py").write_text(CALC, encoding="utf-8")
    (base / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    root = tmp_path / "coding"
    (root / "work").mkdir()
    (root / "tasks").mkdir()
    monkeypatch.setattr(wsp, "root", lambda: root)
    monkeypatch.setattr(wsp, "base_copy", lambda: base)
    return base


def test_tokens_split_identifiers():
    t = index.tokens("restore_terms CodeIndex app/stages/x.py 표기 복원")
    assert {"restore_terms", "restore", "terms", "codeindex", "code", "index", "표기", "복원"} <= set(t)


def test_index_symbol_and_graph(repo):
    idx = index.CodeIndex(repo)
    assert {c["name"] for c in idx.items} == {"clamp", "total"}
    tot = next(c for c in idx.items if c["name"] == "total")
    assert "clamp" in tot["calls"] and tot["start"] < tot["end"]
    # 이름이 질문에 나오면 기호 일치로 그 함수가 1위
    assert idx.search("AssertionError in total() result", 2, "symbol")[0]["name"] == "total"
    # 테스트가 total 을 부르면 호출 그래프로 total 이 부르는 clamp 도 이웃으로 올라온다
    g = idx.search("assert 11 == 13", 2, "graph", seed_names=["total"])
    assert {r["name"] for r in g} == {"total", "clamp"}
    assert index.test_calls(TEST) == ["clamp", "total"]


def test_mutations_and_apply(repo, tmp_path):
    ms = wsp.mutations(CALC)
    kinds = {m["kind"] for m in ms}
    assert {"비교 뒤집기", "상수 ±1"} <= kinds and all(m["func"] in ("clamp", "total") for m in ms)
    m = next(x for x in ms if x["kind"] == "비교 뒤집기" and x["old"] == "x < lo")
    ws = wsp.workspace("mut")
    wsp.apply_mutation(ws, "app/pkg/calc.py", m)
    assert "if x <= lo:" in (ws / "app/pkg/calc.py").read_text(encoding="utf-8")
    c = next(x for x in ms if x["kind"] == "상수 ±1" and x["old"] == "10")
    wsp.apply_mutation(ws, "app/pkg/calc.py", c)
    assert "clamp(i, 0, 11)" in (ws / "app/pkg/calc.py").read_text(encoding="utf-8")


def test_workspace_tools(repo):
    ws = wsp.workspace("tools")
    assert "def clamp" in wsp.read(ws, "app/pkg/calc.py", 4, 5)
    assert not wsp.replace(ws, "app/pkg/calc.py", "return", "return")["ok"]  # 여러 번 있는 글은 거부
    bad = wsp.replace(ws, "app/pkg/calc.py", "    return x\n", "    return x(\n")
    assert not bad["ok"] and "되돌렸" in bad["error"] and "return x\n" in (ws / "app/pkg/calc.py").read_text(encoding="utf-8")
    assert wsp.replace(ws, "app/pkg/calc.py", "    return x\n", "    return int(x)\n")["ok"]
    d = wsp.diff(ws)
    assert "-    return x" in d and "+    return int(x)" in d
    with pytest.raises(ValueError):
        wsp.read(ws, "../../밖.py")
    with pytest.raises(ValueError):
        wsp.workspace("../밖")


def test_run_tests_and_build_tasks(repo):
    """돌연변이를 넣어 테스트가 실패하는 것만 과제로 — 살아남은 돌연변이 수도 함께."""
    ws = wsp.workspace("t")
    assert wsp.run_tests(ws, ["tests/test_calc.py"])["passed"]
    # 돌연변이 후보 3개(x < lo · x > hi · 상수 10) 중 경계 비교 둘은 이 테스트가 못 잡는다(-1 · 11 · 5 만 봄) — 살아남은 돌연변이로 남는다
    r = wsp.build_tasks("tiny", ["tests/test_calc.py"], 2, seed=1)
    assert r["n"] == 1 and r["tried"] == 3 and r["survived"] == 2
    tasks = wsp.load_tasks("tiny")["tasks"]
    assert all(t["file"] == "app/pkg/calc.py" and "실패 출력" in t["issue"] for t in tasks)
    assert wsp.list_tasks()[0]["name"] == "tiny"
    with pytest.raises(ValueError):
        wsp.load_tasks("없음")


def test_agent_fixes_mutation_with_fake_llm(repo, monkeypatch):
    """계획 → 읽기 → 교체(바로 테스트 통과) → 끝. 테스트 파일을 고치려 하면 막는다."""
    m = next(x for x in wsp.mutations(CALC) if x["old"] == "x < lo")
    task = {
        "id": "c1",
        "test": "tests/test_calc.py",
        "file": "app/pkg/calc.py",
        "func": "clamp",
        **m,
        "issue": "tests/test_calc.py 의 test_clamp 실패: clamp",
    }
    ws = wsp.workspace("agent")
    wsp.apply_mutation(ws, task["file"], task)
    steps = iter([{"tool": "replace", "file": "tests/test_calc.py", "old": "== 0", "new": "== 0 or True"},
                  {"tool": "read", "file": "app/pkg/calc.py", "start": 4, "end": 10},
                  {"tool": "replace", "file": "app/pkg/calc.py", "old": "    if x <= lo:\n", "new": "    if x < lo:\n"},
                  {"tool": "done", "summary": "경계 비교를 되돌림"}])  # fmt: skip
    monkeypatch.setattr(agent.llm, "chat_json", lambda *a, **k: ({"candidates": [{"file": "app/pkg/calc.py", "function": "clamp"}]}, {}))
    monkeypatch.setattr(
        agent.llm, "chat", lambda *a, **k: {"text": json.dumps(next(steps), ensure_ascii=False), "usage": {"output_tokens": 5}}
    )
    r = agent.run(None, ws, task, max_steps=6)
    assert (
        r["resolved"] and not r["touched_tests"] and r["edits"] == 1 and r["found_file"] and r["diff_lines"] == 0
    )  # 원래 줄로 정확히 되돌림
    assert "tests/ 는 고칠 수 없습니다" in r["steps"][0]["observation"] and "통과" in r["steps"][2]["observation"]


def test_review_rules_and_preset_eval():
    """규칙은 나쁜 diff 8개 중 논리 버그 하나만 못 잡고, 좋은 diff 는 모두 통과시킨다."""
    issues = review.check("--- a/tests/t.py\n+++ b/tests/t.py\n@@\n-    assert x == 1\n+@pytest.mark.skip\n")
    assert {i["rule"] for i in issues} == {"테스트 약화"}
    assert review.check("+++ b/app/core/x.py\n+from app.stages.kg import build\n")[0]["rule"] == "의존 방향"
    assert review.check("+++ b/app/stages/kg/api.py\n+from app.pipeline import serve\n") == []  # api 는 pipeline 을 써도 된다
    cases = json.loads((Path(review.__file__).parent / "presets" / "review_cases.json").read_text(encoding="utf-8"))
    r = review.evaluate(cases, None)
    assert r["rule"]["precision"] == 1.0 and r["rule"]["recall"] == 0.875 and r["llm"] is None


def test_api(client):
    assert (
        client.post("/api/coding/search", json={"query": "restore_terms 표기 복원", "method": "symbol", "k": 3}).json()["results"][0][
            "name"
        ]
        == "restore_terms"
    )
    assert client.post("/api/coding/review", json={"diff": "+++ b/app/x.py\n+os.system('ls')\n"}).json()["issues"][0]["rule"] == "위험 함수"
    assert client.post("/api/coding/review/eval", json={}).json()["rule"]["recall"] == 0.875
    assert client.get("/api/coding/tasks/없는과제").status_code == 404
    assert client.post("/api/coding/run", json={"tasks": "없는과제", "model": "fake"}).status_code == 404
    assert client.post("/api/coding/tasks", json={"name": "x", "tests": ["../app/main.py"]}).status_code == 400
    assert client.get("/api/coding/overview").json()["functions"] > 1000
