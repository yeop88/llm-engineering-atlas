"""구조 규칙: 의존 방향 · 파일 배치(테스트 · 화면 스크립트 · 스키마)."""

import ast
import re
from pathlib import Path

from app.stages import registry

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
TESTS = ROOT / "tests"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
        elif isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


def test_dependency_direction():
    """core 는 위 계층을 모르고, 단계 내부 로직은 흐름도 앞 단계만 쓴다. 연결 계층(pipeline)은 API(*_api.py)만 부른다.

    이 규칙이 깨지면 단계를 따로 실험 · 교체하기 어려워지고, 연결 계층을 거치지 않는 검색 경로가 생겨
    '검색 향상을 켰는데 어떤 화면에선 적용이 안 되는' 식의 불일치가 생긴다.
    """
    order = {s.key: i for i, s in enumerate(registry.MAIN_FLOW)} | {s.key: 100 for s in registry.EXTRA}
    # registry 는 단계가 아니라 맵 · 단계의 설명 데이터 — 아래 test_registry_is_data_only 에서 따로 본다
    stage_dirs = {p.name for p in (APP / "stages").iterdir() if p.is_dir() and not p.name.startswith("_") and p.name != "registry"}
    bad = []
    for f in (APP / "core").rglob("*.py"):
        # 예외: core 의 모델 CRUD · 시스템 정보는 1 임베딩의 모델 관리자 · 카탈로그를 쓴다. 모델 카탈로그는 모든 단계가
        # 함께 쓰는 기반이라 core 로 옮기는 편이 맞지만, 옮기는 비용에 비해 얻는 게 적어 1단계만 허용한다.
        bad += [
            f"{f.name} → {m}"
            for m in _imports(f)
            if m.startswith(("app.stages", "app.pipeline", "app.web")) and not m.startswith("app.stages.embedding")
        ]
    for d in stage_dirs:
        for f in (APP / "stages" / d).rglob("*.py"):
            is_api = f.name.endswith("api.py")
            for m in _imports(f):
                if m.startswith("app.web") or (m.startswith("app.pipeline") and not is_api):
                    bad.append(f"{d}/{f.name} → {m}")
                parts = m.split(".")
                if not is_api and len(parts) > 2 and parts[:2] == ["app", "stages"] and parts[2] in stage_dirs:
                    if order.get(parts[2], 0) > order.get(d, 0):
                        bad.append(f"{d}/{f.name} → {m} (뒤 단계)")
    assert not bad, "\n".join(bad)


def test_registry_is_data_only():
    """레지스트리(맵 · 단계 설명)는 다른 앱 모듈을 불러오지 않는다 — 화면 · 문서 생성이 무거운 모델 코드를 끌고 오지 않게."""
    bad = [f"{f.relative_to(APP)} → {m}" for f in (APP / "stages" / "registry").rglob("*.py")
           for m in _imports(f) if m.startswith("app.") and not m.startswith("app.stages.registry")]  # fmt: skip
    assert not bad, bad
    # 맵 하나 = 파일 하나: maps/ 의 모든 파일이 MAP_MODULES 에 들어 있고 MAP · STAGES 를 가진다
    files = {p.stem for p in (APP / "stages" / "registry" / "maps").glob("*.py") if p.stem != "__init__"}
    mods = {m.__name__.rsplit(".", 1)[-1] for m in registry.MAP_MODULES}
    assert files == mods, files ^ mods
    assert all(hasattr(m, "MAP") and hasattr(m, "STAGES") for m in registry.MAP_MODULES)


def test_schemas_live_with_their_stage():
    """요청 스키마는 그 단계 패키지의 schemas.py 에 — core/schemas.py 는 공용만(단계를 import 하지 않음)."""
    assert not [m for m in _imports(APP / "core" / "schemas.py") if m.startswith("app.")]
    lines = len((APP / "core" / "schemas.py").read_text(encoding="utf-8").splitlines())
    assert lines < 80, f"core/schemas.py 가 다시 커졌습니다({lines}줄) — 단계 스키마는 stages/<단계>/schemas.py 로"


def test_page_scripts_live_in_static_files():
    """화면 JS 는 static/js/<영역>/<화면>.js(템플릿과 같은 구조), 공용은 static/js/lib/. 템플릿에는 서버 값 한 줄 설정만 인라인.
    인라인 스크립트가 템플릿 17곳 · 정적 파일 12개로 흩어져 있어 화면 코드를 찾기 어려웠다."""
    tpl = APP / "web" / "templates"
    js = APP / "web" / "static" / "js"
    bad = []
    for t in tpl.rglob("*.html"):
        # 같은 스크립트를 두 번 불러오면 최상위 const 가 다시 선언돼 화면 스크립트 전체가 멈춘다(정리 중 실제로 생겼던 오류)
        srcs = re.findall(r'<script src="([^"]+)"', t.read_text(encoding="utf-8"))
        bad += [f"{t.relative_to(tpl)}: 같은 스크립트를 두 번 불러옴 {s}" for s in {s for s in srcs if srcs.count(s) > 1}]
        for body in re.findall(r"<script>(.*?)</script>", t.read_text(encoding="utf-8"), re.S):
            if len(body.strip().splitlines()) > 1:
                bad.append(f"{t.relative_to(tpl)}: 인라인 스크립트 {len(body.strip().splitlines())}줄")
    for f in js.rglob("*.js"):
        rel = f.relative_to(js).as_posix()
        if rel.startswith("lib/") or rel == "apps/common.js":  # 공용: 모든 화면 · 의미 응용 화면들
            continue
        # 한 화면의 스크립트를 나눌 때는 <화면>_<부분>.js (예: rag/collection_detail_eval.js) — 이름 앞부분이 템플릿과 맞으면 된다
        folder, parts = tpl / f.parent.relative_to(js), f.stem.split("_")
        if not any((folder / ("_".join(parts[:i]) + ".html")).exists() for i in range(len(parts), 0, -1)):
            bad.append(f"static/js/{rel}: 짝이 되는 템플릿이 없음")
    assert not bad, "\n".join(bad)


