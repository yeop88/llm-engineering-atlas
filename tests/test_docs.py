"""문서: 생성 문서가 레지스트리와 같은지, 상대 링크(파일 · 제목 앵커)가 깨지지 않았는지."""

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from app.stages import registry

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def slug(title: str) -> str:
    """GitHub 제목 앵커: 소문자, 글자 · 숫자 · 공백 · 하이픈 · 밑줄만 남기고 공백을 하이픈으로."""
    t = re.sub(r"`|\*\*|\[|\]\([^)]*\)", "", title).lower()
    kept = "".join(c for c in t if c in " -_" or unicodedata.category(c)[0] in "LMN")
    return kept.replace(" ", "-")


def md_files() -> list[Path]:
    return [*sorted((ROOT / "docs").rglob("*.md")), ROOT / "README.md", ROOT / "CHANGELOG.md"]


def test_generated_docs_are_up_to_date():
    # 자식 프로세스의 출력 인코딩을 UTF-8 로 고정 — Windows 기본(cp949)으로 한국어를 출력하면 읽는 쪽에서 디코딩 오류가 난다
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_docs.py"), "--check"], capture_output=True, text=True, encoding="utf-8", env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_registry_doc_paths_exist():
    for s in registry.STAGES:
        assert (ROOT / s.readme).is_file(), s.readme
        for _, path in s.docs:
            assert (ROOT / path.split("#")[0]).is_file(), path


def test_relative_links_resolve():
    broken = []
    anchors: dict[Path, set[str]] = {}
    for f in md_files():
        text = f.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if re.match(r"^[a-z]+:", target):
                continue
            path, _, anchor = target.partition("#")
            dest = (f.parent / path).resolve() if path else f
            if not dest.exists():
                broken.append(f"{f.relative_to(ROOT)} → {target}")
                continue
            if anchor and dest.suffix == ".md":
                if dest not in anchors:
                    anchors[dest] = {slug(h) for h in HEADING.findall(dest.read_text(encoding="utf-8"))}
                if anchor not in anchors[dest]:
                    broken.append(f"{f.relative_to(ROOT)} → {target} (앵커 없음)")
    assert not broken, "\n".join(broken)


def test_docs_layout_is_consistent():
    """문서 구조 규칙(docs/README.md '구조'): 맵 개요는 docs/maps/<맵>.md, 단계는 docs/stages/<맵>/<번호>-<이름>/ — 맵마다 위치가 달랐던 것을 맞춘 뒤 다시 흩어지지 않게."""
    docs = ROOT / "docs"
    assert sorted(p.name for p in docs.glob("*.md")) == ["README.md"]  # 최상위에는 색인만
    slugs = {m.slug for m in registry.MAPS}
    assert {p.name for p in (docs / "stages").iterdir() if p.is_dir()} == slugs
    assert {p.stem for p in (docs / "maps").glob("*.md")} == slugs
    for m in registry.MAPS:
        assert m.doc == f"docs/maps/{m.slug}.md"
        text = (ROOT / m.doc).read_text(encoding="utf-8")
        assert "## 단계" in text and "| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |" in text, m.doc  # 모든 맵에 같은 단계 표
    for s in registry.STAGES:
        folder = s.doc_dir.split("/")
        assert folder[:3] == ["docs", "stages", s.map_info.slug] and folder[3].startswith(s.no.lower() + "-"), s.doc_dir
