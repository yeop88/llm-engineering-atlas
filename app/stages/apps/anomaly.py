"""이상·신종 탐지: 정상(과 이미 아는 이상 유형) 예시로 '경계'를 배우고, 그 밖에 있는 텍스트를 찾는다.

- 그룹마다(정상, 알려진 유형 각각) 이상 점수 모델을 학습하고, 교차 적합(out-of-fold) 점수의 분위수로 임계값을 정한다.
- 알려진 이상 유형이 있으면 '정상 대 이상' 분류기도 학습한다. 돈·긴급·링크 같은 이상 유형의 공통 특징을 배워
  학습에 없던 유형도 이상으로 잡는다 (정상 데이터가 다양하면 거리 경계만으로는 느슨하다).
- 판정: 정상 경계 밖이거나 분류기가 이상이라고 하면 이상 → 알려진 유형의 경계 안이면 그 유형, 아니면 '신종'.
"""

from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import KFold
from sklearn.neighbors import LocalOutlierFactor

from app.stages.apps.common import AppError, Item, item_out, normalize

METHODS = {"knn": "kNN 거리", "lof": "LOF (국소 밀도)", "iforest": "Isolation Forest", "centroid": "중심점 거리"}
NOVEL = "신종"
MIN_GROUP = 3  # 그룹(라벨)마다 필요한 최소 예시 수
MIN_NORMAL = 5
STABLE_NORMAL = 50  # 이보다 적으면 경계(분위수) 추정이 흔들린다


def conformal_threshold(oof: np.ndarray, quantile: float) -> float:
    """정상 새 텍스트가 경계 밖으로 나갈 확률이 1 - quantile 이하가 되도록 하는 분위수 (분할 컨포멀 방식).
    예시가 적으면 보간하지 않고 더 높은 순위 값을 쓴다 (n=25, 95% → 최댓값)."""
    n = len(oof)
    rank = min(n, int(np.ceil((n + 1) * quantile)))
    return float(np.sort(oof)[rank - 1])


# ── 그룹 하나의 이상 점수 모델 (높을수록 이상) ─────────────────────────────
class GroupScorer:
    def __init__(self, method: str, k: int = 5):
        if method not in METHODS:
            raise AppError(f"알 수 없는 탐지 방법: {method}")
        self.method, self.k = method, k
        self.state: dict[str, Any] = {}

    def fit(self, x: np.ndarray) -> GroupScorer:
        n = len(x)
        if self.method == "knn":
            self.state["x"] = x.astype(np.float32)
        elif self.method == "centroid":
            self.state["c"] = normalize(x.mean(axis=0, keepdims=True))[0]
        elif self.method == "lof":
            m = LocalOutlierFactor(n_neighbors=max(1, min(self.k * 2, n - 1)), novelty=True, metric="cosine")
            self.state["m"] = m.fit(x)
        else:
            self.state["m"] = IsolationForest(n_estimators=200, random_state=0).fit(x)
        return self

    def score(self, x: np.ndarray) -> np.ndarray:
        if self.method == "knn":
            sims = x @ self.state["x"].T
            k = min(self.k, sims.shape[1])
            top = -np.sort(-sims, axis=1)[:, :k]
            return 1.0 - top.mean(axis=1)  # 가장 가까운 k 개와의 평균 코사인 거리
        if self.method == "centroid":
            return 1.0 - x @ self.state["c"]
        return -self.state["m"].score_samples(x)


def out_of_fold(x: np.ndarray, method: str, k: int, folds: int = 5) -> np.ndarray:
    """자기 자신을 뺀 상태의 점수 (학습 데이터 점수는 너무 낮게 나오므로 임계값 보정에 쓴다)."""
    n = len(x)
    oof = np.zeros(n)
    for tr, te in KFold(n_splits=min(folds, n), shuffle=True, random_state=0).split(x):
        oof[te] = GroupScorer(method, k).fit(x[tr]).score(x[te])
    return oof


