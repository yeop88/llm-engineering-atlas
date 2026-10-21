"""맵과 단계 레지스트리 — 사이드바 · 화면 라우트 · 단계 설명 서랍 · 단계 소개 · 맵 화면 · 빠른 이동 · 문서가 모두 여기서 만들어진다.

구조 (한 파일 2,900줄을 나눴다 — 맵을 고치거나 더할 때 그 맵 파일만 보면 되게)
- model.py            데이터 구조(Map · Page · Stage)와 경로 규칙
- maps/<맵>.py        맵 1개 = 파일 1개: MAP(흐름 · 원칙 · 예시)와 STAGES(단계의 원리 · 왜 · 어떻게 · 할 일 · 기반 단계)
- __init__.py         맵 순서(MAP_MODULES)로 모으고 조회 함수를 둔다

새 맵 추가: maps/<맵>.py 를 만들고 MAP_MODULES 에 한 줄 → `uv run python scripts/gen_docs.py`. 상세 체크리스트는 docs/guides/architecture.md.
"""

from app.stages.registry.maps import (
    analytics,
    as_service,
    coding,
    compliance,
    computer_use,
    context,
    conversation,
    docintel,
    edge,
    evalops,
    flywheel,
    guardrails,
    interop,
    interp,
    knowledge_graph,
    llm,
    longrun,
    multi_agent,
    platform,
    posttrain,
    reasoning,
    rlvr,
    serving,
    voice,
)  # fmt: skip
from app.stages.registry.model import BASIC, DONE, PLANNED, STATUS_LABEL, Map, Page, Stage

# 메뉴 · 문서 색인에 나오는 순서
MAP_MODULES = [llm, knowledge_graph, multi_agent, evalops, guardrails, docintel, serving, conversation, as_service, posttrain,
               flywheel, platform, interop, voice, compliance, longrun, rlvr, edge,
               reasoning, context, analytics, coding, computer_use, interp]  # fmt: skip
MAPS: list[Map] = [m.MAP for m in MAP_MODULES]
MAP_BY_KEY = {m.key: m for m in MAPS}
STAGES: list[Stage] = [s for m in MAP_MODULES for s in m.STAGES]
BY_KEY = {s.key: s for s in STAGES}
MAIN_FLOW = [s for s in STAGES if s.flow == "main"]
EXTRA = [s for s in STAGES if s.flow == "extra"]
KG_FLOW = [s for s in STAGES if s.map == "kg"]
AGENTS_FLOW = [s for s in STAGES if s.map == "agents"]
OTHER_MAP_STAGES = [s for s in STAGES if s.map != "llm"]


def map_stages(key: str) -> list[Stage]:
    return [s for s in STAGES if s.map == key]


def map_flow(stage: Stage) -> list[Stage]:
    """이전 · 다음 단계를 잇는 흐름. LLM 맵은 본선만(곁가지 없음), 다른 맵은 그 맵의 단계 순서."""
    if stage.map == "llm":
        return MAIN_FLOW if stage.flow == "main" else []
    return map_stages(stage.map)


def stage_for_nav(nav: str | None) -> Stage | None:
    """화면의 nav 키 → 그 화면이 속한 단계 (단계 설명 서랍 · 위치 표시용)."""
    if not nav:
        return None
    if nav.startswith("stage_"):
        return BY_KEY.get(nav[6:])
    return next((s for s in STAGES if any(p.nav == nav for p in s.pages)), None)


__all__ = ["BASIC", "DONE", "PLANNED", "STATUS_LABEL", "Map", "Page", "Stage", "MAPS", "MAP_BY_KEY", "STAGES", "BY_KEY", "MAIN_FLOW", "EXTRA",
           "KG_FLOW", "AGENTS_FLOW", "OTHER_MAP_STAGES", "map_stages", "map_flow", "stage_for_nav"]  # fmt: skip
