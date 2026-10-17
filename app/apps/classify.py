"""텍스트 분류: 제로샷(라벨 설명과의 유사도) · 퓨샷 학습(중심점 / kNN / 로지스틱 회귀) · 교차검증 평가 · 저장·예측."""

from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold

from app.apps.common import AppError, normalize, snippet

METHODS = {"centroid": "중심점 (라벨별 평균 벡터)", "knn": "k-최근접 이웃", "logreg": "로지스틱 회귀"}


def softmax(x: np.ndarray, temperature: float) -> np.ndarray:
    z = x / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


# ── 모델 ────────────────────────────────────────────────────────────────────
class Classifier:
    """임베딩 → 라벨. 학습 데이터 벡터는 정규화되어 있다고 가정한다."""

    def __init__(self, method: str, labels: list[str], k: int = 5, temperature: float = 0.05):
        if method not in METHODS:
            raise AppError(f"알 수 없는 분류 방법: {method}")
        self.method, self.labels, self.k, self.temperature = method, labels, k, temperature
        self.state: dict[str, Any] = {}

    def fit(self, x: np.ndarray, y: list[str]) -> Classifier:
        yi = np.array([self.labels.index(v) for v in y])
        if self.method == "centroid":
            self.state["centroids"] = normalize(np.vstack([x[yi == i].mean(axis=0) for i in range(len(self.labels))]))
        elif self.method == "knn":
            self.state["x"], self.state["y"] = x.astype(np.float32), yi
        else:
            clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=10.0)
            clf.fit(x, yi)
            self.state["clf"] = clf
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        n_cls = len(self.labels)
        if self.method == "centroid":
            return softmax(x @ self.state["centroids"].T, self.temperature)
        if self.method == "knn":
            sims = x @ self.state["x"].T
            k = min(self.k, sims.shape[1])
            top = np.argsort(-sims, axis=1)[:, :k]
            proba = np.zeros((len(x), n_cls))
            for r in range(len(x)):
                w = np.exp(sims[r, top[r]] / self.temperature)  # 가까울수록 큰 가중치
                for j, wt in zip(top[r], w, strict=True):
                    proba[r, self.state["y"][j]] += wt
            return proba / proba.sum(axis=1, keepdims=True)
        clf: LogisticRegression = self.state["clf"]
        proba = np.zeros((len(x), n_cls))
        proba[:, clf.classes_] = clf.predict_proba(x)
        return proba

    def predict(self, x: np.ndarray, top: int = 3) -> list[dict[str, Any]]:
        proba = self.predict_proba(x)
        out = []
        for p in proba:
            order = np.argsort(-p)[:top]
            out.append(
                {
                    "label": self.labels[order[0]],
                    "confidence": round(float(p[order[0]]), 4),
                    "top": [{"label": self.labels[i], "p": round(float(p[i]), 4)} for i in order],
                }
            )
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"method": self.method, "labels": self.labels, "k": self.k, "temperature": self.temperature, "state": self.state}, path)

    @classmethod
    def load(cls, path: Path) -> Classifier:
        d = joblib.load(path)
        c = cls(d["method"], d["labels"], d["k"], d["temperature"])
        c.state = d["state"]
        return c


# ── 평가 ────────────────────────────────────────────────────────────────────
def report(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict[str, Any]:
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    return {
        "accuracy": round(float(np.mean(np.array(y_true) == np.array(y_pred))), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "per_class": [
            {
                "label": lab,
                "precision": round(float(p[i]), 4),
                "recall": round(float(r[i]), 4),
                "f1": round(float(f[i]), 4),
                "support": int(s[i]),
            }
            for i, lab in enumerate(labels)
        ],
        "confusion": confusion_matrix(y_true, y_pred, labels=labels).tolist(),  # 행 = 정답, 열 = 예측
    }


def cross_validate(x: np.ndarray, y: list[str], method: str, k: int, folds: int = 5) -> tuple[dict[str, Any] | None, list[str] | None, str]:
    labels = sorted(set(y))
    counts = Counter(y)
    n_folds = min(folds, min(counts.values()))
    if n_folds < 2:
        return (
            None,
            None,
            f"교차검증을 하려면 라벨마다 예시가 2개 이상 필요합니다 (가장 적은 라벨: {min(counts, key=counts.get)} {min(counts.values())}개).",
        )
    pred = [""] * len(y)
    for tr, te in StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=0).split(x, y):
        clf = Classifier(method, labels, k).fit(x[tr], [y[i] for i in tr])
        for i, r in zip(te, clf.predict(x[te], top=1), strict=True):
            pred[i] = r["label"]
    return report(y, pred, labels) | {"folds": n_folds}, pred, ""


def zero_shot(x: np.ndarray, label_vecs: np.ndarray, labels: list[str], temperature: float = 0.05) -> list[dict[str, Any]]:
    clf = Classifier("centroid", labels, temperature=temperature)
    clf.state["centroids"] = normalize(label_vecs)
    return clf.predict(x)


def errors(texts: list[str], y: list[str], pred: list[str], limit: int = 30) -> list[dict[str, str]]:
    return [{"text": snippet(t, 200), "gold": g, "pred": p} for t, g, p in zip(texts, y, pred, strict=True) if g != p][:limit]
