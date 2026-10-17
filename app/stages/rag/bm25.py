"""BM25 (Okapi). 문서 쪽 가중치를 미리 계산한 희소 행렬로 저장해 질의 시 행렬 곱 한 번으로 점수를 낸다.

score(q, d) = Σ_t∈q idf(t) · tf(t,d)·(k1+1) / (tf(t,d) + k1·(1 − b + b·|d|/avgdl))
"""

import math
import threading
from collections import Counter

import numpy as np
from scipy.sparse import csr_matrix


class BM25Index:
    def __init__(self, ids: list[int], docs_tokens: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.ids = np.asarray(ids, dtype=np.int64)
        self.vocab: dict[str, int] = {}
        rows, cols, vals = [], [], []
        lengths = np.array([len(t) for t in docs_tokens], dtype=np.float64)
        avgdl = float(lengths.mean()) if len(lengths) and lengths.mean() > 0 else 1.0
        df: Counter[int] = Counter()
        for r, tokens in enumerate(docs_tokens):
            tf = Counter(self.vocab.setdefault(t, len(self.vocab)) for t in tokens)
            norm = k1 * (1 - b + b * lengths[r] / avgdl)
            for c, f in tf.items():
                rows.append(r)
                cols.append(c)
                vals.append(f * (k1 + 1) / (f + norm))
                df[c] += 1
        n = len(docs_tokens)
        self.idf = np.zeros(len(self.vocab), dtype=np.float64)
        for c, d in df.items():
            self.idf[c] = math.log(1 + (n - d + 0.5) / (d + 0.5))
        self.matrix = csr_matrix((vals, (rows, cols)), shape=(n, len(self.vocab)), dtype=np.float64)
        self._pos = {int(cid): i for i, cid in enumerate(self.ids)}

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query_tokens: list[str], top_k: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        q = Counter(self.vocab[t] for t in query_tokens if t in self.vocab)
        if not q or not len(self.ids):
            return []
        weights = np.zeros(len(self.vocab))
        for c, f in q.items():
            weights[c] = self.idf[c] * f
        scores = self.matrix @ weights
        if allowed is not None:
            mask = np.zeros(len(self.ids), dtype=bool)
            for cid in allowed:
                if (p := self._pos.get(cid)) is not None:
                    mask[p] = True
            scores = np.where(mask, scores, 0.0)
        k = min(top_k, int((scores > 0).sum()))
        if k <= 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(self.ids[i]), float(scores[i])) for i in top]


class BM25Cache:
    """청크 세트별 BM25 인덱스를 메모리에 캐시. 청크가 바뀌면(개수·최대 id) 다시 만든다."""

    def __init__(self) -> None:
        self._items: dict[int, tuple[tuple[int, int], BM25Index]] = {}
        self._lock = threading.Lock()

    def get(self, chunk_set_id: int, version: tuple[int, int], loader) -> BM25Index:
        with self._lock:
            hit = self._items.get(chunk_set_id)
            if hit and hit[0] == version:
                return hit[1]
        ids, tokens = loader()
        index = BM25Index(ids, tokens)
        with self._lock:
            self._items[chunk_set_id] = (version, index)
        return index

    def invalidate(self, chunk_set_id: int | None = None) -> None:
        with self._lock:
            if chunk_set_id is None:
                self._items.clear()
            else:
                self._items.pop(chunk_set_id, None)


bm25_cache = BM25Cache()
