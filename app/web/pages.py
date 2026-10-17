"""Jinja2 로 렌더링하는 웹 UI 페이지. 데이터는 각 페이지의 JS 가 /api 에서 가져온다."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import APP_DIR, get_settings
from app.stages import registry
from app.stages.embedding.catalog import CATALOG_VERSION

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=APP_DIR / "web" / "templates")


def nav_items() -> list[dict]:
    """메뉴: 흐름도 순서. 화면이 여러 개인 단계는 드롭다운, 예정 단계(⑥~⑧)는 하나로 묶는다."""
    items: list[dict] = [
        {"label": "대시보드", "href": "/", "keys": ["dashboard"]},
        {"label": "맵", "href": "/roadmap", "keys": ["roadmap"]},
    ]
    later: list[dict] = []
    for s in registry.MAIN_FLOW:
        label = f"{s.no} {s.menu}"
        if s.no[0] in "678":
            later.append({"label": label, "href": s.href, "desc": f"{s.status_label} · {s.summary}", "key": f"stage_{s.key}"})
        elif len(s.pages) > 1:
            sub = [{"label": p.label, "href": p.href, "desc": p.desc, "key": p.nav} for p in s.pages]
            sub.append({"label": "단계 소개", "href": f"/stages/{s.key}", "desc": "원리 · 왜 · 어떻게", "key": f"stage_{s.key}"})
            items.append({"label": label, "items": sub, "keys": [x["key"] for x in sub]})
        else:
            keys = [p.nav for p in s.pages] + [f"stage_{s.key}"]
            items.append({"label": label, "href": s.href, "keys": keys})
    items.append({"label": "6~8 라우팅·모델", "items": later, "keys": [x["key"] for x in later]})
    for s in registry.EXTRA:
        items.append({"label": s.title, "href": s.href, "keys": [p.nav for p in s.pages] + [f"stage_{s.key}"]})
    items.append({"label": "이력", "href": "/history", "keys": ["history"]})
    return items


def doc_url(path: str) -> str:
    return f"{get_settings().repo_url}/blob/main/{path}"


templates.env.globals.update(
    app_name=get_settings().app_name, catalog_version=CATALOG_VERSION, nav_items=nav_items(), registry=registry,
    stage_for_nav=registry.stage_for_nav, doc_url=doc_url,
)  # fmt: skip

PAGES = {
    "/": ("dashboard.html", "dashboard"),
    "/models": ("embedding/models.html", "models"),
    "/hub": ("embedding/hub.html", "hub"),
    "/playground": ("embedding/playground.html", "playground"),
    "/multimodal": ("multimodal/multimodal.html", "multimodal"),
    "/benchmark": ("embedding/benchmark.html", "benchmark"),
    "/history": ("history.html", "history"),
    "/collections": ("rag/collections.html", "rag"),
    "/llm": ("rag/llm.html", "llm"),
    "/rag/answer": ("rag/answer.html", "rag_answer"),
    "/finetune": ("finetune/finetune.html", "finetune"),
    "/roadmap": ("roadmap.html", "roadmap"),
}


def _page(template: str, nav: str):
    def view(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, template, {"nav": nav})

    return view


for path, (template, nav) in PAGES.items():
    router.add_api_route(path, _page(template, nav), methods=["GET"], response_class=HTMLResponse, name=nav)


@router.get("/models/{model_id}", response_class=HTMLResponse)
def model_detail(request: Request, model_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "embedding/model_detail.html", {"nav": "models", "model_id": model_id})


@router.get("/collections/{collection_id}", response_class=HTMLResponse)
def collection_detail(request: Request, collection_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "rag/collection_detail.html", {"nav": "rag", "collection_id": collection_id})


APP_PAGES = {
    "recommend": "콘텐츠 추천",
    "classify": "텍스트 분류",
    "cluster": "클러스터링",
    "dedup": "중복·표절 검사",
    "anomaly": "이상·신종 탐지",
    "keywords": "키워드·요약",
}


@router.get("/apps", response_class=HTMLResponse)
def apps_hub(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "apps/apps.html", {"nav": "apps", "available": list(APP_PAGES)})


@router.get("/apps/{name}", response_class=HTMLResponse)
def app_page(request: Request, name: str) -> HTMLResponse:
    if name not in APP_PAGES:
        return templates.TemplateResponse(request, "apps/apps.html", {"nav": "apps", "available": list(APP_PAGES)}, status_code=404)
    return templates.TemplateResponse(request, f"apps/{name}.html", {"nav": "apps", "app_name_key": name, "app_title": APP_PAGES[name]})


@router.get("/stages/{key}", response_class=HTMLResponse)
def stage_page(request: Request, key: str) -> HTMLResponse:
    """단계 소개: 원리 · 왜 · 어떻게 · 현재 상태 · 화면 · 할 일 (예정 단계도 여기서 설명한다)."""
    st = registry.BY_KEY.get(key)
    if st is None:
        return templates.TemplateResponse(request, "roadmap.html", {"nav": "roadmap"}, status_code=404)
    return templates.TemplateResponse(request, "stage.html", {"nav": f"stage_{key}", "stage": st})
