"""맵 · 단계의 데이터 구조와 경로 규칙. 데이터(맵 · 단계 목록)는 maps/<맵>.py, 모으기 · 조회는 __init__.py."""

from __future__ import annotations

from dataclasses import dataclass, field

DONE, BASIC, PLANNED = "done", "basic", "planned"
# 연구 = 이 PC · 공개 모델로는 아직 제대로 돌릴 수 없어 설계 · 문헌 정리와 작은 흉내 실험만(생성 미디어 · 풀듀플렉스 등),
# 보류 = 하지 않기로 미룬 것(이유를 plans 에). 예정과 나눈 이유: '곧 만든다'와 '지금은 만들 수 없다'를 같은 표시로 두면 계획이 흐려진다
RESEARCH, HOLD = "research", "hold"
STATUS_LABEL = {DONE: "구현됨", BASIC: "기초 있음", PLANNED: "예정", RESEARCH: "연구", HOLD: "보류"}
STATUSES = (DONE, BASIC, PLANNED, RESEARCH, HOLD)


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
    # 생태계 자리(registry/ecosystem.py) — 구현 상태(단계 상태)와 기술 성숙도를 따로 적는다
    group: str = ""  # 상위 그룹 A~F
    eco: tuple[str, ...] = ()  # 이 맵이 덮는 생태계 맵 번호(M1~M30 · E1~E4)
    maturity: str = ""  # 기초 · 성숙 · 신선 · 실험적
    depends_on: tuple[str, ...] = ()  # 이 맵이 기대는 다른 앱 맵 키
    last_verified_at: str = ""  # 이 맵의 기술 설명을 마지막으로 확인한 날(YYYY-MM-DD)
    evidence_level: str = ""  # measured · implemented · documented · survey (ecosystem.EVIDENCE)

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
    """단계의 화면 하나. 주소 · 템플릿 · 메뉴 이름이 여기 한 곳에 있어 라우트 · 사이드바 · 빠른 이동 · 위치 표시가 모두 이것으로 만들어진다
    (예전에는 web/pages.py 의 PAGES · 의미 응용 목록 · 메뉴 코드를 따로 고쳐야 했다)."""

    nav: str  # 화면의 nav 키 (메뉴 강조 · 단계 설명 연결)
    href: str  # 주소 규칙: 화면이 여럿인 단계는 /<단계>/<화면>, 하나인 단계는 /<단계>
    # 한 화면이 여러 단계를 다루면(운영 맵) 나머지 단계는 '/<화면 주소>#<부분>' + 템플릿 없음 — 라우트 · 사이드바 항목을 만들지 않고 단계 소개 · 빠른 이동에서 그 부분으로 간다
    label: str
    desc: str = ""
    template: str = ""  # web/templates 아래 경로. 비우면 라우트를 만들지 않음(상세 화면처럼 web/pages.py 가 직접 만드는 경우)


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
