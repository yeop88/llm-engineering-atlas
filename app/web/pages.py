"""Jinja2 로 렌더링하는 웹 UI 페이지. 데이터는 각 페이지의 JS 가 /api 에서 가져온다.

화면 목록은 단계 레지스트리(app/stages/registry/)의 Page 가 한 곳에서 정한다 — 주소 · 템플릿 · 메뉴 이름으로
라우트 · 사이드바 · 위치 표시(breadcrumb) · 빠른 이동(Ctrl K) 색인을 모두 만든다. 새 화면은 레지스트리에 Page 한 줄.
단계에 속하지 않는 공통 화면(대시보드 · 이력 · 맵 목록 · 설정)만 아래 COMMON_PAGES 에 둔다.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core import auth
from app.core.config import APP_DIR, get_settings
from app.stages import registry
from app.stages.embedding.catalog import CATALOG_VERSION
from app.stages.registry import Page, ecosystem

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=APP_DIR / "web" / "templates")

# 단계 밖 공통 화면: (nav 키, 주소, 이름, 템플릿)
COMMON_PAGES = [
    Page("dashboard", "/", "대시보드", "연결 상태 · 맵 진행 · 최근 실험 · 작업", "dashboard.html"),
    Page("maps", "/maps", "모든 맵", f"맵 {len(registry.MAPS)}개 · 그룹 A~F · 단계 상태", "maps/index.html"),
    # 생태계 구조는 맵이 아니라 맵들을 잇는 대응표라 공통 화면 — /maps/{slug} 보다 먼저 등록되어야 맵 주소로 오인되지 않는다
    Page("ecosystem", "/maps/ecosystem", "LLM 생태계 구조", "생태계 맵 34개 대응 · 온톨로지 · 통합 라우팅", "maps/ecosystem.html"),
    Page("history", "/history", "이력", "실행 기록 · 비교 · 삭제", "history.html"),
    Page("settings_llm", "/settings/llm", "LLM 연결", "로컬 · OpenAI 호환 · Claude", "settings/llm.html"),
]

# 1.0 에서 주소 규칙을 /<단계>/<화면> 으로 맞췄다. 북마크 · 문서 링크가 깨지지 않게 예전 주소는 새 주소로 넘긴다(308: 영구 · 방법 유지).
REDIRECTS = {
    "/models": "/embedding/models",
    "/hub": "/embedding/hub",
    "/playground": "/embedding/playground",
    "/benchmark": "/embedding/benchmark",
    "/collections": "/rag/collections",
    "/llm": "/settings/llm",
    "/roadmap": "/maps/llm",
}
REDIRECT_PREFIXES = {"/models/": "/embedding/models/", "/collections/": "/rag/collections/"}


def _llm_stages() -> list:
    return [s for s in registry.MAIN_FLOW + registry.EXTRA if s.pages]


def sidebar() -> list[dict]:
    """사이드바: 시작 · 실험(LLM 맵 단계 순서) · 맵 · 기록과 설정. 항목은 모두 레지스트리에서 — 단계 · 화면 · 맵이 늘어도 이 코드는 그대로."""
    experiments = []
    for s in _llm_stages():
        keys = [p.nav for p in s.pages] + [f"stage_{s.key}"]
        item = {"label": s.menu, "no": s.no, "href": s.href, "keys": keys, "status": s.status, "children": []}
        if len(s.pages) > 1:
            item["children"] = [{"label": p.label, "href": p.href, "key": p.nav} for p in s.pages]
        experiments.append(item)
    # 운영 · 서비스: LLM 맵 밖에서 화면이 있는 맵(문서 처리 · 가드레일 · 평가 · AS). 맵 하나 = 항목 하나, 화면은 펼침 —
    # 단계(30개)를 다 늘어놓으면 사이드바가 길어지고, 화면 하나가 여러 단계를 함께 다룬다
    ops = []
    for m in registry.MAPS:
        stages = registry.map_stages(m.key)
        pages = [p for s in stages for p in s.pages]
        if m.key == "llm" or not pages:
            continue
        ops.append({"label": m.title.removesuffix(" 맵").split(": ")[-1].split(" (")[0], "href": m.href, "icon": "▸",
                    "keys": [f"map_{m.key}"] + [p.nav for p in pages] + [f"stage_{s.key}" for s in stages],
                    "children": [{"label": p.label, "href": p.href, "key": p.nav} for p in pages if p.template]})  # fmt: skip
    maps = [{"label": m.title.removesuffix(" 맵"), "href": m.href, "key": f"map_{m.key}"} for m in registry.MAPS]
    common = {p.nav: p for p in COMMON_PAGES}
    return [
        {"title": "", "items": [{"label": "대시보드", "href": "/", "keys": ["dashboard"], "icon": "◇", "children": []}]},
        {"title": "실험 · LLM 시스템 맵", "items": experiments},
        {"title": "운영 · 서비스", "items": ops},
        {"title": "맵", "items": [
            {"label": "모든 맵", "href": "/maps", "keys": ["maps"], "icon": "▦", "children": []},
            {"label": f"맵 {len(maps)}개", "href": None, "keys": [m["key"] for m in maps] + [f"stage_{s.key}" for s in registry.OTHER_MAP_STAGES],
             "icon": "☷", "children": maps, "group": "maps"},
        ]},
        {"title": "기록 · 설정", "items": [
            {"label": common["history"].label, "href": "/history", "keys": ["history"], "icon": "↺", "children": []},
            {"label": common["settings_llm"].label, "href": "/settings/llm", "keys": ["settings_llm"], "icon": "⚙", "children": []},
            {"label": "API 문서", "href": "/docs", "keys": [], "icon": "{}", "children": [], "external": True},
        ]},
    ]  # fmt: skip


def crumbs(nav: str | None) -> list[tuple[str, str | None]]:
    """위치 표시: (이름, 주소) 목록. 마지막은 지금 화면(주소 없음). 상세 화면은 JS 가 대상 이름을 덧붙인다(setCrumb)."""
    if not nav or nav == "dashboard":
        return [("대시보드", None)]
    for p in COMMON_PAGES:
        if p.nav == nav:
            return [("설정", None), (p.label, None)] if nav.startswith("settings_") else [(p.label, None)]
    if nav.startswith("map_"):
        m = registry.MAP_BY_KEY.get(nav[4:])
        return [("맵", "/maps"), (m.title if m else "맵", None)]
    st = registry.stage_for_nav(nav)
    if st is None:
        return []
    head = (f"{st.no} {st.menu}", st.href) if st.map == "llm" else (st.map_info.title.removesuffix(" 맵"), st.map_info.href)
    if nav == f"stage_{st.key}":
        return [head, ((f"{st.no} {st.title}" if st.map != "llm" else "단계 소개"), None)]
    page = next(p for p in st.pages if p.nav == nav)
    return [head, (page.label, None)]


def search_index() -> list[dict]:
    """빠른 이동(Ctrl K) 색인: 화면 · 단계 · 맵. 컬렉션처럼 데이터에 있는 것은 브라우저가 /api 에서 함께 찾는다."""
    out = [{"type": "화면", "label": p.label, "desc": p.desc, "href": p.href} for p in COMMON_PAGES]
    for s in registry.STAGES:
        out += [{"type": "화면", "label": p.label, "desc": f"{s.no} {s.title} · {p.desc}", "href": p.href} for p in s.pages]
        out.append(
            {
                "type": "단계",
                "label": f"{s.no} {s.title}",
                "desc": f"{s.map_info.title} · {s.status_label} · {s.summary}",
                "href": f"/stages/{s.key}",
            }
        )
    out += [{"type": "맵", "label": m.title, "desc": m.summary, "href": m.href} for m in registry.MAPS]
    return out


def doc_url(path: str) -> str:
    return f"{get_settings().repo_url}/blob/main/{path}"


templates.env.globals.update(
    app_name=get_settings().app_name, catalog_version=CATALOG_VERSION, sidebar=sidebar(), crumbs=crumbs, registry=registry, ecosystem=ecosystem,
    stage_for_nav=registry.stage_for_nav, doc_url=doc_url,
    auth_enabled=auth.enabled,  # 함수로 둬 테스트 · 설정 변경이 바로 반영되게
)  # fmt: skip


def all_pages() -> list[Page]:
    """라우트를 만들 화면: 공통 화면 + 레지스트리의 단계 화면(템플릿이 있는 것)."""
    return COMMON_PAGES + [p for s in registry.STAGES for p in s.pages if p.template]


def _page(page: Page, extra: dict | None = None):
    def view(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, page.template, {"nav": page.nav, "page": page, **(extra or {})})

    return view


APP_NAMES = [p.href.rsplit("/", 1)[-1] for p in registry.BY_KEY["apps"].pages if p.href != "/apps"]

for _p in all_pages():
    _extra = {"available": APP_NAMES} if _p.nav == "apps" else None
    router.add_api_route(_p.href, _page(_p, _extra), methods=["GET"], response_class=HTMLResponse, name=_p.nav)

# 전용 화면이 있는 맵(LLM · 지식 그래프 · 멀티에이전트) — 나머지 맵은 아래 공통 화면
for _m in registry.MAPS:
    if _m.template:
        router.add_api_route(_m.href, _page(Page(f"map_{_m.key}", _m.href, _m.title, template=_m.template)), methods=["GET"],
                             response_class=HTMLResponse, name=f"map_{_m.key}")  # fmt: skip


@router.get("/ui/search-index.json")
def ui_search_index() -> JSONResponse:
    return JSONResponse(search_index())


@router.get("/embedding/models/{model_id}", response_class=HTMLResponse)
def model_detail(request: Request, model_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "embedding/model_detail.html", {"nav": "models", "model_id": model_id})


@router.get("/rag/collections/{collection_id}", response_class=HTMLResponse)
def collection_detail(request: Request, collection_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "rag/collection_detail.html", {"nav": "rag", "collection_id": collection_id})


def _not_found(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "maps/index.html", {"nav": "maps", "not_found": True}, status_code=404)


@router.get("/maps/{slug}", response_class=HTMLResponse)
def map_page(request: Request, slug: str) -> HTMLResponse:
    """따로 만든 화면이 없는 맵은 공통 화면으로 (전용 화면이 있는 맵은 위에서 먼저 잡힌다)."""
    m = next((x for x in registry.MAPS if x.href == f"/maps/{slug}"), None)
    if m is None or m.template:
        return _not_found(request)
    return templates.TemplateResponse(request, "maps/generic.html", {"nav": f"map_{m.key}", "m": m})


@router.get("/apps/{name}", response_class=HTMLResponse)
def unknown_app(request: Request, name: str) -> HTMLResponse:
    """레지스트리에 없는 응용 이름(있는 응용은 위의 화면 라우트가 먼저 잡는다)."""
    return templates.TemplateResponse(request, "apps/apps.html", {"nav": "apps", "available": APP_NAMES}, status_code=404)


@router.get("/stages/{key}", response_class=HTMLResponse)
def stage_page(request: Request, key: str) -> HTMLResponse:
    """단계 소개: 원리 · 왜 · 어떻게 · 현재 상태 · 화면 · 할 일 (예정 단계도 여기서 설명한다)."""
    st = registry.BY_KEY.get(key)
    if st is None:
        return _not_found(request)
    return templates.TemplateResponse(request, "stage.html", {"nav": f"stage_{key}", "stage": st})


def _redirect(request: Request, to: str) -> RedirectResponse:
    q = request.url.query
    return RedirectResponse(to + (f"?{q}" if q else ""), status_code=308)


def _to(new: str):
    def view(request: Request) -> RedirectResponse:  # Request 타입이 있어야 FastAPI 가 쿼리 값으로 오해하지 않는다
        return _redirect(request, new)

    return view


def _to_prefix(new: str):
    def view(request: Request, rest: str) -> RedirectResponse:
        return _redirect(request, new + rest)

    return view


for _old, _new in REDIRECTS.items():
    router.add_api_route(_old, _to(_new), methods=["GET"])
for _old, _new in REDIRECT_PREFIXES.items():
    router.add_api_route(_old + "{rest:path}", _to_prefix(_new), methods=["GET"])
