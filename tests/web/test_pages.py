"""화면: 모든 페이지가 열리는지 · 예전 주소 넘겨주기 · 위치 표시 · 빠른 이동 색인."""

from app.stages import registry
from app.web.pages import REDIRECT_PREFIXES, REDIRECTS, all_pages, crumbs, search_index


def test_pages_render(client):
    cid = client.post("/api/collections", json={"name": "화면 확인"}).json()["id"]
    model_id = client.get("/api/models").json()[0]["id"]
    paths = [p.href for p in all_pages()] + [m.href for m in registry.MAPS] + [f"/embedding/models/{model_id}", f"/rag/collections/{cid}"]
    for path in paths:  # 모든 화면 (템플릿 위치가 바뀌어도 빠짐없이)
        r = client.get(path)
        assert r.status_code == 200, path
        assert "LLM Engineering Atlas" in r.text, path
    assert client.get("/apps/없는앱").status_code == 404
    client.delete(f"/api/collections/{cid}")


def test_old_urls_redirect(client):
    """1.0 에서 주소를 /<단계>/<화면> 으로 맞췄다 — 예전 북마크 · 문서 링크는 새 주소로 넘어가고 쿼리도 유지한다."""
    for old, new in REDIRECTS.items():
        r = client.get(old + "?x=1", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == new + "?x=1", old
        assert client.get(old).status_code == 200, old
    for old, new in REDIRECT_PREFIXES.items():
        r = client.get(old + "3", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == new + "3", old


def test_crumbs_and_search_index(client):
    assert crumbs("rag_answer") == [("2 RAG", "/rag/collections"), ("답변 생성", None)]
    assert crumbs("map_evalops")[0] == ("맵", "/maps")
    assert crumbs("settings_llm")[-1] == ("LLM 연결", None)
    idx = client.get("/ui/search-index.json").json()
    assert idx == search_index()
    hrefs = {x["href"] for x in idx}
    # 모든 화면 · 단계 · 맵을 빠른 이동으로 찾을 수 있다
    assert {p.href for p in all_pages()} <= hrefs and all(m.href in hrefs for m in registry.MAPS)
    assert all(f"/stages/{s.key}" in hrefs for s in registry.STAGES)
    page = client.get("/rag/answer").text
    assert 'aria-current="page">답변 생성' in page and 'id="sidebar"' in page and 'id="palette"' in page


def test_page_links_use_current_urls(client):
    """화면(템플릿 · 스크립트)의 고정 링크는 새 주소로 — 예전 주소는 넘겨주기로 열리긴 하지만 한 번 더 돌아가고, 주소 규칙이 다시 섞인다."""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "app" / "web"
    links = set()
    for f in [*web.rglob("*.html"), *(web / "static" / "js").rglob("*.js")]:
        for m in re.finditer(r"""(?:href=\?["'`]|location(?:\.href)?\s*=\s*["'`])(/[a-z][\w/-]*)""", f.read_text(encoding="utf-8")):
            links.add(m.group(1))
    links = {u.rstrip("/") or "/" for u in links if not u.startswith(("/api", "/static", "/docs", "/login", "/logout", "/ui/"))}
    bad = []
    for u in sorted(links):
        r = client.get(u, follow_redirects=False)
        # 끝이 / 로 끝나 동적 값이 붙는 링크(/stages/ · /apps/)는 목록 화면이 열리면 된다
        if r.status_code != 200 and not (r.status_code == 404 and u in ("/stages", "/rag/collections", "/embedding/models")):
            bad.append(f"{u} → {r.status_code}")
    assert not bad, bad
