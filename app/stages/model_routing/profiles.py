"""MR5 후보 목록: 설정의 모델들(기본 · 소형 · 모델별 주소 · 대체 · Claude)을 후보로 만들고, 보정 작업이 잰 품질 · 지연 · 비용을 덧씌운다.

후보를 사람이 목록으로 고정하면 새 모델이 들어와도 쓰이지 않는다. 그래서 설정에서 자동으로 만들고(종류는 이름으로 추정 — 사람이 고칠 수 있음),
잰 값은 data/model_routing/profiles.json 에 둔다. 잰 날짜를 함께 남겨 오래된 보정을 알아보게 한다.
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def path() -> Path:
    p = get_settings().data_dir / "model_routing" / "profiles.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _kind(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("think", "reason", "r1", "qwq")):
        return "reasoning"
    if any(k in n for k in ("e2b", "0.6b", "1b", "mini", "small", "q2")):
        return "small"
    if "claude" in n or "gpt" in n:
        return "api"
    return "local"


def defaults() -> list[dict[str, Any]]:
    st = get_settings()
    names: list[tuple[str, str]] = []
    if st.openai_model:
        names.append(("openai", st.openai_model))
    names += [("openai", m) for m in (st.openai_model_urls or {}) if m != st.openai_model]
    if st.small_llm_model and st.small_llm_model not in [n for _, n in names]:
        names.append(("openai", st.small_llm_model))
    for fb in st.llm_fallbacks or []:
        if fb.get("model") and fb["model"] not in [n for _, n in names]:
            names.append((fb.get("provider") or "openai", fb["model"]))
    if st.anthropic_api_key:
        names.append(("anthropic", st.anthropic_model))
    out = []
    for prov, m in names:
        mm = ["text", "image"] if "gemma-4" in m.lower() or "vl" in m.lower() or prov == "anthropic" else ["text"]
        out.append({"name": m, "provider": prov, "model": m, "kind": _kind(m), "modalities": mm, "quality": {}, "p95_ms": None, "cost": None,
                    "reliability": 0.95, "measured_at": None})  # fmt: skip
    return out


def load() -> list[dict[str, Any]]:
    saved = {}
    if path().exists():
        try:
            saved = {c["name"]: c for c in json.loads(path().read_text(encoding="utf-8"))}
        except ValueError, KeyError:
            saved = {}
    base = defaults()
    names = {c["name"] for c in base}
    return [c | saved.get(c["name"], {}) for c in base] + [c for n, c in saved.items() if n not in names]


def save(cands: list[dict[str, Any]]) -> None:
    path().write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
