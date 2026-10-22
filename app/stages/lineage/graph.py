"""LN1 · LN2 계보 그래프: 모델 노드 · 계열 · 제작사 · 구조 · 모달리티 · 라이선스 노드와 관계(BELONGS_TO · SUCCEEDS · DERIVED_FROM ·
QUANTIZED_FROM · HAS_ARCHITECTURE · SUPPORTS_MODALITY · LICENSED_UNDER). 노드 종류는 생태계 공통 온톨로지(Model · Capability …)와 같은 이름.

세대(SUCCEEDS)는 같은 계열 안에서 세대 번호 순으로 잇는다. 같은 기반 모델을 가리키는 GGUF 들은 QUANTIZED_FROM 으로 기반에 묶어
'같은 모델의 다른 비트' 를 한눈에 보게 한다 — 양자화 비교(7b · IF3)의 후보가 된다.
"""

from typing import Any


def _gen(v: str | None) -> float:
    try:
        return float(v) if v else -1.0
    except ValueError:
        return -1.0


def build(models: dict[str, dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def node(nid: str, kind: str, label: str, **kw: Any) -> str:
        nodes.setdefault(nid, {"id": nid, "type": kind, "label": label} | kw)
        return nid

    for k, m in models.items():
        mid = node(k, "Model", m["name"], params_b=m.get("params_b"), file=m.get("file"))
        fam = node(f"family:{m['family']}", "Family", m["family"])
        edges.append({"a": mid, "rel": "BELONGS_TO", "b": fam})
        if m.get("org"):
            edges.append({"a": fam, "rel": "MADE_BY", "b": node(f"org:{m['org']}", "Provider", m["org"])})
        if m.get("arch"):
            moe = " · MoE" if m.get("experts") else ""
            edges.append({"a": mid, "rel": "HAS_ARCHITECTURE", "b": node(f"arch:{m['arch']}{moe}", "Architecture", f"{m['arch']}{moe}")})
        for mo in m.get("modalities") or []:
            edges.append({"a": mid, "rel": "SUPPORTS_MODALITY", "b": node(f"mod:{mo}", "Capability", mo)})
        lic = m.get("license") or {}
        if lic.get("id") or lic.get("name"):
            lid = lic.get("name") or lic["id"]
            edges.append({"a": mid, "rel": "LICENSED_UNDER", "b": node(f"license:{lid}", "License", lid, check=lic.get("check"))})
        for b in m.get("base_models") or []:
            if not b.get("name") and not b.get("repo"):
                continue
            repo = (b.get("repo") or "").rstrip("/").split("huggingface.co/")[-1] or b["name"]
            bid = node(f"hf:{repo}", "Model", repo, base=True)
            edges.append({"a": mid, "rel": "QUANTIZED_FROM" if m["source"] == "gguf" else "DERIVED_FROM", "b": bid})
            edges.append({"a": bid, "rel": "BELONGS_TO", "b": fam})
    # 세대: 같은 계열의 세대 번호가 다른 모델을 번호 순으로 잇는다(같은 세대끼리는 잇지 않음)
    by_fam: dict[str, list[tuple[float, str]]] = {}
    for k, m in models.items():
        if _gen(m.get("generation")) >= 0:
            by_fam.setdefault(m["family"], []).append((_gen(m["generation"]), k))
    for lst in by_fam.values():
        gens = sorted({g for g, _ in lst})
        for g1, g2 in zip(gens, gens[1:], strict=False):
            for _, a in [x for x in lst if x[0] == g2]:
                for _, b in [x for x in lst if x[0] == g1][:1]:
                    edges.append({"a": a, "rel": "SUCCEEDS", "b": b})
    return {"nodes": list(nodes.values()), "edges": edges}


FIELDS = ("params_b", "experts", "layers", "hidden", "kv_heads", "modalities", "arch")


def compare(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """두 모델(대개 세대)의 바뀐 점 — 구조 숫자 · 맥락 · 모달리티 · 라이선스."""
    out = [{"field": f, "a": a.get(f), "b": b.get(f)} for f in FIELDS if a.get(f) != b.get(f)]
    for f in ("trained", "sliding_window"):
        if (a.get("context") or {}).get(f) != (b.get("context") or {}).get(f):
            out.append({"field": f"context.{f}", "a": (a.get("context") or {}).get(f), "b": (b.get("context") or {}).get(f)})
    la, lb = (a.get("license") or {}).get("id"), (b.get("license") or {}).get("id")
    if la != lb:
        out.append({"field": "license", "a": la, "b": lb})
    return out
