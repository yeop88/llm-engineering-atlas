"""키워드 추출 (형태소 명사구 후보 + 임베딩 유사도 + MMR) 과 추출 요약 (문장 임베딩 그래프 중심성)."""

from collections import Counter
from typing import Any

import numpy as np

from app.apps.common import AppError, normalize

MAX_CANDIDATES = 300  # 문서마다 빈도 상위 후보만 임베딩


def candidates(phrases: list[str], min_freq: int = 1) -> list[tuple[str, int]]:
    cnt = Counter(phrases)
    return [(p, n) for p, n in cnt.most_common(MAX_CANDIDATES) if n >= min_freq]


def mmr(query: np.ndarray, cand: np.ndarray, top_n: int, diversity: float, texts: list[str] | None = None) -> list[int]:
    """관련도(query 와의 유사도)와 이미 고른 것과의 중복을 함께 본다. diversity 0 = 관련도만.
    texts 를 주면 이미 고른 키워드를 포함하거나 그에 포함되는 후보("연차" ⊂ "유급 연차휴가")는 건너뛴다."""
    rel = cand @ query
    chosen: list[int] = []
    rest = list(range(len(cand)))
    while rest and len(chosen) < top_n:
        if texts and chosen:
            rest = [i for i in rest if not any(texts[i] in texts[c] or texts[c] in texts[i] for c in chosen)]
            if not rest:
                break
        if chosen:
            red = (cand[rest] @ cand[chosen].T).max(axis=1)
            score = (1 - diversity) * rel[rest] - diversity * red
        else:
            score = rel[rest]
        best = rest[int(np.argmax(score))]
        chosen.append(best)
        rest.remove(best)
    return chosen


def keywords(
    doc_vec: np.ndarray, cands: list[tuple[str, int]], cand_vecs: np.ndarray, top_n: int = 8, diversity: float = 0.3
) -> list[dict[str, Any]]:
    if not cands:
        return []
    doc_vec = normalize(doc_vec[None, :])[0]
    cand_vecs = normalize(cand_vecs)
    idx = mmr(doc_vec, cand_vecs, top_n, diversity, [c[0] for c in cands])
    return [{"keyword": cands[i][0], "score": round(float(cand_vecs[i] @ doc_vec), 4), "freq": cands[i][1]} for i in idx]


def pagerank(sim: np.ndarray, damping: float = 0.85, iters: int = 100) -> np.ndarray:
    """문장 유사도 그래프의 중심성 (LexRank/TextRank 의 임베딩판).
    모델마다 기본 유사도 수준이 달라(관계없는 문장도 0.8 인 모델) 문장쌍 유사도의 중앙값을 빼고 그보다 닮은 정도만 간선 가중치로 쓴다."""
    n = len(sim)
    off = sim[~np.eye(n, dtype=bool)]
    w = np.clip(sim - (np.median(off) if off.size else 0.0), 0, None)
    np.fill_diagonal(w, 0)
    rows = w.sum(axis=1, keepdims=True)
    p = np.divide(w, rows, out=np.full_like(w, 1.0 / n), where=rows > 0)
    r = np.full(n, 1.0 / n)
    for _ in range(iters):
        nxt = (1 - damping) / n + damping * (p.T @ r)
        if np.abs(nxt - r).sum() < 1e-9:
            break
        r = nxt
    return r


def summarize(sentences: list[str], vecs: np.ndarray, n: int = 3, diversity: float = 0.3, lead_bonus: float = 0.0) -> dict[str, Any]:
    if len(sentences) < 2:
        raise AppError("요약하려면 문장이 2개 이상 필요합니다.")
    vecs = normalize(vecs)
    sim = vecs @ vecs.T
    rank = pagerank(sim)
    rank = (rank - rank.min()) / max(float(rank.max() - rank.min()), 1e-12)  # 0~1
    if lead_bonus:  # 기사처럼 앞 문장이 중요한 글
        rank = rank + lead_bonus * (1 - np.arange(len(rank)) / len(rank))
    centroid = normalize(vecs.mean(axis=0, keepdims=True))[0]
    # MMR: 중심성이 높은 문장부터, 이미 고른 문장과 겹치는 것은 피한다
    chosen: list[int] = []
    rest = list(range(len(sentences)))
    n = min(n, len(sentences))
    while len(chosen) < n:
        if chosen:
            red = sim[np.ix_(rest, chosen)].max(axis=1)
            score = (1 - diversity) * rank[rest] - diversity * red
        else:
            score = rank[rest]
        best = rest[int(np.argmax(score))]
        chosen.append(best)
        rest.remove(best)
    order = sorted(chosen)
    summary_vec = normalize(vecs[order].mean(axis=0, keepdims=True))[0]
    return {
        "picked": [sentences[i] for i in order],
        "selected": order,
        "sentences": [
            {"index": i, "text": s, "centrality": round(float(rank[i]), 4), "selected": i in chosen} for i, s in enumerate(sentences)
        ],
        "coverage": round(float(summary_vec @ centroid), 4),  # 요약이 전체 글의 의미를 얼마나 대표하는지
        "compression": round(sum(len(sentences[i]) for i in order) / max(1, sum(len(s) for s in sentences)), 4),
    }
