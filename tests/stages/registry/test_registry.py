"""단계 레지스트리: 내용 완결성 · 화면 연결 · 사이드바 · 단계 소개 · 단계 설명 서랍."""

from markupsafe import escape

from app.stages import registry
from app.web.pages import all_pages, sidebar


def test_every_stage_is_described():
    keys = [s.key for s in registry.STAGES]
    assert len(keys) == len(set(keys))
    for s in registry.STAGES:
        assert s.title and s.summary and len(s.principle) > 40 and len(s.why) > 40 and s.how, s.key
        assert s.status in registry.STATUS_LABEL
        assert s.status != registry.DONE or s.pages, f"구현된 단계 {s.key} 에 화면이 없음"
        for _, path in s.docs:
            assert path.startswith("docs/"), path
    # 흐름도 본선: 1 임베딩 → … → 8 에이전트 · 강화학습
    assert [s.key for s in registry.MAIN_FLOW][:5] == ["embedding", "rag", "rerank", "search_lab", "finetune"]


def test_stage_pages_point_to_real_routes():
    # 라우트는 레지스트리의 Page 로 만들어진다 — 화면은 템플릿을 가져야 하고, nav 키는 겹치지 않아야 한다.
    # 예외: 여러 단계를 한 화면에서 다루면 나머지 단계는 그 화면의 부분(#앵커, 템플릿 없음)을 가리킨다 — 화면 주소는 실제 라우트여야 한다
    routes = {p.href for p in all_pages()}
    navs = [p.nav for p in all_pages()] + [p.nav for s in registry.STAGES for p in s.pages if not p.template]
    assert len(navs) == len(set(navs))
    for s in registry.STAGES:
        for p in s.pages:
            if "#" in p.href:
                assert not p.template and p.href.split("#")[0] in routes, p.href
            else:
                assert p.href in routes and p.template, p.href
            assert registry.stage_for_nav(p.nav) is s
    assert registry.stage_for_nav("stage_routing") is registry.BY_KEY["routing"]
    assert registry.stage_for_nav("history") is None


def test_nav_covers_every_stage():
    flat = []
    for sec in sidebar():
        for item in sec["items"]:
            flat += item["keys"] + [c["key"] for c in item["children"]]
    for s in registry.STAGES:
        assert any(k == f"stage_{s.key}" or k in [p.nav for p in s.pages] for k in flat), s.key


def test_stage_and_map_pages(client):
    for s in registry.STAGES:
        r = client.get(f"/stages/{s.key}")
        # 화면은 Jinja 가 HTML 이스케이프한 글(따옴표 → &#39;)이라 같은 함수(markupsafe)로 바꿔 비교
        assert r.status_code == 200 and str(escape(s.principle[:20])) in r.text and s.status_label in r.text, s.key
    assert client.get("/stages/없음").status_code == 404
    m = client.get("/maps/llm").text
    assert all(f"/stages/{s.key}" in m for s in registry.map_stages("llm")) and "부분 연결" in m and "전체 연결" in m
    # 두 번째 맵: 지식 그래프 · GraphRAG — 단계가 그 맵 화면에 모두 있고, LLM 맵 표에는 섞이지 않는다
    kg = client.get("/maps/knowledge-graph").text
    assert all(f"/stages/{s.key}" in kg for s in registry.map_stages("kg")) and "Text2Cypher" in kg
    assert "K1" not in m.split("단계별 상태")[1].split("연결 실행")[0]
    ag = client.get("/maps/multi-agent").text
    assert all(f"/stages/{s.key}" in ag for s in registry.map_stages("agents")) and "오케스트레이터" in ag
    mr = client.get("/stages/mm_rag").text
    assert "기반 단계" in mr and 'href="/stages/multimodal"' in mr  # 이미 있는 기능으로 이어진다
    st = client.get("/stages/ontology").text
    assert 'href="/maps/knowledge-graph"' in st and "/stages/kg_extract" in st  # 같은 맵 안에서 다음 단계
    # 단계에 속한 화면에는 그 단계의 원리 · 왜 · 어떻게 서랍(ⓘ 로 연다) — 단계 밖 화면에는 없다
    r = client.get("/finetune").text
    assert 'id="stage-drawer"' in r and 'id="stage-btn"' in r and registry.BY_KEY["finetune"].why[:20] in r
    assert 'id="stage-drawer"' not in client.get("/history").text


def test_maps():
    keys = ["llm", "kg", "agents", "evalops", "guardrails", "docintel", "serving", "conversation", "as_service", "posttrain",
            "flywheel", "platform", "interop", "voice", "compliance", "longrun", "rlvr", "edge",
            "reasoning", "context", "analytics", "coding", "computer_use", "interp",
            "memory", "compress", "omni", "bigmodel"]  # fmt: skip
    assert [m.key for m in registry.MAPS] == keys and {s.map for s in registry.STAGES} == set(keys)
    for m in registry.MAPS:
        # 공통 화면 맵은 흐름 묶음이 그 맵의 단계를 빠짐없이 한 번씩 담아야 한다(화면 흐름도에서 빠지는 단계가 없게)
        if not m.template:
            grouped = [k for _, ks in m.groups for k in ks]
            assert sorted(grouped) == sorted(s.key for s in registry.map_stages(m.key)), m.key
            assert m.lead and m.principles and m.example and m.generated_doc, m.key
    assert [s.no for s in registry.AGENTS_FLOW] == [f"MA{i}" for i in range(1, 9)]
    # 기반 단계는 실제 단계여야 하고, 구현됨 · 기초 있음 단계는 기반이 있어야 한다(이미 있는 것을 보여 주려고)
    for s in registry.OTHER_MAP_STAGES:
        assert all(k in registry.BY_KEY and k != s.key for k in s.builds_on), s.key
        assert s.status == registry.PLANNED or s.builds_on, s.key
        assert registry.map_flow(s) == registry.map_stages(s.map)
    assert all(m.diagram for m in registry.MAPS)
    assert [s.no for s in registry.KG_FLOW] == [f"K{i}" for i in range(1, 9)]
    assert all(s.map == "llm" for s in registry.MAIN_FLOW + registry.EXTRA)  # 본선 · 곁가지는 LLM 맵
    maps = next(i for sec in sidebar() for i in sec["items"] if i.get("group") == "maps")
    assert [x["href"] for x in maps["children"]] == [m.href for m in registry.MAPS]


def test_every_map_page(client):
    for m in registry.MAPS:
        r = client.get(m.href)
        assert r.status_code == 200, m.key
        assert all(f"/stages/{s.key}" in r.text for s in registry.map_stages(m.key)), m.key
    assert client.get("/maps/없는맵").status_code == 404


def test_stage_numbers_unique():
    nos = [s.no for s in registry.STAGES]
    assert len(nos) == len(set(nos))  # 화면 · 문서에서 번호로 단계를 찾으므로 맵이 달라도 겹치면 안 된다
