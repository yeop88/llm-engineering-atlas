"""평가 지표의 불확실성: 부트스트랩 신뢰구간과 짝지은(paired) 부트스트랩 비교.

평가 질문이 수십 개뿐이면 nDCG 0.71 과 0.68 의 차이는 우연일 수 있다. 질문(또는 문장쌍)을 복원 추출로
다시 뽑아 지표를 여러 번 계산하고, 그 분포로 구간과 '이 차이가 우연일 확률'을 구한다.
"""

from collections.abc import Callable
from typing import Any

import numpy as np

N_BOOT = 1000
LEVEL = 0.95


def _indices(n: int, n_boot: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(n_boot, n))


def mean_ci(values: list[float] | np.ndarray, n_boot: int = N_BOOT, level: float = LEVEL, seed: int = 0) -> list[float]:
    """질문별 값의 평균에 대한 백분위 부트스트랩 구간."""
    v = np.asarray(values, dtype=np.float64)
    if len(v) < 2:
        return [float(v.mean()) if len(v) else 0.0] * 2
    means = v[_indices(len(v), n_boot, seed)].mean(axis=1)
    a = (1 - level) / 2
    return [round(float(np.quantile(means, a)), 4), round(float(np.quantile(means, 1 - a)), 4)]


def stat_ci(n: int, stat: Callable[[np.ndarray], float], n_boot: int = N_BOOT, level: float = LEVEL, seed: int = 0) -> list[float]:
    """평균이 아닌 통계량(스피어만 상관 등)의 구간. stat(인덱스 배열) → 값."""
    if n < 3:
        v = stat(np.arange(n)) if n else 0.0
        return [round(v, 4)] * 2
    vals = np.array([stat(ix) for ix in _indices(n, n_boot, seed)])
    vals = vals[np.isfinite(vals)]
    a = (1 - level) / 2
    return [round(float(np.quantile(vals, a)), 4), round(float(np.quantile(vals, 1 - a)), 4)]


def _paired(diffs: np.ndarray, observed: float, level: float) -> dict[str, Any]:
    a = (1 - level) / 2
    lo, hi = float(np.quantile(diffs, a)), float(np.quantile(diffs, 1 - a))
    # 양측 p: 부트스트랩 차이가 0 을 넘어 반대쪽으로 갈 비율의 두 배
    p = 2 * min(float((diffs <= 0).mean()), float((diffs >= 0).mean()))
    return {
        "diff": round(observed, 4),
        "ci": [round(lo, 4), round(hi, 4)],
        "p": round(min(1.0, p), 4),
        "significant": bool(lo > 0 or hi < 0),
    }


def paired_mean(
    a: list[float] | np.ndarray, b: list[float] | np.ndarray, n_boot: int = N_BOOT, level: float = LEVEL, seed: int = 0
) -> dict[str, Any]:
    """같은 질문들에 대한 두 시스템의 질문별 값 (a - b). 질문 난이도 차이가 상쇄되어 독립 비교보다 예민하다."""
    d = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    if len(d) < 2:
        return {"diff": round(float(d.mean()) if len(d) else 0.0, 4), "ci": [0.0, 0.0], "p": 1.0, "significant": False}
    return _paired(d[_indices(len(d), n_boot, seed)].mean(axis=1), float(d.mean()), level)


def paired_stat(
    n: int,
    stat_a: Callable[[np.ndarray], float],
    stat_b: Callable[[np.ndarray], float],
    n_boot: int = N_BOOT,
    level: float = LEVEL,
    seed: int = 0,
) -> dict[str, Any]:
    full = np.arange(n)
    observed = stat_a(full) - stat_b(full)
    if n < 3:
        return {"diff": round(observed, 4), "ci": [0.0, 0.0], "p": 1.0, "significant": False}
    diffs = np.array([stat_a(ix) - stat_b(ix) for ix in _indices(n, n_boot, seed)])
    return _paired(diffs[np.isfinite(diffs)], observed, level)
