"""6 라우팅: 학습 라우터(교차검증)."""

import numpy as np
import pytest

from app.core.db import SessionLocal
from app.stages.routing import learned, service
from tests.helpers import model_id


def _rows(n=24, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        hard = i % 3 == 0  # 긴 '왜 · 어떻게' 질문이 전체 경로에서 나음
        q = f"질문 {i} 왜 그렇게 되는지 절차와 이유를 각각 자세히 설명해 주세요" if hard else f"질문 {i} 기한은?"
        rows.append({"query": q, "confidence": float(rng.uniform(0, 0.05) if hard else rng.uniform(0.1, 0.4)),
                     "easy": {"quality": 0.0 if hard else 1.0, "ndcg": None, "ms": 1000.0, "search_ms": 50.0, "answer": None},
                     "hard": {"quality": 1.0, "ndcg": None, "ms": 3000.0, "search_ms": 80.0, "answer": None},
                     "rule": {"path": "hard" if hard else "easy", "reason": ""}, "llm": None})  # fmt: skip
    return rows


def test_learned_router_cross_validated(client):
    rows = _rows()
    with SessionLocal() as db:
        from app.core import crud

        spec = crud.get_spec(db, model_id(client, "nlpai-lab/KURE-v1"), "embedding")
    model, cv = learned.train(spec, rows)
    assert cv["n_hard"] == 8 and cv["folds"] == 5 and len(cv["proba"]) == len(rows)
    paths = ["hard" if p >= 0.5 else "easy" for p in cv["proba"]]
    res = service.evaluate(rows, ["rule", "confidence"], 0.05, {"learned": paths})
    by = {r["router"]: r for r in res["results"]}
    assert "learned" in by and by["learned"]["quality"] >= by["always_easy"]["quality"]
    assert by["learned"]["latency_ms"]["mean"] < by["always_hard"]["latency_ms"]["mean"]
    path, why = learned.route(model, spec, rows[0]["query"], [{"score": 0.5}, {"score": 0.49}])
    assert path in ("easy", "hard") and "어려움 확률" in why
    with pytest.raises(ValueError):
        learned.cross_val_proba(np.zeros((4, 3)), ["easy", "easy", "easy", "hard"])  # 한쪽이 2개 미만
