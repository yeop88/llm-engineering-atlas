"""K4 지식 융합 · 정제: 같은 개체를 하나로 묶는다.

- 조문 · 법령 이름: 추출(K3)에서 정규화한다(띄어쓰기 · 가운뎃점 · '구' 법 · 조문 번호 표기) — 규칙으로 확정할 수 있는 것은 규칙으로.
- 쟁점: LLM 이 판례마다 뽑은 이름은 같은 쟁점도 다르게 적는다('취업규칙 불이익 변경' · '취업규칙의 불리한 변경'). 띄어쓰기 · 조사를
  뺀 글자가 같으면 바로 합치고, 그 밖에는 임베딩 유사도가 기준 이상인 것끼리 합친다(합친 기록을 남겨 사람이 확인).
  기준을 낮추면 다른 쟁점이 하나로 뭉쳐 '같은 쟁점 판례' 확장이 엉뚱한 판례를 끌고 온다 — 그래서 보수적으로(0.88).
"""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import numpy as np

MERGE_SIM = 0.88
# 서로 반대인 당사자 · 역할 — 임베딩은 '임차인 지위 승계'와 '임대인 지위 승계'를 아주 가깝게 보지만(같은 낱말이 대부분) 다른 쟁점이다.
# 첫 구축에서 실제로 둘이 하나로 합쳐졌다. 한쪽에만 있는 반대말이 있으면 유사도와 상관없이 합치지 않는다.
OPPOSITES = [("임차인", "임대인"), ("근로자", "사용자"), ("원고", "피고"), ("채권자", "채무자"), ("매수인", "매도인"),
             ("양수인", "양도인"), ("수급인", "도급인"), ("상고인", "피상고인")]  # fmt: skip


def conflict(a: str, b: str) -> bool:
    """두 이름이 서로 반대인 역할을 가리키나 — 한쪽에만 있는 반대말 쌍."""
    for x, y in OPPOSITES:
        if (x in a and y in b and not (y in a or x in b)) or (y in a and x in b and not (x in a or y in b)):
            return True
    return False


def _norm(s: str) -> str:
    """낱말 끝의 조사와 띄어쓰기만 뺀다('취업규칙의 불이익 변경' = '취업규칙 불이익변경'). 낱말 안의 글자는 그대로 — '가산임금'의 '가'를 지우면 안 된다."""
    return re.sub(r"\s+", "", re.sub(r"(의|에서|에|은|는|이|가|을|를|과|와)(?=\s|$)", "", s))


def merge_issues(per_case: dict[str, list[str]], embed: Callable[[list[str]], np.ndarray] | None = None,
                 sim: float = MERGE_SIM) -> dict[str, Any]:  # fmt: skip
    """판례 → 쟁점 이름들 → {"nodes", "edges", "merges"}. 대표 이름은 묶음에서 가장 많이 나온(같으면 짧은) 이름."""
    counts = Counter(i for v in per_case.values() for i in v)
    names = list(counts)
    parent = list(range(len(names)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_norm: dict[str, int] = {}
    for i, n in enumerate(names):
        k = _norm(n)
        if k in by_norm:
            union(by_norm[k], i)
        else:
            by_norm[k] = i
    if embed is not None and len(names) > 1:
        v = embed(names)
        s = v @ v.T
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if s[i, j] >= sim and not conflict(names[i], names[j]):
                    union(i, j)
    groups: dict[int, list[str]] = {}
    for i, n in enumerate(names):
        groups.setdefault(find(i), []).append(n)
    # 이음(A~B, B~C)으로 반대 역할이 한 묶음에 들어올 수 있어, 대표와 반대인 이름은 떼어 따로 묶음을 만든다
    split: dict[int, list[str]] = {}
    for gid, members in list(groups.items()):
        rep = sorted(members, key=lambda x: (-counts[x], len(x)))[0]
        keep = [m for m in members if not conflict(rep, m)]
        out = [m for m in members if conflict(rep, m)]
        groups[gid] = keep
        if out:
            split[-(gid + 1)] = out
    groups |= split
    canon = {}
    merges = []
    for members in groups.values():
        rep = sorted(members, key=lambda x: (-counts[x], len(x)))[0]
        for m in members:
            canon[m] = rep
        if len(members) > 1:
            merges.append({"canonical": rep, "aliases": sorted(m for m in members if m != rep)})
    nodes = [{"label": "Issue", "key": rep, "name": rep, "props": {"aliases": sorted(m for m in members if m != rep), "cases": 0}}
             for members in groups.values() for rep in [canon[members[0]]]]  # fmt: skip
    edges, per_issue = [], Counter()
    for case, issues in per_case.items():
        for i in dict.fromkeys(canon[x] for x in issues):
            edges.append({"src": ("Precedent", case), "dst": ("Issue", i), "type": "CONCERNS"})
            per_issue[i] += 1
    for n in nodes:
        n["props"]["cases"] = per_issue[n["key"]]
    return {
        "nodes": nodes,
        "edges": edges,
        "merges": sorted(merges, key=lambda m: -len(m["aliases"])),
        "n_raw": len(names),
        "n_issues": len(nodes),
    }
