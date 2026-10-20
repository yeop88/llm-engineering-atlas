"""선택형 토큰 인증과 사용자 · 그룹. API_TOKEN · API_USERS 를 비워 두면(기본) 꺼져 있다 — 혼자 로컬에서 쓰는 실험실이 기본이라서.

사내망 · 서버에 올리면 누구나 모델을 내려받고 컬렉션을 지울 수 있으므로 토큰으로 막는다.
- API_TOKEN: 관리자 토큰 하나(모든 문서를 본다). 0.x 와 같다.
- API_USERS: 사용자마다 토큰 · 그룹 · 역할 — 권한별 검색(그룹이 붙은 문서는 그 그룹만, 보안 · 가드레일 맵 G3)과 감사 로그(G5)의 '누가'.
- API: `Authorization: Bearer <토큰>` 헤더
- 화면: /login 에서 토큰을 넣으면 쿠키를 준다. 쿠키에는 토큰이 아니라 토큰의 HMAC 을 담는다(쿠키가 새도 토큰 자체는 드러나지 않게).
토큰을 바꾸면 기존 쿠키는 모두 무효가 된다.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.core.config import get_settings

COOKIE = "atlas_session"
# 로그인 없이 열리는 경로: 로그인 화면 자체, 정적 파일(로그인 화면 CSS), 상태 확인(도커 healthcheck)
OPEN_PATHS = ("/login", "/logout", "/static/", "/api/health")
ALL = "*"  # 모든 그룹 — 관리자 · 인증을 끈 로컬


@dataclass(frozen=True)
class User:
    name: str
    groups: tuple[str, ...] = field(default=(ALL,))
    role: str = "admin"  # admin | user

    @property
    def sees_all(self) -> bool:
        return ALL in self.groups

    def public(self) -> dict:
        return {"name": self.name, "groups": list(self.groups), "role": self.role}


LOCAL = User("local")  # 인증을 끈 로컬 실험실


router = APIRouter(tags=["auth"])


def _session_value(token: str) -> str:
    return hmac.new(token.encode(), b"atlas-session-v1", hashlib.sha256).hexdigest()


def enabled() -> bool:
    st = get_settings()
    return bool(st.api_token or st.api_users)


def _accounts() -> list[tuple[str, User]]:
    """(토큰, 사용자) 목록 — 관리자 토큰 + API_USERS."""
    st = get_settings()
    out = [(st.api_token, User("admin"))] if st.api_token else []
    for u in st.api_users:
        if u.get("token"):
            out.append((str(u["token"]), User(str(u.get("name") or "user"), tuple(u.get("groups") or ()), str(u.get("role") or "user"))))
    return out


def user_of(request: Request) -> User | None:
    """요청의 사용자. 인증이 꺼져 있으면 로컬(모든 권한), 켜져 있는데 토큰이 맞지 않으면 None."""
    if not enabled():
        return LOCAL
    header = request.headers.get("authorization", "")
    bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
    cookie = request.cookies.get(COOKIE, "")
    for token, user in _accounts():
        if bearer and secrets.compare_digest(bearer.encode(), token.encode()):
            return user
        if cookie and secrets.compare_digest(cookie.encode(), _session_value(token).encode()):
            return user
    return None


def authorized(request: Request) -> bool:
    return user_of(request) is not None


def current_user(request: Request | None) -> User:
    """API 에서 쓰는 지금 사용자(미들웨어가 넣어 둔 것). 테스트처럼 요청이 없으면 로컬."""
    if request is None:
        return LOCAL
    return getattr(request.state, "user", None) or user_of(request) or LOCAL


def require_admin(request: Request | None, what: str) -> User:
    """관리자만 하는 일(감사 조회 · 서버 폴더 읽기 · 문서 권한 바꾸기). 토큰 없이 쓰면 로컬 사용자가 관리자라 그대로 통과."""
    user = current_user(request)
    if user.role != "admin":
        raise HTTPException(403, f"{what}은(는) 관리자만 할 수 있습니다.")
    return user


async def middleware(request: Request, call_next) -> Response:
    path = request.url.path
    user = user_of(request)
    request.state.user = user
    if user is not None or path.startswith(OPEN_PATHS):
        return await call_next(request)
    if path.startswith("/api/") or path in ("/openapi.json",) or path.startswith("/docs"):
        return JSONResponse({"detail": "인증이 필요합니다. Authorization: Bearer <토큰> 헤더를 보내거나 /login 에서 로그인하세요."},
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
<p class="small muted">이 서버는 접근 토큰으로 보호됩니다. 관리자에게 받은 토큰을 넣으세요.</p>
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
    if not enabled():
        return RedirectResponse("/", status_code=303)
    return _login_page(next)


@router.post("/login")
def login(token: str = Form(...), next: str = Form("/")) -> Response:
    if not enabled():
        return RedirectResponse("/", status_code=303)
    # 인자 이름 next 가 내장 next() 를 가리므로 목록으로 찾는다
    found = [t for t, _u in _accounts() if secrets.compare_digest(token.strip().encode(), t.encode())]
    real = found[0] if found else None
    if real is None:
        return _login_page(next, "토큰이 맞지 않습니다.")
    res = RedirectResponse(_safe_next(next), status_code=303)
    st = get_settings()
    res.set_cookie(COOKIE, _session_value(real), httponly=True, samesite="lax", secure=st.auth_cookie_secure,
                   max_age=st.auth_cookie_days * 86400)  # fmt: skip
    return res


@router.get("/logout")
def logout() -> Response:
    res = RedirectResponse("/login" if enabled() else "/", status_code=303)
    res.delete_cookie(COOKIE)
    return res


@router.get("/api/health")
def health() -> dict:
    """도커 · 로드밸런서 상태 확인용 (인증 없이 열림 — 정보는 담지 않는다)."""
    return {"ok": True}


@router.get("/api/me")
def me(request: Request) -> dict:
    """지금 사용자 — 화면이 권한 · 감사 표시에 쓴다."""
    return current_user(request).public() | {"auth": enabled()}
