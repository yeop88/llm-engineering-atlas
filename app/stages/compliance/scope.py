"""RC1 적용 규제 식별: 서비스 기능의 특성 → 적용 규칙(조항 · 의무 요지 · 통제), 조항 원문은 규제 컬렉션에서.

규칙을 먼저 쓰고 검색은 보조로 두는 이유: '이 기능에 이 조항이 적용된다'는 판단은 근거를 댈 수 있어야 하고(규칙 파일 = 검토한 판단),
검색은 규칙이 놓친 조항을 '검토할 후보'로 보이는 데만 쓴다 — 비슷한 조항이 나왔다고 적용된다고 볼 수는 없다.
"""

import re
from collections.abc import Callable
from typing import Any

from app.stages.compliance import catalog
from app.stages.kg.extract import ART_HEAD, article_key, law_name

SearchFn = Callable[[str, int], list[dict[str, Any]]]


def applicable(profile: dict[str, Any]) -> list[dict[str, Any]]:
    have = set(profile.get("attrs") or [])
    return [r for r in catalog.rules() if set(r["when"]) <= have]


def rule_key(r: dict[str, Any]) -> str:
    m = re.match(r"제(\d+)조(?:의(\d+))?", r["article"])
    return article_key(r["law"], m.group(1), m.group(2)) if m else f"{r['law']} {r['article']}"


def chunk_articles(hit: dict[str, Any]) -> list[str]:
    """검색 결과 청크 → 든 조항 키들(나온 순서). 짧은 조문은 이웃과 합쳐져(merge_below) 한 청크에 조항이 여럿 든다 — 규제 자료
    청크 362개 중 40개. 첫 머리만 보면 '제28조 + 제28조의2' 청크에서 제28조의2 를 영영 못 찾아, 청크 안의 머리를 모두 본다.
    머리가 없으면(긴 조문의 뒷부분) 제목 줄(heading)을 본다."""
    law = law_name(re.sub(r"\.(txt|md)$", "", hit.get("filename") or ""))
    for text in (hit.get("text") or "", hit.get("heading") or ""):
        if keys := [article_key(law, m.group(1), m.group(2)) for m in ART_HEAD.finditer(text)]:
            return list(dict.fromkeys(keys))
    return []


def identify(profile: dict[str, Any], arts: dict[str, dict[str, Any]], search: SearchFn | None = None, k: int = 8) -> dict[str, Any]:
    """→ {items: 적용 규칙별 조항 · 원문 · 통제, controls: 필요한 통제, suggestions: 규칙에 없는 검색 후보}."""
    items = []
    for r in applicable(profile):
        key = rule_key(r)
        a = arts.get(key)
        items.append({"rule": r["id"], "law": r["law"], "article": r["article"], "key": key, "obligation": r["obligation"],
                      "controls": r["controls"], "found": a is not None, "title": a["title"] if a else "",
                      "text": a["text"][:1200] if a else "", "enforced": a["enforced"] if a else ""})  # fmt: skip
    needed = sorted({c for it in items for c in it["controls"]})
    suggestions: list[dict[str, Any]] = []
    if search is not None:
        known = {it["key"] for it in items}
        for h in search(profile["description"], k):
            for key in chunk_articles(h):
                if key not in known and all(x["key"] != key for x in suggestions):
                    a = arts.get(key) or {}
                    suggestions.append(
                        {"key": key, "title": a.get("title", ""), "score": h.get("score"), "text": (a.get("text") or "")[:300]}
                    )
    return {"profile": profile["key"], "name": profile["name"], "items": items, "controls": needed,
            "missing": [it["key"] for it in items if not it["found"]], "suggestions": suggestions}  # fmt: skip


def search_eval(search: SearchFn, k: int = 10) -> dict[str, Any]:
    """의무를 평이하게 물었을 때 근거 조항을 찾는가 → hit@1 · @3 · @5 · MRR (조항 단위, 같은 조항의 청크 여럿은 한 번)."""
    rows, mrr, hits = [], 0.0, {1: 0, 3: 0, 5: 0, k: 0}
    qs = catalog.obligation_queries()
    for q in qs:
        ranked: list[str] = []
        for h in search(q["q"], k * 3):  # 한 조항이 청크 여럿이라 넉넉히 받아 조항으로 접는다
            ranked += [key for key in chunk_articles(h) if key not in ranked]
        ranked = ranked[:k]
        rank = next((i + 1 for i, key in enumerate(ranked) if key in q["gold"]), None)
        for n in hits:
            hits[n] += bool(rank and rank <= n)
        mrr += 1 / rank if rank else 0.0
        rows.append({"id": q["id"], "q": q["q"], "gold": q["gold"], "rank": rank, "top": ranked[:3]})
    n = max(1, len(qs))
    return {"n": len(qs), "k": k, "mrr": round(mrr / n, 3), **{f"hit@{m}": round(v / n, 3) for m, v in hits.items()}, "rows": rows}
