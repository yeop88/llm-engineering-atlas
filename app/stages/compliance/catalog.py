"""규제 대응 맵의 기준 자료(presets/*.json): 규제 목록 · 서비스 기능 · 적용 규칙 · 통제 · 위험 등급 기준표 · 의무 질문.

코드가 아니라 파일로 두는 이유: 조항 · 통제 연결은 법이 바뀌거나 기능이 늘 때마다 고쳐야 하고, 검토하는 사람이 코드를 몰라도 읽을 수 있어야 한다.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

PRESETS = Path(__file__).parent / "presets"


@cache
def _load(name: str) -> dict[str, Any]:
    return json.loads((PRESETS / f"{name}.json").read_text(encoding="utf-8"))


def regulations() -> list[dict[str, Any]]:
    return _load("regulations")["laws"]


def profiles() -> list[dict[str, Any]]:
    return _load("profiles")["profiles"]


def attrs() -> dict[str, str]:
    return _load("profiles")["attrs"]


def profile(key: str) -> dict[str, Any] | None:
    return next((p for p in profiles() if p["key"] == key), None)


def rules() -> list[dict[str, Any]]:
    return _load("rules")["rules"]


def controls() -> list[dict[str, Any]]:
    return _load("controls")["controls"]


def control(cid: str) -> dict[str, Any] | None:
    return next((c for c in controls() if c["id"] == cid), None)


def rubric() -> dict[str, Any]:
    return _load("rubric")


def obligation_queries() -> list[dict[str, Any]]:
    return _load("obligation_queries")["queries"]


def notes() -> dict[str, str]:
    return {n: _load(n)["note"] for n in ("regulations", "profiles", "rules", "controls", "rubric", "obligation_queries")}
