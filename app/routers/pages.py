"""Jinja2 로 렌더링하는 웹 UI 페이지. 데이터는 각 페이지의 JS 가 /api 에서 가져온다."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.catalog import CATALOG_VERSION
from app.config import BASE_DIR, get_settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals.update(app_name=get_settings().app_name, catalog_version=CATALOG_VERSION)

PAGES = {
    "/": ("dashboard.html", "dashboard"),
    "/models": ("models.html", "models"),
    "/hub": ("hub.html", "hub"),
    "/playground": ("playground.html", "playground"),
    "/multimodal": ("multimodal.html", "multimodal"),
    "/benchmark": ("benchmark.html", "benchmark"),
    "/history": ("history.html", "history"),
}


def _page(template: str, nav: str):
    def view(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, template, {"nav": nav})

    return view


for path, (template, nav) in PAGES.items():
    router.add_api_route(path, _page(template, nav), methods=["GET"], response_class=HTMLResponse, name=nav)


@router.get("/models/{model_id}", response_class=HTMLResponse)
def model_detail(request: Request, model_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "model_detail.html", {"nav": "models", "model_id": model_id})
