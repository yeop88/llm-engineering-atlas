"""단계 레지스트리: 내용 완결성 · 화면 연결 · 메뉴 · 단계 소개 · 상단 설명 패널."""

from app.stages import registry
from app.web.pages import PAGES, nav_items


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
    routes = set(PAGES) | {"/apps"}
    navs = {nav for _, nav in PAGES.values()} | {"apps"}
    for s in registry.STAGES:
        for p in s.pages:
            assert p.href in routes, p.href
            assert p.nav in navs, p.nav
            assert registry.stage_for_nav(p.nav) is s
    assert registry.stage_for_nav("stage_routing") is registry.BY_KEY["routing"]
    assert registry.stage_for_nav("history") is None


def test_nav_covers_every_stage():
    flat = []
    for item in nav_items():
        flat += item["keys"]
    for s in registry.STAGES:
        assert any(k == f"stage_{s.key}" or k in [p.nav for p in s.pages] for k in flat), s.key


def test_stage_and_map_pages(client):
    for s in registry.STAGES:
        r = client.get(f"/stages/{s.key}")
        assert r.status_code == 200 and s.principle[:20] in r.text and s.status_label in r.text, s.key
    assert client.get("/stages/없음").status_code == 404
    m = client.get("/roadmap").text
    assert all(f"/stages/{s.key}" in m for s in registry.STAGES) and "부분 연결" in m and "전체 연결" in m
    # 단계에 속한 화면 위에는 그 단계의 원리 · 왜 · 어떻게 패널
    r = client.get("/finetune").text
    assert 'class="stage-info" data-stage="finetune"' in r and registry.BY_KEY["finetune"].why[:20] in r
    assert 'class="stage-info"' not in client.get("/history").text
