"""중복·표절 검사.

- 중복 제거: 대표와 의미 유사도 ≥ 임계값인 항목을 그룹으로 묶고(연쇄 묶임 방지) 그룹마다 대표 하나만 남긴다.
  글자 3-gram 자카드로 '완전 중복'과 '표현만 다른 같은 내용(의역)'을 구분한다.
- 표절 검사: 검사 대상 글을 문장으로 나눠 참고 문서 문장과 대조 — 복사 / 의역 / 독창.
"""

from collections import defaultdict
from typing import Any

import numpy as np

from app.stages.apps.common import AppError, Item, item_out, normalize, snippet


def char_ngrams(text: str, n: int = 3) -> set[str]:
    t = "".join(text.lower().split())
    return {t[i : i + n] for i in range(max(1, len(t) - n + 1))} if t else set()


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ── 중복 제거 ───────────────────────────────────────────────────────────────
def near_duplicates(
    items: list[Item], x: np.ndarray, threshold: float = 0.92, keep: str = "first", copy_lex: float = 0.8, block: int = 2048
) -> dict[str, Any]:
    """대표(리더) 방식 그룹화: 앞에서부터 아직 그룹이 없는 항목을 대표로 삼고, 대표와 직접 유사도 ≥ 임계값인 항목만 묶는다.
    쌍을 계속 이어 붙이는 방식(A~B, B~C → A~C)과 달리 서로 관계없는 항목이 연쇄로 엮이지 않는다."""
    if len(items) < 2:
        raise AppError("중복을 찾으려면 텍스트가 2개 이상 필요합니다.")
    x = normalize(x)
    n = len(items)
    group_of = [-1] * n
    nn_sims = np.full(n, -1.0)
    leaders: list[int] = []
    for s in range(0, n, block):  # 큰 입력도 메모리를 넘지 않게 블록 단위 유사도
        sims = x[s : s + block] @ x.T
        for r in range(sims.shape[0]):
            i = s + r
            row = sims[r].copy()
            row[i] = -1.0
            nn_sims[i] = row.max()
            if group_of[i] >= 0:
                continue
            group_of[i] = i
            leaders.append(i)
            for j in np.where(row >= threshold)[0]:
                if j > i and group_of[j] < 0:
                    group_of[j] = i

    out_groups = []
    for leader in leaders:
        members = [i for i in range(n) if group_of[i] == leader]
        if len(members) < 2:
            continue
        rep = max(members, key=lambda i: len(items[i].text)) if keep == "longest" else leader
        rep_grams = char_ngrams(items[rep].text)
        rows = []
        for i in sorted(members, key=lambda i: (i != rep, i)):
            sem = float(x[i] @ x[rep])
            lex = jaccard(char_ngrams(items[i].text), rep_grams)
            kind = None if i == rep else ("copy" if lex >= copy_lex else "paraphrase")  # 글자까지 거의 같으면 완전 중복
            rows.append(item_out(items[i], keep=i == rep, similarity=round(sem, 4), lexical=round(lex, 4), kind=kind))
        out_groups.append({"size": len(members), "representative": items[rep].key, "members": rows})
    out_groups.sort(key=lambda g: -g["size"])
    remove = sum(g["size"] - 1 for g in out_groups)
    removed = {m["key"] for g in out_groups for m in g["members"] if not m["keep"]}
    kinds: dict[str, int] = defaultdict(int)
    for g in out_groups:
        for m in g["members"]:
            if m["kind"]:
                kinds[m["kind"]] += 1
    # 임계값 정하기 참고: 각 항목의 가장 가까운 이웃 유사도 분포 (모델마다 크게 다름)
    q = np.percentile(nn_sims, [10, 50, 90]).round(4).tolist()
    edges = np.round(np.arange(0.5, 1.0001, 0.05), 2)
    hist = np.histogram(np.clip(nn_sims, 0.5, 1.0), bins=edges)[0].tolist()
    return {
        "threshold": threshold,
        "groups": out_groups,
        "n_items": n,
        "n_groups": len(out_groups),
        "n_remove": remove,
        "n_keep": n - remove,
        "kinds": dict(kinds),
        "keep_keys": [it.key for it in items if it.key not in removed],
        "nn_similarity": {
            "p10": q[0],
            "median": q[1],
            "p90": q[2],
            "hist": [{"from": float(a), "to": float(b), "n": c} for a, b, c in zip(edges[:-1], edges[1:], hist, strict=True)],
        },
        "summary": {"groups": len(out_groups), "remove": remove, "dedup_ratio": round(remove / n, 4)},
    }


# ── 표절 검사 ───────────────────────────────────────────────────────────────
def plagiarism(
    suspect_sents: list[str],
    suspect_vecs: np.ndarray,
    ref_sents: list[tuple[Item, str]],
    ref_vecs: np.ndarray,
    threshold: float = 0.85,
    copy_lex: float = 0.6,
) -> dict[str, Any]:
    """suspect_sents 각 문장에 가장 가까운 참고 문장을 찾아 판정. ref_sents = [(출처 아이템, 문장)]."""
    if not suspect_sents:
        raise AppError("검사할 글을 입력하세요.")
    if not ref_sents:
        raise AppError("참고 문서가 비어 있습니다.")
    sims = normalize(suspect_vecs) @ normalize(ref_vecs).T
    best = sims.argmax(axis=1)
    rows = []
    total = sum(len(s) for s in suspect_sents)
    flagged_chars = {"copy": 0, "paraphrase": 0}
    by_source: dict[str, dict[str, Any]] = {}
    for i, s in enumerate(suspect_sents):
        j = int(best[i])
        sem = float(sims[i, j])
        src_item, ref = ref_sents[j]
        lex = jaccard(char_ngrams(s), char_ngrams(ref))
        kind = "copy" if lex >= copy_lex else ("paraphrase" if sem >= threshold else "original")
        if kind != "original":
            flagged_chars[kind] += len(s)
            e = by_source.setdefault(src_item.key, item_out(src_item, sentences=0, chars=0))
            e["sentences"] += 1
            e["chars"] += len(s)
        rows.append(
            {
                "index": i,
                "text": s,
                "kind": kind,
                "similarity": round(sem, 4),
                "lexical": round(lex, 4),
                "source": src_item.key,
                "match": snippet(ref, 200),
            }
        )
    copy_r, para_r = flagged_chars["copy"] / max(1, total), flagged_chars["paraphrase"] / max(1, total)
    return {
        "sentences": rows,
        "ratio": {"copy": round(copy_r, 4), "paraphrase": round(para_r, 4), "total": round(copy_r + para_r, 4)},
        "sources": sorted(by_source.values(), key=lambda e: -e["chars"]),
        "n_suspect": len(suspect_sents),
        "n_reference": len(ref_sents),
        "summary": {"plagiarism_ratio": round(copy_r + para_r, 4), "copy": round(copy_r, 4), "paraphrase": round(para_r, 4)},
    }