def test_tests_mirror_app_layout():
    """테스트는 app/ 와 같은 구조: tests/core · tests/pipeline · tests/web · tests/stages/<단계>. 최상위에는 공용 · 구조 · 문서 테스트만."""
    top = sorted(p.name for p in TESTS.glob("*.py"))
    assert top == ["__init__.py", "conftest.py", "helpers.py", "test_architecture.py", "test_docs.py"], top
    dirs = {p.name for p in TESTS.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert dirs == {"core", "pipeline", "stages", "web"}, dirs
    app_stages = {p.name for p in (APP / "stages").iterdir() if p.is_dir() and not p.name.startswith("_")}
    test_stages = {p.name for p in (TESTS / "stages").iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert test_stages <= app_stages, test_stages - app_stages


# ── 화면 규칙 (1.0 UI 개편) ─────────────────────────────────────────────────
PAGE_JS = [f for f in (APP / "web" / "static" / "js").rglob("*.js") if "lib" not in f.parts]
TEMPLATES = [t for t in (APP / "web" / "templates").rglob("*.html") if t.parent.name != "_ui" and t.name != "base.html"]


def test_pages_use_shared_header():
    """모든 화면은 공통 머리말(templates/_ui/macros.html page_header) — 제목 · 설명 접기 · 동작 버튼 · 뒤로 가기가 같은 모양."""
    bad = [t.relative_to(APP).as_posix() for t in TEMPLATES if "ui.page_header" not in t.read_text(encoding="utf-8")]
    assert not bad, bad


def test_labels_are_connected():
    """이름표는 입력란과 연결(for=id 또는 입력란을 감쌈) — 이름표를 눌러도 입력란에 커서가 가고, 화면 낭독기가 입력 이름을 읽는다.
    개편 전에는 이름표 302개 중 연결된 것이 0개였다."""
    bad = []
    for t in TEMPLATES:
        for m in re.finditer(r"<label(?![^>]*\bfor=)[^>]*>(.*?)</label>", t.read_text(encoding="utf-8"), re.S):
            if not re.search(r"<(input|select|textarea)\b", m.group(1)):
                bad.append(f"{t.relative_to(APP).as_posix()}: {m.group(0)[:60]}")
    assert not bad, "\n".join(bad)


def test_page_scripts_use_shared_ui():
    """삭제 확인은 ui.confirm / ui.choose (브라우저 기본 confirm() 은 무엇이 함께 지워지는지 적을 수 없고 Enter 한 번에 실행된다).
    인라인 style · 손으로 부르는 esc() 는 지금보다 늘리지 않는다 — 새 코드는 유틸리티 클래스와 자동 이스케이프 html`` 로."""
    bad = [f.name for f in PAGE_JS if re.search(r"(?<![.\w])confirm\(", f.read_text(encoding="utf-8"))]
    assert not bad, bad
    styles = sum(f.read_text(encoding="utf-8").count('style="') for f in PAGE_JS + TEMPLATES)
    escs = sum(len(re.findall(r"(?<![\w.])esc\(", f.read_text(encoding="utf-8"))) for f in PAGE_JS)  # reEsc( 같은 다른 이름은 빼고
    # 개편 때 인라인 style 446 → 83(남은 것은 대부분 막대 폭처럼 값이 바뀌는 것), esc() 450 → 3.
    # 남은 esc() 3곳은 '글자를 먼저 이스케이프한 뒤 <mark> · 근거 칩을 끼우고 raw() 로 돌려주는' 형광펜 · 답변 본문 함수.
    assert styles <= 90, f"인라인 style 이 {styles}곳으로 늘었습니다 — static/css/style.css 의 유틸리티 클래스를 쓰세요"
    assert escs <= 3, f"손으로 부르는 esc() 가 {escs}곳으로 늘었습니다 — html`` (lib/common.js) 를 쓰세요"
    # 지역 변수 이름이 html 이면 그 함수 안의 html`` 이 태그 함수가 아니라 그 변수를 불러 바로 오류가 난다(전환 때 3곳 있었다)
    shadow = [f.name for f in PAGE_JS + [APP / "web" / "static" / "js" / "lib" / "charts.js"]
              if re.search(r"\b(let|const|var)\s+html\b|function\s+\w*\s*\([^)]*\bhtml\b", f.read_text(encoding="utf-8"))]  # fmt: skip
    assert not shadow, shadow
