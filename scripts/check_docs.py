"""문서와 코드가 어긋나지 않았는지 검사한다: 문서에 적은 저장소 경로가 실제로 있는지, 화면 주소가 지금 주소인지.

파일 이동 · 이름 변경 · 화면 주소 변경 뒤 문서가 예전 이름을 가리키는 일이 반복돼(1.0 정리 때 가이드 · 단계 문서 여러 곳)
사람이 기억하는 대신 검사한다. tests/test_docs.py 가 docs/ · README.md 에 돌리고, 직접 돌릴 때는
`uv run python scripts/check_docs.py [파일...]`(파일을 주지 않으면 docs/ · README.md).

- 경로: 백틱 안의 `app/…` · `tests/…` · `docs/…` · `scripts/…` · `migrations/…` 가 있어야 한다(`<맵>` · `*` 같은 자리 표시는 앞부분까지만).
- 화면 주소: 백틱 안의 `/…` 중 화면 영역(`/rag/…` · `/embedding/…` · `/maps/…` 처럼 화면 주소의 첫 마디, 레지스트리에서 뽑음)이나
  예전 주소로 시작하는 것은 지금 화면이어야 한다(예전 주소 → 308 넘기기는 실패). API 안쪽 경로(`/chat/completions`) 같은 건 보지 않는다.
- 바뀐 내역을 적는 CHANGELOG.md 와 정정 기록(docs/records/)은 예전 이름이 나오는 게 맞아 빼고 검사한다.
  다른 문서에서 일부러 예전 이름을 적는 줄(예: 0.x → 1.0 비교 표)은 그 줄에 `<!-- 예전 이름 -->` 을 붙이면 뺀다.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH_RE = re.compile(r"`((?:app|tests|docs|scripts|migrations)/[^`\s]*)`")
URL_RE = re.compile(r"`(/[a-z][a-z0-9/_-]*)(?:[?#][^`]*)?`")
# OpenAI 호환 음성 경로(/audio/transcriptions · /audio/speech)는 바깥 서버(STT_URL · TTS_URL) 뒤에 붙는 경로다 — 오디오 맵 화면(/audio/…)이 생겨
# 첫 마디가 같아져도 화면 주소로 보지 않는다
SKIP_URL = ("/api", "/docs", "/static", "/login", "/logout", "/ui/", "/v1", "/audio/transcriptions", "/audio/speech")
IGNORE = "<!-- 예전 이름 -->"


def page_prefixes() -> set[str]:
    """화면 주소의 첫 마디(/rag · /embedding · /maps …)와 예전 주소 — 이것으로 시작하는 백틱 주소만 화면 주소로 본다."""
    from app.stages import registry
    from app.web.pages import REDIRECT_PREFIXES, REDIRECTS, all_pages

    hrefs = [p.href for p in all_pages()] + [m.href for m in registry.MAPS] + ["/stages/x"]
    return {"/" + h.strip("/").split("/")[0] for h in hrefs if h != "/"} | set(REDIRECTS) | {k.rstrip("/") for k in REDIRECT_PREFIXES}


def doc_files() -> list[Path]:
    """검사 대상: README.md + docs/**/*.md (생성 문서 포함, 정정 기록 제외)."""
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    return [f for f in files if "records" not in f.relative_to(ROOT).parts]


def _base(path: str) -> str:
    # 자리 표시(<맵> · <번호>-<이름> · * · …)가 시작되는 곳 앞까지만 — 그 앞 폴더는 있어야 한다
    cut = min([i for i in (path.find("<"), path.find("*"), path.find("{"), path.find("…")) if i >= 0], default=len(path))
    return path[:cut].rstrip("/").split("::")[0].split("#")[0]


def missing_paths(text: str) -> list[str]:
    out = []
    for m in PATH_RE.finditer(text):
        p = _base(m.group(1))
        if p.count("/") == 0 or not p:
            continue
        cand = ROOT / p
        # 'app/stages/registry/maps/<맵>.py' → 'app/stages/registry/maps' 처럼 잘린 이름은 그 폴더나 그 이름으로 시작하는 파일이면 된다
        if not (cand.exists() or any(cand.parent.glob(cand.name + "*"))):
            out.append(m.group(1))
    return out


def page_urls(text: str, prefixes: set[str]) -> list[str]:
    urls = []
    for m in URL_RE.finditer(text):
        u = m.group(1).rstrip("/")
        if u and not u.startswith(SKIP_URL) and "<" not in m.group(0) and "/" + u.strip("/").split("/")[0] in prefixes:
            urls.append(u)
    return urls


def check(files: list[Path], client=None) -> list[str]:
    """어긋난 곳 목록. client(FastAPI TestClient)를 주면 화면 주소도 검사한다."""
    problems = []
    prefixes = page_prefixes() if client is not None else set()
    for f in files:
        text = "\n".join(line for line in f.read_text(encoding="utf-8").splitlines() if IGNORE not in line)
        rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
        problems += [f"{rel}: 없는 경로 `{p}`" for p in missing_paths(text)]
        if client is not None:
            for u in sorted(set(page_urls(text, prefixes))):
                r = client.get(u, follow_redirects=False)
                if r.status_code == 308:
                    problems.append(f"{rel}: 예전 화면 주소 `{u}` → `{r.headers['location']}`")
                elif r.status_code == 404:
                    problems.append(f"{rel}: 없는 화면 주소 `{u}`")
    return problems


def main(argv: list[str]) -> int:
    import logging

    from fastapi.testclient import TestClient

    from app.main import app

    logging.disable(logging.INFO)  # 요청마다 찍히는 로그 대신 결과만

    files = [Path(a).resolve() for a in argv] or doc_files()
    with TestClient(app) as client:
        problems = check(files, client)
    sys.stdout.reconfigure(errors="replace")  # Windows 콘솔(cp949)
    print("\n".join(problems) if problems else f"어긋난 곳 없음 ({len(files)}개 파일)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main(sys.argv[1:]))
