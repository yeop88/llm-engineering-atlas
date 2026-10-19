"""맵 · 단계의 데이터 구조와 경로 규칙. 데이터(맵 · 단계 목록)는 maps/<맵>.py, 모으기 · 조회는 __init__.py."""

from __future__ import annotations

from dataclasses import dataclass, field

DONE, BASIC, PLANNED = "done", "basic", "planned"
STATUS_LABEL = {DONE: "구현됨", BASIC: "기초 있음", PLANNED: "예정"}


@dataclass(frozen=True)
class Map:
    key: str
    title: str
    href: str
    doc: str  # 맵 개요 문서 (저장소 내 경로)
    summary: str
    diagram: str = ""  # 문서 색인에 넣는 글자 흐름도
    # 아래는 공통 맵 화면(/maps/<key>) · 생성 개요 문서용 — 맵마다 화면 템플릿 · 문서를 손으로 만들지 않으려고(맵이 10개)
    lead: str = ""  # 화면 첫 문단
    groups: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (묶음 설명, 단계 키들) — 묶음 안은 →, 묶음 사이는 ↓
    principles: tuple[str, ...] = ()  # 설계 원칙 (기반 실측에서 가져온 것)
    example: str = ""
    template: str = ""  # 따로 만든 화면이 있으면 그 템플릿, 비우면 공통 화면

    @property
    def slug(self) -> str:
        """맵 이름 하나를 화면 주소 · 개요 문서 · 단계 문서 폴더에 같이 쓴다(docs/maps/<slug>.md, docs/stages/<slug>/)."""
        return self.doc.rsplit("/", 1)[-1].removesuffix(".md")

    @property
    def generated_doc(self) -> bool:
        """전용 화면이 있는 맵(LLM · 지식 그래프 · 멀티에이전트)은 개요도 손으로 쓰고, 단계 표만 생성한다."""
        return not self.template


@dataclass(frozen=True)
class Page:
    nav: str  # 화면의 nav 키 (메뉴 강조 · 상단 설명 연결)
    href: str
    label: str
    desc: str = ""


@dataclass(frozen=True)
class Stage:
    key: str
    no: str  # 흐름도 번호 (메뉴 · 맵 표시)
    title: str
    en: str
    status: str
    summary: str  # 한 줄
    principle: str  # 원리
    why: str  # 왜 하는가
    how: list[str]  # 어떻게 (이 앱에서)
    pages: list[Page] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)  # 앞으로 할 일
    docs: list[tuple[str, str]] = field(default_factory=list)  # (제목, 저장소 내 경로)
    flow: str = "main"  # main = 흐름도 본선, extra = 곁가지(멀티모달 · 의미 응용), kg = 지식 그래프 맵
    short: str = ""  # 메뉴용 짧은 이름 (비우면 title)
    map: str = "llm"  # 속한 맵 (MAPS)
    builds_on: list[str] = field(default_factory=list)  # 이 단계가 위에 짓는 다른 단계(주로 LLM 맵의 구현된 단계) 키

    @property
    def status_label(self) -> str:
        return STATUS_LABEL[self.status]

    @property
    def doc_dir(self) -> str:
        """이 단계 문서 폴더: docs/stages/<맵>/<번호>-<이름>/ — 모든 맵이 같은 규칙. README.md 는 scripts/gen_docs.py 가 만든다.
        이름은 키에서 맵 접두어(3글자 이하, 예: as_ · rc_ · kg_)를 뺀 것 — 번호에 이미 맵이 드러나 'as1-as-intake' 처럼 반복되지 않게."""
        head, _, rest = self.key.partition("_")
        name = (rest if rest and len(head) <= 3 else self.key).replace("_", "-")
        return f"docs/stages/{self.map_info.slug}/{self.no.lower()}-{name}"

    @property
    def readme(self) -> str:
        return f"{self.doc_dir}/README.md"

    @property
    def menu(self) -> str:
        return self.short or self.title

    @property
    def href(self) -> str:
        return self.pages[0].href if self.pages else f"/stages/{self.key}"

    @property
    def map_info(self) -> Map:
        from app.stages.registry import MAP_BY_KEY  # 늦은 import — 패키지가 이 모듈을 먼저 불러오므로

        return MAP_BY_KEY[self.map]
