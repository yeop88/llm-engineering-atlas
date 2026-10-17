import numpy as np
import pytest

from app.stages.embedding.benchmark import DatasetError, pearson, retrieval_metrics, spearman, validate_dataset


def test_retrieval_metrics_perfect_and_miss():
    doc_ids = ["a", "b", "c"]
    scores = np.array([[0.9, 0.1, 0.0], [0.1, 0.2, 0.9]])
    overall, per_query = retrieval_metrics(scores, doc_ids, [{"a"}, {"b"}])
    # q1: 정답 a 가 1위 → 모든 지표 1.0 / q2: 정답 b 가 2위 → MRR 0.5
    assert per_query[0]["mrr@10"] == 1.0
    assert per_query[1]["rank_of_first_relevant"] == 2
    assert per_query[1]["mrr@10"] == 0.5
    assert per_query[1]["recall@1"] == 0.0
    assert per_query[1]["recall@3"] == 1.0
    assert overall["mrr@10"] == pytest.approx(0.75)
    assert per_query[1]["ndcg@10"] == pytest.approx(1 / np.log2(3), abs=1e-4)  # 응답은 소수 4자리로 반올림


def test_retrieval_metrics_multiple_relevant():
    scores = np.array([[0.9, 0.8, 0.1, 0.0]])
    overall, _ = retrieval_metrics(scores, ["a", "b", "c", "d"], [{"a", "c"}])
    assert overall["recall@1"] == 0.5
    assert overall["recall@3"] == 1.0


def test_correlations():
    x = np.array([1, 2, 3, 4, 5.0])
    assert spearman(x, x * 10) == pytest.approx(1.0)
    assert spearman(x, -x) == pytest.approx(-1.0)
    assert pearson(x, 2 * x + 1) == pytest.approx(1.0)
    # 단조 증가지만 비선형 → spearman 1, pearson < 1
    assert spearman(x, x**3) == pytest.approx(1.0)
    assert pearson(x, x**3) < 1.0


def test_spearman_ties():
    assert spearman(np.array([1, 1, 2, 3.0]), np.array([1, 1, 2, 3.0])) == pytest.approx(1.0)


def test_validate_dataset():
    ok = {
        "name": "x",
        "type": "retrieval",
        "corpus": [{"id": "d1", "text": "t"}],
        "queries": [{"id": "q", "text": "t", "relevant": ["d1"]}],
    }
    assert validate_dataset(ok) is ok
    with pytest.raises(DatasetError):
        validate_dataset(ok | {"queries": [{"id": "q", "text": "t", "relevant": ["nope"]}]})
    with pytest.raises(DatasetError):
        validate_dataset({"name": "bad name!", "type": "sts", "pairs": []})
    with pytest.raises(DatasetError):
        validate_dataset({"name": "s", "type": "sts", "pairs": [{"s1": "a", "s2": "b", "score": 1}]})
