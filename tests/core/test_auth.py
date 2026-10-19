"""선택형 접근 토큰."""

from app.core.config import get_settings


def test_token_auth(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_token", "s3cret-token")
    assert client.get("/api/health").status_code == 200  # 열린 경로
    assert client.get("/api/models").status_code == 401
    page = client.get("/embedding/models", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].startswith("/login?next=/embedding/models")
    assert client.get("/api/models", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    bad = client.post("/login", data={"token": "wrong", "next": "/embedding/models"}, follow_redirects=False)
    assert bad.status_code == 401
    evil = client.post("/login", data={"token": "s3cret-token", "next": "//evil.example"}, follow_redirects=False)
    assert evil.headers["location"] == "/"  # 다른 사이트로 넘기지 않는다
    ok = client.post("/login", data={"token": "s3cret-token", "next": "/embedding/models"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/embedding/models"
    cookie = ok.cookies.get("atlas_session")
    assert cookie and "s3cret-token" not in cookie  # 쿠키에 토큰 자체를 담지 않는다
    assert client.get("/embedding/models", cookies={"atlas_session": cookie}).status_code == 200
    client.cookies.clear()
    monkeypatch.setattr(get_settings(), "api_token", None)
    assert client.get("/api/models").status_code == 200  # 끄면 다시 열림
