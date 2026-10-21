"""IP1 임베딩 공간 분석: 같은 점수의 모델도 공간 모양이 다르다 — 양자화 · 차원 줄이기에서 다르게 무너지는 이유를 공간에서 찾는다.

지표(모델마다 같은 글로):
- 이방성: 아무 두 글의 평균 코사인 — 높으면 벡터가 한쪽으로 몰려 있어 점수 차이가 작다(구분력 ↓)
- 유효 차원: 특이값 분포의 참여 비율(Σσ²)² / Σσ⁴ — 몇 차원을 실제로 쓰나(낮으면 차원 줄이기에 강함)
- 상위 차원 설명력: 주성분 상위 10 · 50 개가 분산의 몇 %
- 문서 군집: 같은 문서 청크끼리의 평균 코사인 − 다른 문서끼리 — 문서 구분이 공간에 드러나는가
- 언어 간 정렬: 한국어 문장의 가장 가까운 영어 문장이 그 번역인 비율 · 번역 쌍 코사인 vs 아무 쌍
"""

import random
from typing import Any

import numpy as np

PAIRS = [
    ("세탁기에서 E4 오류가 표시되면 배수 필터를 청소하세요.", "If the washer shows error E4, clean the drain filter."),
    ("건조기 필터는 사용할 때마다 비워야 합니다.", "The dryer filter should be emptied after every use."),
    ("전원 플러그를 뽑은 뒤 기사 방문을 신청하세요.", "Unplug the power cord and request a technician visit."),
    ("근로계약 기간은 1년을 넘을 수 없습니다.", "An employment contract period may not exceed one year."),
    ("임대인은 보증금을 돌려주어야 합니다.", "The landlord must return the deposit."),
    ("개인정보는 목적을 달성하면 파기해야 합니다.", "Personal data must be destroyed once its purpose is achieved."),
    ("문이 잠겨 열리지 않으면 5분 기다리세요.", "If the door is locked, wait five minutes."),
    ("세제는 표시선 아래까지만 넣으세요.", "Add detergent only up to the marked line."),
    ("공문서는 한글로 작성하여야 합니다.", "Official documents must be written in Hangul."),
    ("소음이 크면 다리 높이를 맞추세요.", "If the noise is loud, level the feet."),
    ("물이 새면 즉시 급수 밸브를 잠그세요.", "If water leaks, close the water valve immediately."),
    ("만족도 조사에 응답해 주셔서 감사합니다.", "Thank you for answering the satisfaction survey."),
]  # fmt: skip


def _norm(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-12)


def metrics(vecs: np.ndarray, doc_ids: list[int] | None = None, seed: int = 7) -> dict[str, Any]:
    v = _norm(vecs.astype(np.float32))
    n = len(v)
    rnd = random.Random(seed)
    pairs = [(rnd.randrange(n), rnd.randrange(n)) for _ in range(min(5000, n * 10))]
    pairs = [(a, b) for a, b in pairs if a != b]
    aniso = float(np.mean([v[a] @ v[b] for a, b in pairs])) if pairs else None
    c = v - v.mean(0)
    s = np.linalg.svd(c, compute_uv=False)
    var = s**2
    pr = float(var.sum() ** 2 / (var**2).sum()) if var.sum() else None
    out: dict[str, Any] = {"n": n, "dim": v.shape[1], "anisotropy": round(aniso, 4) if aniso is not None else None, "effective_dim": round(pr, 1) if pr else None,
                           "pca_top10": round(float(var[:10].sum() / var.sum()), 4), "pca_top50": round(float(var[:50].sum() / var.sum()), 4)}  # fmt: skip
    if doc_ids:
        same, diff = [], []
        for a, b in pairs:
            (same if doc_ids[a] == doc_ids[b] else diff).append(float(v[a] @ v[b]))
        if same and diff:
            out["doc_separation"] = round(float(np.mean(same) - np.mean(diff)), 4)
    return out


def alignment(ko: np.ndarray, en: np.ndarray) -> dict[str, Any]:
    k, e = _norm(ko), _norm(en)
    sim = k @ e.T
    top1 = float(np.mean(np.argmax(sim, axis=1) == np.arange(len(k))))
    pair = float(np.mean(np.diag(sim)))
    off = float((sim.sum() - np.trace(sim)) / (sim.size - len(k)))
    return {"retrieval@1": round(top1, 4), "pair_cos": round(pair, 4), "random_cos": round(off, 4), "gap": round(pair - off, 4)}
