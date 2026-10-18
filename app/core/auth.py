"""선택형 토큰 인증. API_TOKEN 을 비워 두면(기본) 꺼져 있다 — 혼자 로컬에서 쓰는 실험실이 기본이라서.

사내망 · 서버에 올리면 누구나 모델을 내려받고 컬렉션을 지울 수 있으므로, 토큰 하나로 막는다(사용자 · 권한 구분은 하지 않는다).
- API: `Authorization: Bearer <토큰>` 헤더
- 화면: /login 에서 토큰을 넣으면 쿠키를 준다. 쿠키에는 토큰이 아니라 토큰의 HMAC 을 담는다(쿠키가 새도 토큰 자체는 드러나지 않게).
토큰을 바꾸면 기존 쿠키는 모두 무효가 된다.
"""

import hashlib
import hmac
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.core.config import get_settings

COOKIE = "atlas_session"
# 로그인 없이 열리는 경로: 로그인 화면 자체, 정적 파일(로그인 화면 CSS), 상태 확인(도커 healthcheck)
OPEN_PATHS = ("/login", "/logout", "/static/", "/api/health")

router = APIRouter(tags=["auth"])


def _session_value(token: str) -> str:
    return hmac.new(token.encode(), b"atlas-session-v1", hashlib.sha256).hexdigest()


def authorized(request: Request) -> bool:
    token = get_settings().api_token
    if not token:
        return True
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and secrets.compare_digest(header[7:].strip().encode(), token.encode()):
        return True
    cookie = request.cookies.get(COOKIE, "")
    return bool(cookie) and secrets.compare_digest(cookie.encode(), _session_value(token).encode())


async def middleware(request: Request, call_next) -> Response:
    path = request.url.path
    if not get_settings().api_token or path.startswith(OPEN_PATHS) or authorized(request):
        return await call_next(request)
    if path.startswith("/api/") or path in ("/openapi.json",) or path.startswith("/docs"):
        return JSONResponse({"detail": "인증이 필요합니다. Authorization: Bearer <API_TOKEN> 헤더를 보내거나 /login 에서 로그인하세요."},
                            status_code=401, headers={"WWW-Authenticate": "Bearer"})  # fmt: skip
    nxt = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(nxt)}", status_code=303)


def _safe_next(nxt: str) -> str:
    # 다른 사이트로 넘기는 열린 리디렉션을 막는다 — 같은 사이트 안의 경로만
    return nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else "/"


LOGIN_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>로그인 · {app}</title><link rel="stylesheet" href="/static/css/style.css"></head>
<body><main style="max-width:420px;margin:12vh auto;padding:0 16px">
<form method="post" action="/login" class="card stack">
<h1 style="margin:0">◆ {app}</h1>
<p class="small muted">이 서버는 접근 토큰(<code>API_TOKEN</code>)으로 보호됩니다. 관리자에게 받은 토큰을 넣으세요.</p>
{err}
<input type="hidden" name="next" value="{next}">
<div class="field"><label for="t">접근 토큰</label><input id="t" name="token" type="password" autocomplete="current-password" required autofocus></div>
<button class="btn primary" type="submit">로그인</button>
</form></main></body></html>"""


def _login_page(nxt: str, error: str = "") -> HTMLResponse:
    from markupsafe import escape

    err = f'<div class="badge err">{escape(error)}</div>' if error else ""
    html = LOGIN_HTML.format(app=escape(get_settings().app_name), err=err, next=escape(_safe_next(nxt)))
    return HTMLResponse(html, status_code=401 if error else 200)


@router.get("/login", response_class=HTMLResponse)
def login_form(next: str = "/") -> Response:
    if not get_settings().api_token:
        return RedirectResponse("/", status_code=303)
    return _login_page(next)


@router.post("/login")
def login(token: str = Form(...), next: str = Form("/")) -> Response:
    real = get_settings().api_token
    if not real:
        return RedirectResponse("/", status_code=303)
    if not secrets.compare_digest(token.strip().encode(), real.encode()):
        return _login_page(next, "토큰이 맞지 않습니다.")
    res = RedirectResponse(_safe_next(next), status_code=303)
    st = get_settings()
    res.set_cookie(COOKIE, _session_value(real), httponly=True, samesite="lax", secure=st.auth_cookie_secure,
                   max_age=st.auth_cookie_days * 86400)  # fmt: skip
    return res


@router.get("/logout")
def logout() -> Response:
    res = RedirectResponse("/login" if get_settings().api_token else "/", status_code=303)
    res.delete_cookie(COOKIE)
    return res


@router.get("/api/health")
def health() -> dict:
    """도커 · 로드밸런서 상태 확인용 (인증 없이 열림 — 정보는 담지 않는다)."""
    return {"ok": True}
