"""학습 라우터: 라우팅 평가 기록(질문마다 쉬운 · 어려운 경로를 둘 다 실행한 결과)으로 '어려운 경로가 실제로 나았던 질문'을 배운다.

왜
- 규칙 · 확신도 · LLM 라우터는 사람이 정한 신호 하나씩만 본다. 평가 기록에는 질문마다 정답(오라클: 어느 경로가 나았나)이
  이미 있으므로, 그것을 라벨로 삼아 여러 신호를 함께 쓰는 분류기를 만들 수 있다 — 추가 실험 비용 없이.
- 입력 = 질문 임베딩(질문의 주제 · 형태) + 검색 확신도(이 문서 모음에서 쉬운가) + 규칙 신호(길이 · 이유/방법을 묻는 말 · 여러 요구).
  모델은 로지스틱 회귀: 질문 수가 수십~수백 개라 큰 모델은 외워 버린다. class_weight=balanced — 어려운 쪽이 드물어도 무시하지 않게.
- 평가는 교차검증(학습에 쓰지 않은 질문으로 예측) — 같은 질문으로 배우고 채점하면 오라클에 가깝게 부풀려진다.
- 라벨: 어려운 경로 품질 > 쉬운 경로 품질 + margin 이면 hard. 동점은 쉬움(같은 품질이면 싼 쪽이 정답 — 오라클과 같은 규칙).
"""

import pickle
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.routing.routers import EASY, HARD, confidence, rule_features

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)


def artifact_path(router_id: int) -> Path:
    d = get_settings().data_dir / "routers"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{router_id}.pkl"


def signals(question: str, conf: float | None) -> list[float]:
    """임베딩 외 신호. 척도를 0~수 정도로 맞춘다(로지스틱 회귀의 규제가 한 신호만 누르지 않게)."""
    f = rule_features(question)
    return [
        conf if conf is not None else 0.0,
        1.0 if conf is None else 0.0,
        f["chars"] / 100,
        len(f["hard_words"]),
        f["joins"],
        f["questions"] - 1,
    ]


def features(spec: ModelSpec, questions: list[str], confs: list[float | None]) -> np.ndarray:
    mgr = get_manager()
    emb = mgr.encode(mgr.get(spec), questions, "query").embeddings
    return np.hstack([emb, np.array([signals(q, c) for q, c in zip(questions, confs, strict=True)], dtype=np.float32)])


def labels(rows: list[dict[str, Any]], margin: float = 0.0) -> list[str]:
    return [HARD if r[HARD]["quality"] > r[EASY]["quality"] + margin else EASY for r in rows]


def _model(c: float):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=c, class_weight="balanced", max_iter=2000)


def cross_val_proba(x: np.ndarray, y: list[str], c: float = 1.0, seed: int = 0) -> tuple[np.ndarray, int]:
    """교차검증으로 질문마다 '어려움' 확률(그 질문을 빼고 학습한 모델의 예측). → (확률, 폴드 수)."""
    from sklearn.model_selection import StratifiedKFold

    yy = np.array([v == HARD for v in y])
    minority = int(min(yy.sum(), (~yy).sum()))
    if minority < 2:
        raise ValueError(f"쉬움 · 어려움 질문이 각각 2개 이상 필요합니다 (지금 어려움 {int(yy.sum())} · 쉬움 {int((~yy).sum())}). "
                         "평가 질문을 늘리거나 margin 을 낮추세요.")  # fmt: skip
    folds = min(5, minority)
    p = np.zeros(len(y))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=seed).split(x, yy):
        p[te] = _model(c).fit(x[tr], yy[tr]).predict_proba(x[te])[:, 1]
    return p, folds


def train(spec: ModelSpec, rows: list[dict[str, Any]], margin: float = 0.0, c: float = 1.0) -> tuple[Any, dict[str, Any]]:
    """평가 기록 → (학습된 모델 — 모든 질문으로, 교차검증 예측). 질문마다 확신도는 기록에 있는 값을 쓴다."""
    qs = [r["query"] for r in rows]
    x = features(spec, qs, [r.get("confidence") for r in rows])
    y = labels(rows, margin)
    p, folds = cross_val_proba(x, y, c)
    model = _model(c).fit(x, np.array([v == HARD for v in y]))
    return model, {"proba": p.tolist(), "labels": y, "folds": folds, "n_hard": y.count(HARD), "n": len(y)}


def save(model: Any, router_id: int) -> None:
    artifact_path(router_id).write_bytes(pickle.dumps(model))


def load(router_id: int) -> Any:
    # 직접 만든 파일만 읽는다(data/routers) — pickle 은 신뢰할 수 없는 파일을 읽으면 코드가 실행될 수 있다
    return pickle.loads(artifact_path(router_id).read_bytes())  # noqa: S301


def route(model: Any, spec: ModelSpec, question: str, results: list[dict[str, Any]], threshold: float = 0.5) -> tuple[str, str]:
    """→ (경로, 이유). 확신도 신호를 쓰므로 쉬운 경로로 먼저 검색한 결과가 필요하다(확신도 라우터와 같은 비용)."""
    conf = confidence(results)
    p = float(model.predict_proba(features(spec, [question], [conf]))[0, 1])
    path = HARD if p >= threshold else EASY
    return path, f"어려움 확률 {p:.2f} ({'≥' if path == HARD else '<'} {threshold}) · 확신도 {conf if conf is None else round(conf, 3)}"
