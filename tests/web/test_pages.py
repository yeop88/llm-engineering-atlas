"""화면: 모든 페이지가 열리는지."""


def test_pages_render(client):
    from app.web.pages import APP_PAGES, PAGES

    cid = client.post("/api/collections", json={"name": "화면 확인"}).json()["id"]
    model_id = client.get("/api/models").json()[0]["id"]
    paths = [*PAGES, "/apps", *(f"/apps/{a}" for a in APP_PAGES), f"/models/{model_id}", f"/collections/{cid}"]
    for path in paths:  # 모든 화면 (템플릿 위치가 바뀌어도 빠짐없이)
        r = client.get(path)
        assert r.status_code == 200, path
        assert "LLM Engineering Atlas" in r.text, path
    assert client.get("/apps/없는앱").status_code == 404
    client.delete(f"/api/collections/{cid}")