# ── 탐지기 ──────────────────────────────────────────────────────────────────
class Detector:
    def __init__(self, method: str = "knn", k: int = 5, quantile: float = 0.95, normal_label: str = "정상"):
        self.method, self.k, self.quantile, self.normal_label = method, k, quantile, normal_label
        self.groups: list[str] = []
        self.scorers: dict[str, GroupScorer] = {}
        self.thresholds: dict[str, float] = {}
        self.oof: dict[str, np.ndarray] = {}  # 정상 그룹의 점수 분포 → 백분위
        self.train_x: np.ndarray | None = None
        self.train_y: list[str] = []
        self.train_text: list[str] = []
        self.warnings: list[str] = []
        self.clf: LogisticRegression | None = None  # 정상 대 이상 (알려진 유형이 있을 때)

    def fit(self, x: np.ndarray, y: list[str], texts: list[str]) -> Detector:
        y = [lab or self.normal_label for lab in y]  # 라벨이 없으면 정상
        if self.normal_label not in y:
            raise AppError(f"정상 라벨 '{self.normal_label}' 이 붙은 예시가 없습니다. 정상 라벨 이름을 확인하세요.")
        for g in [self.normal_label] + sorted(set(y) - {self.normal_label}):
            idx = [i for i, lab in enumerate(y) if lab == g]
            need = MIN_NORMAL if g == self.normal_label else MIN_GROUP
            if len(idx) < need:
                if g == self.normal_label:
                    raise AppError(f"정상 예시가 {need}개 이상 필요합니다 (현재 {len(idx)}개).")
                self.warnings.append(f"'{g}' 예시가 {len(idx)}개뿐이라 제외했습니다 (유형마다 {need}개 이상).")
                continue
            xg = x[idx]
            # 알려진 유형은 예시가 적은 경우가 많아 밀도 기반(LOF·Isolation Forest)이 의미가 없다 → kNN 거리
            method = self.method if g == self.normal_label or self.method in ("knn", "centroid") else "knn"
            oof = out_of_fold(xg, method, self.k)
            self.groups.append(g)
            self.scorers[g] = GroupScorer(method, self.k).fit(xg)
            self.thresholds[g] = conformal_threshold(oof, self.quantile)
            if g == self.normal_label and len(idx) < STABLE_NORMAL:
                self.warnings.append(
                    f"정상 예시가 {len(idx)}개라 경계가 불안정할 수 있습니다. {STABLE_NORMAL}개 이상이면 오탐률이 설정값에 가까워집니다."
                )
            self.oof[g] = np.sort(oof)
        keep = [i for i, lab in enumerate(y) if lab in self.scorers]
        self.train_x = x[keep].astype(np.float32)
        self.train_y = [y[i] for i in keep]
        self.train_text = [texts[i] for i in keep]
        if self.known_types:
            self.clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=10.0)
            self.clf.fit(self.train_x, [lab != self.normal_label for lab in self.train_y])
        return self

    @property
    def known_types(self) -> list[str]:
        return [g for g in self.groups if g != self.normal_label]

    def _ratios(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """그룹별 원점수와 경계 비율(점수 ÷ 임계값; 1 이하 = 그 그룹의 경계 안). 점수가 음수일 수 있는 방법을 위해 최솟값 기준으로 옮긴다."""
        raw = np.column_stack([self.scorers[g].score(x) for g in self.groups])
        ratio = np.empty_like(raw)
        for j, g in enumerate(self.groups):
            lo = float(self.oof[g][0])
            span = max(self.thresholds[g] - lo, 1e-9)
            ratio[:, j] = (raw[:, j] - lo) / span  # 0 = 학습 데이터 중 가장 전형적, 1 = 임계값
        return raw, ratio

    def predict(self, x: np.ndarray) -> list[dict[str, Any]]:
        raw, ratio = self._ratios(x)
        ni = self.groups.index(self.normal_label)
        sims = x @ self.train_x.T
        p_anom = self.clf.predict_proba(x)[:, 1] if self.clf is not None else np.zeros(len(x))
        known = [j for j, g in enumerate(self.groups) if g != self.normal_label]
        out = []
        for r in range(len(x)):
            # 1 을 넘으면 이상: 정상 경계 비율과 분류기 확률(0.5 → 1) 중 큰 값
            score = max(float(ratio[r, ni]), 2 * float(p_anom[r]))
            if score <= 1.0:
                verdict = self.normal_label
            else:
                best = min(known, key=lambda j: ratio[r, j]) if known else None
                verdict = self.groups[best] if best is not None and ratio[r, best] <= 1.0 else NOVEL
            nn = int(np.argmax(sims[r]))
            out.append(
                {
                    "verdict": verdict,
                    "anomalous": verdict != self.normal_label,
                    "anomaly_score": round(score, 4),
                    "p_anomalous": round(float(p_anom[r]), 4) if self.clf is not None else None,
                    "normal_percentile": round(
                        float(np.searchsorted(self.oof[self.normal_label], raw[r, ni]) / len(self.oof[self.normal_label])), 4
                    ),
                    "boundary": {g: round(float(ratio[r, j]), 4) for j, g in enumerate(self.groups)},
                    "nearest": {"text": self.train_text[nn], "label": self.train_y[nn], "similarity": round(float(sims[r, nn]), 4)},
                }
            )
        return out

    def info(self) -> dict[str, Any]:
        return {
            "groups": [{"label": g, "n": self.train_y.count(g), "threshold": round(self.thresholds[g], 4)} for g in self.groups],
            "normal_label": self.normal_label,
            "known_types": self.known_types,
            "warnings": self.warnings,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> Detector:
        d = joblib.load(path)
        if not isinstance(d, Detector):
            raise AppError("탐지기 파일 형식이 올바르지 않습니다.")
        return d


# ── 평가 ────────────────────────────────────────────────────────────────────
def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "support": tp + fn}


def evaluate(det: Detector, gold: list[str], preds: list[dict[str, Any]]) -> dict[str, Any]:
    """정답 라벨: 정상 라벨 / 학습한 유형 이름 / 그 밖의 이름(= 신종으로 잡아야 할 것)."""
    known = set(det.groups)
    g_anom = [g != det.normal_label for g in gold]
    p_anom = [p["anomalous"] for p in preds]
    expected = [g if g in known else NOVEL for g in gold]
    out: dict[str, Any] = {
        "anomaly": _prf(
            sum(a and b for a, b in zip(g_anom, p_anom, strict=True)),
            sum(b and not a for a, b in zip(g_anom, p_anom, strict=True)),
            sum(a and not b for a, b in zip(g_anom, p_anom, strict=True)),
        ),
        "accuracy": round(float(np.mean([e == p["verdict"] for e, p in zip(expected, preds, strict=True)])), 4),
        "false_alarm_rate": round(sum(b and not a for a, b in zip(g_anom, p_anom, strict=True)) / max(1, g_anom.count(False)), 4),
    }
    if 0 < sum(g_anom) < len(g_anom):  # 양쪽이 다 있어야 AUC
        out["auc"] = round(float(roc_auc_score(g_anom, [p["anomaly_score"] for p in preds])), 4)
    g_nov = [e == NOVEL for e in expected]
    if any(g_nov):
        p_nov = [p["verdict"] == NOVEL for p in preds]
        out["novel"] = _prf(
            sum(a and b for a, b in zip(g_nov, p_nov, strict=True)),
            sum(b and not a for a, b in zip(g_nov, p_nov, strict=True)),
            sum(a and not b for a, b in zip(g_nov, p_nov, strict=True)),
        )
    cats = [det.normal_label, *det.known_types, NOVEL]
    out["confusion"] = {
        "labels": cats,
        "matrix": [[sum(e == a and p["verdict"] == b for e, p in zip(expected, preds, strict=True)) for b in cats] for a in cats],
    }
    return out


def score_hist(scores: list[float], groups: list[str] | None = None, top: float = 3.0, step: float = 0.25) -> list[dict[str, Any]]:
    """경계 비율 분포 (정답 그룹별 개수). 마지막 칸은 top 이상 전부."""
    edges = np.arange(0, top + 1e-9, step)
    rows = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else np.inf
        sel = [j for j, s in enumerate(scores) if lo <= max(s, 0) < hi]
        counts: dict[str, int] = {}
        for j in sel:
            g = groups[j] if groups else ""
            counts[g] = counts.get(g, 0) + 1
        rows.append({"from": round(float(lo), 2), "to": None if hi == np.inf else round(float(hi), 2), "n": len(sel), "by": counts})
    return rows


def explore(items: list[Item], x: np.ndarray, method: str, k: int, quantile: float, normal_label: str, top: int = 30) -> dict[str, Any]:
    """검사할 데이터 없이 한 묶음 안의 이상치를 찾는다 (자기 자신을 뺀 점수)."""
    if len(items) < MIN_NORMAL:
        raise AppError(f"이상치를 찾으려면 텍스트가 {MIN_NORMAL}개 이상 필요합니다.")
    oof = out_of_fold(x, method, k)
    lo, thr = float(oof.min()), conformal_threshold(oof, quantile)
    ratio = (oof - lo) / max(thr - lo, 1e-9)
    order = np.argsort(-ratio)
    has_gold = any(it.label for it in items)
    res: dict[str, Any] = {
        "mode": "explore",
        "n_flagged": int((ratio > 1).sum()),
        "outliers": [item_out(items[i], anomaly_score=round(float(ratio[i]), 4), rank=r + 1) for r, i in enumerate(order[:top])],
        "hist": score_hist(
            ratio.tolist(), [("이상" if (it.label or normal_label) != normal_label else "정상") for it in items] if has_gold else None
        ),
    }
    if has_gold:
        g = [(it.label or normal_label) != normal_label for it in items]
        if 0 < sum(g) < len(g):
            res["metrics"] = {"auc": round(float(roc_auc_score(g, ratio)), 4)}
            res["summary"] = res["metrics"] | {"flagged": res["n_flagged"]}
    res.setdefault("summary", {"flagged": res["n_flagged"]})
    return res
