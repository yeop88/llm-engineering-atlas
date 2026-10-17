"""클러스터링: K-means · 계층(평균 연결, 코사인) · HDBSCAN, 군집 수 자동 추천(실루엣), 군집별 키워드(c-TF-IDF)·대표 문장."""

import math
from collections import Counter
from typing import Any

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from app.apps.common import AppError, Item, item_out, normalize
from app.rag.korean import nouns_many
from app.services.projection import pca_2d

METHODS = {"kmeans": "K-means", "agglomerative": "계층 (평균 연결)", "hdbscan": "HDBSCAN (밀도 기반, 노이즈 분리)"}


def _fit(x: np.ndarray, method: str, k: int | None, min_cluster_size: int) -> np.ndarray:
    if method == "kmeans":
        return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(x)
    if method == "agglomerative":
        return AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(x)
    if method == "hdbscan":
        return HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean", copy=True).fit_predict(x)  # 정규화 벡터: 유클리드 ∝ 코사인
    raise AppError(f"알 수 없는 군집 방법: {method}")


def _silhouette(x: np.ndarray, labels: np.ndarray) -> float | None:
    mask = labels >= 0
    if len(set(labels[mask])) < 2 or mask.sum() < 3:
        return None
    return float(silhouette_score(x[mask], labels[mask], metric="cosine"))


def choose_k(x: np.ndarray, method: str, k_max: int) -> tuple[int, list[dict[str, float]]]:
    """2..k_max 중 실루엣 점수가 가장 높은 k."""
    upper = max(2, min(k_max, len(x) - 1))
    scores = []
    for k in range(2, upper + 1):
        s = _silhouette(x, _fit(x, method, k, 5))
        scores.append({"k": k, "silhouette": round(s, 4) if s is not None else None})
    best = max((s for s in scores if s["silhouette"] is not None), key=lambda s: s["silhouette"], default={"k": 2})
    return int(best["k"]), scores


def ctfidf_keywords(token_lists: list[list[str]], labels: np.ndarray, top: int = 6) -> dict[int, list[str]]:
    """군집을 하나의 문서로 보고 TF-IDF (BERTopic 의 c-TF-IDF): 그 군집에 유독 많이 나오는 단어."""
    clusters = sorted(c for c in set(labels.tolist()) if c >= 0)
    tf: dict[int, Counter[str]] = {c: Counter() for c in clusters}
    for toks, c in zip(token_lists, labels, strict=True):
        if c >= 0:
            tf[c].update(toks)
    total = Counter()
    for c in clusters:
        total.update(tf[c])
    avg = sum(sum(t.values()) for t in tf.values()) / max(1, len(clusters))
    out = {}
    for c in clusters:
        n = sum(tf[c].values()) or 1
        scores = {w: (f / n) * math.log(1 + avg / total[w]) for w, f in tf[c].items()}
        out[c] = [w for w, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:top]]
    return out


def cluster(
    items: list[Item], x: np.ndarray, method: str = "kmeans", k: int | None = None, k_max: int = 10, min_cluster_size: int = 5
) -> dict[str, Any]:
    if len(items) < 4:
        raise AppError("군집화하려면 텍스트가 4개 이상 필요합니다.")
    x = normalize(x)
    k_scores = None
    if method != "hdbscan" and not k:
        k, k_scores = choose_k(x, method, k_max)
    if method != "hdbscan" and k >= len(items):
        raise AppError(f"군집 수({k})는 텍스트 수({len(items)})보다 작아야 합니다.")
    labels = _fit(x, method, k, min_cluster_size)
    sil = _silhouette(x, labels)
    keywords = ctfidf_keywords(nouns_many([it.text for it in items]), labels)
    coords, explained = pca_2d(x)

    clusters = []
    for c in sorted(set(labels.tolist()), key=lambda c: (c < 0, -int((labels == c).sum()))):
        idx = np.where(labels == c)[0]
        centroid = normalize(x[idx].mean(axis=0))
        sims = x[idx] @ centroid
        order = idx[np.argsort(-sims)]
        gold = Counter(items[i].label for i in idx if items[i].label)
        clusters.append(
            {
                "id": int(c),
                "noise": c < 0,
                "size": len(idx),
                "keywords": keywords.get(c, []),
                "cohesion": round(float(sims.mean()), 4),  # 군집 안 평균 중심 유사도
                "representatives": [item_out(items[i], similarity=round(float(x[i] @ centroid), 4)) for i in order[:3]],
                "members": [items[i].key for i in order],
                "gold_labels": dict(gold.most_common(3)),
            }
        )
    out: dict[str, Any] = {
        "method": method,
        "k": len([c for c in clusters if not c["noise"]]),
        "noise": int((labels < 0).sum()),
        "silhouette": round(sil, 4) if sil is not None else None,
        "k_scores": k_scores,
        "clusters": clusters,
        "points": [
            {
                "key": it.key,
                "x": round(float(p[0]), 4),
                "y": round(float(p[1]), 4),
                "cluster": int(lab),
                "label": it.label,
                "text": it.text[:120],
            }
            for it, p, lab in zip(items, coords, labels, strict=True)
        ],
        "explained_variance": round(explained, 4),
    }
    if out["k"] == 0:
        out["warning"] = "모든 텍스트가 노이즈로 판정되었습니다. 최소 군집 크기를 줄이거나 K-means 를 쓰세요."
    elif out["noise"] > len(items) / 2:
        out["warning"] = (
            f"절반 이상({out['noise']}개)이 노이즈입니다. 짧고 다양한 텍스트에서는 HDBSCAN 이 보수적으로 동작합니다. 최소 군집 크기를 줄여 보세요."
        )
    gold = [it.label for it in items]
    if all(gold) and out["k"] > 0:  # 정답 라벨이 있으면 일치도 (노이즈 제외)
        mask = labels >= 0
        purity = sum(max(Counter(gold[i] for i in np.where(labels == c)[0]).values()) for c in set(labels[mask].tolist())) / max(
            1, mask.sum()
        )
        out["agreement"] = {
            "ari": round(float(adjusted_rand_score(np.array(gold)[mask], labels[mask])), 4),
            "purity": round(float(purity), 4),
            "n_labels": len(set(gold)),
        }
    return out
