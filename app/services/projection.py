"""임베딩 2D 투영(PCA / t-SNE)과 의미 쌍 정렬도 계산."""

from typing import Any

import numpy as np


def _scale(points: np.ndarray) -> np.ndarray:
    """보기 좋게 [-1, 1] 범위로 맞춘다 (축 값 자체에는 의미가 없음)."""
    points = points - points.mean(axis=0)
    span = np.abs(points).max()
    return points / span if span > 0 else points


def pca_2d(emb: np.ndarray) -> tuple[np.ndarray, float]:
    """반환: (n, 2) 좌표, 두 성분이 설명하는 분산 비율."""
    centered = emb - emb.mean(axis=0)
    _, s, vt = np.linalg.svd(centered, full_matrices=False)
    coords = centered @ vt[:2].T
    var = s**2
    explained = float(var[:2].sum() / var.sum()) if var.sum() > 0 else 0.0
    # 부호는 임의이므로 첫 성분이 가장 큰 점이 오른쪽에 오도록 맞춰 모델 간 비교를 쉽게 한다
    for k in range(coords.shape[1]):
        if coords[np.abs(coords[:, k]).argmax(), k] < 0:
            coords[:, k] *= -1
    if coords.shape[1] < 2:
        coords = np.hstack([coords, np.zeros((len(coords), 1))])
    return _scale(coords), explained


def tsne_2d(emb: np.ndarray) -> np.ndarray:
    from sklearn.manifold import TSNE

    n = len(emb)
    perplexity = float(max(2.0, min(30.0, (n - 1) / 3)))
    coords = TSNE(n_components=2, perplexity=perplexity, init="pca", metric="cosine", random_state=0).fit_transform(emb)
    return _scale(coords)


def pair_alignment(emb: np.ndarray, groups: list[str]) -> dict[str, Any] | None:
    """그룹이 정확히 2개이고 개수가 같으면 i번째끼리 의미가 같은 쌍으로 보고 정렬도를 잰다 (원래 차원 기준)."""
    names = list(dict.fromkeys(groups))
    if len(names) != 2:
        return None
    a_idx = [i for i, g in enumerate(groups) if g == names[0]]
    b_idx = [i for i, g in enumerate(groups) if g == names[1]]
    if len(a_idx) != len(b_idx) or len(a_idx) < 2:
        return None
    a, b = emb[a_idx], emb[b_idx]
    sim = a @ b.T
    n = len(a_idx)
    pair = float(np.diag(sim).mean())
    off = float((sim.sum() - np.trace(sim)) / (n * n - n))
    a2b = float((sim.argmax(axis=1) == np.arange(n)).mean())
    b2a = float((sim.argmax(axis=0) == np.arange(n)).mean())
    return {
        "groups": names,
        "n_pairs": n,
        "pair_cosine": round(pair, 4),
        "other_cosine": round(off, 4),
        "margin": round(pair - off, 4),
        "top1_a_to_b": round(a2b, 4),
        "top1_b_to_a": round(b2a, 4),
        "pairs": [[a_idx[i], b_idx[i]] for i in range(n)],
    }
