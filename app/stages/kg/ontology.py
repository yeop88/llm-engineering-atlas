"""K2 온톨로지: 클래스 · 관계 · 규칙을 한 파일(presets/legal_ontology.json)에 두고, 추출 결과 검증 · Text2Cypher 스키마 설명 · 화면이
모두 여기서 나오게 한다(설계와 쓰는 곳이 어긋나지 않게)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PRESETS = Path(__file__).parent / "presets"
REQUIRED = {"Article": ("law", "no"), "Precedent": ("case_no",)}


@lru_cache(maxsize=4)
def load(name: str = "legal_ontology") -> dict[str, Any]:
    return json.loads((PRESETS / f"{name}.json").read_text(encoding="utf-8"))


def validate(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], onto: dict[str, Any] | None = None) -> dict[str, Any]:
    """온톨로지 규칙에 맞는 것만 남긴다 → {"nodes", "edges", "rejected": [{"what", "why"}]}. LLM 이 만든 관계 타입 · 방향이 틀린 것을 거른다."""
    onto = onto or load()
    classes, rels = onto["classes"], onto["relations"]
    ok_nodes, rejected = [], []
    keys = set()
    for n in nodes:
        if n["label"] not in classes:
            rejected.append({"what": f"{n['label']}:{n.get('key')}", "why": "온톨로지에 없는 클래스"})
            continue
        miss = [p for p in REQUIRED.get(n["label"], ()) if not (n.get("props") or {}).get(p)]
        if not n.get("key") or miss:
            rejected.append({"what": f"{n['label']}:{n.get('key')}", "why": f"필수 속성 없음({', '.join(miss) or 'key'})"})
            continue
        ok_nodes.append(n)
        keys.add((n["label"], n["key"]))
    ok_edges = []
    for e in edges:
        r = rels.get(e["type"])
        (sl, sk), (dl, dk) = e["src"], e["dst"]
        if r is None:
            rejected.append({"what": f"{e['type']}", "why": "온톨로지에 없는 관계"})
        elif (r["from"] != "*" and sl != r["from"]) or dl != r["to"]:
            rejected.append({"what": f"{sl}-{e['type']}->{dl}", "why": f"방향 · 클래스가 다름({r['from']}->{r['to']})"})
        elif (sl, sk) not in keys or (dl, dk) not in keys:
            rejected.append({"what": f"{sk}-{e['type']}->{dk}", "why": "양 끝 노드가 없음"})
        else:
            ok_edges.append(e)
    return {"nodes": ok_nodes, "edges": ok_edges, "rejected": rejected}


def schema_text(onto: dict[str, Any] | None = None) -> str:
    """Text2Cypher 프롬프트용 스키마 설명 — 레이블 · 속성 · 관계 방향."""
    onto = onto or load()
    rows = ["노드(레이블 {속성}): 모든 노드에 graph · key · name 속성이 있다."]
    for c, v in onto["classes"].items():
        rows.append(f"- (:{c}) {v['label']} — {v['desc']}. 속성: " + ", ".join(f"{k}({d})" for k, d in v["props"].items()))
    rows.append("관계:")
    for r, v in onto["relations"].items():
        rows.append(f"- (:{v['from'] if v['from'] != '*' else '아무 노드'})-[:{r}]->(:{v['to']}) {v['label']} — {v['desc']}")
    rows.append(
        "Article 의 key 는 '근로기준법 제23조' · '근로기준법 시행령 제2조' · '주택임대차보호법 제8조의2' 처럼 법령 이름 + 조문 번호다."
    )
    return "\n".join(rows)
