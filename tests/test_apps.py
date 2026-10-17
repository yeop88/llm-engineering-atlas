"""의미 기반 응용: 추천 · (이후 기능 테스트를 이어서 추가)."""

import time

import numpy as np
import pytest

from app.apps import common
from app.apps.recommend import recommend


def _wait(client, job):
    for _ in range(400):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


def _model(client, hf_id="nlpai-lab/KURE-v1"):
    return next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == hf_id)


# ── 공통 ────────────────────────────────────────────────────────────────────
def test_embedding_cache_roundtrip():
    c = common.EmbeddingCache(max_items=2)
    assert c.get_many("m", "plain", None, ["a"]) == [None]
    c.put_many("m", "plain", None, ["a", "b", "c"], np.eye(3, dtype=np.float32))
    got = c.get_many("m", "plain", None, ["a", "c"])
    assert got[0] is None and np.allclose(got[1], [0, 0, 1])  # 용량 2 → 가장 오래된 a 제거
    assert c.get_many("m", "query", None, ["c"]) == [None]  # 역할이 다르면 다른 키


def test_resolve_texts_source_with_labels():
    items = common.resolve_source(
        None, {"type": "texts", "items": [{"text": " 안녕 ", "label": "인사"}, {"text": ""}, {"text": "b", "id": "x"}]}
    )
    assert [(i.key, i.text, i.label) for i in items] == [("1", "안녕", "인사"), ("x", "b", "")]
    with pytest.raises(common.AppError):
        common.resolve_source(None, {"type": "texts", "items": []})


# ── 추천 ────────────────────────────────────────────────────────────────────
def test_recommend_mmr_and_reasons():
    items = [common.Item(key=str(i), text=t) for i, t in enumerate(["축구1", "축구2", "축구3", "요리1", "요리2", "여행1"])]
    v = np.array([[1, 0, 0], [0.99, 0.1, 0], [0.98, 0.15, 0], [0, 1, 0], [0.1, 0.95, 0], [0.5, 0.5, 0.7]], dtype=np.float32)
    plain = recommend(items, v, liked=["0"], top_k=2, diversity=0.0)
    assert [r["key"] for r in plain["results"]] == ["1", "2"]  # 관련도만: 축구끼리
    assert plain["results"][0]["because"]["key"] == "0"
    diverse = recommend(items, v, liked=["0"], top_k=2, diversity=0.9)
    assert diverse["results"][1]["key"] != "2"  # 다양성: 두 번째는 축구가 아닌 것
    assert diverse["intra_similarity"] < plain["intra_similarity"]
    neg = recommend(items, v, liked=["0"], disliked=["5"], top_k=5, diversity=0.0)
    assert "5" not in [r["key"] for r in neg["results"]]
    with pytest.raises(common.AppError):
        recommend(items, v, liked=[])


def test_recommend_api(client):
    p = client.get("/api/apps/presets?app=recommend").json()
    assert p and p[0]["n"] == 30
    data = client.get(f"/api/apps/presets/{p[0]['name']}").json()
    src = {"type": "texts", "items": data["items"]}
    assert client.post("/api/apps/items", json={"source": src}).json()["n"] == 30
    body = {"model_id": _model(client), "source": src, "liked": ["a16", "a17"], "top_k": 3, "diversity": 0.0}
    job = _wait(client, client.post("/api/apps/recommend", json=body).json())
    assert job["status"] == "done", job
    res = job["result"]
    assert len(res["results"]) == 3 and all(r["key"] not in ("a16", "a17") for r in res["results"])
    assert [r["score"] for r in res["results"]] == sorted((r["score"] for r in res["results"]), reverse=True)
    assert all(r["because"]["key"] in ("a16", "a17") for r in res["results"])  # 추천 이유 = 좋아요한 아이템
    assert any(r["kind"] == "app_recommend" for r in client.get("/api/runs").json())
    # 같은 데이터 재실행은 캐시 사용
    hits = client.get("/api/apps/cache").json()["hits"]
    _wait(client, client.post("/api/apps/recommend", json=body | {"interest": "김치"}).json())
    assert client.get("/api/apps/cache").json()["hits"] >= hits + 30
    assert client.post("/api/apps/recommend", json=body | {"liked": [], "interest": ""}).status_code == 400


# ── 분류 ────────────────────────────────────────────────────────────────────
from app.apps import classify  # noqa: E402


def _blobs(n_per=8, dim=16, seed=0):
    rng = np.random.default_rng(seed)
    centers = np.eye(3, dim) * 3
    x = np.vstack([centers[i] + rng.normal(0, 0.3, (n_per, dim)) for i in range(3)])
    return common.normalize(x.astype(np.float32)), [lab for lab in ("가", "나", "다") for _ in range(n_per)]


@pytest.mark.parametrize("method", ["centroid", "knn", "logreg"])
def test_classifier_methods_and_persistence(method, tmp_path):
    x, y = _blobs()
    clf = classify.Classifier(method, ["가", "나", "다"], k=3).fit(x, y)
    pred = clf.predict(x, top=2)
    assert [p["label"] for p in pred] == y and all(0 < p["confidence"] <= 1 for p in pred)
    assert np.allclose(clf.predict_proba(x).sum(axis=1), 1)
    clf.save(tmp_path / "m.joblib")
    again = classify.Classifier.load(tmp_path / "m.joblib")
    assert [p["label"] for p in again.predict(x)] == y


def test_cross_validation_report():
    x, y = _blobs()
    cv, pred, warning = classify.cross_validate(x, y, "logreg", 5)
    assert not warning and cv["accuracy"] == 1.0 and cv["folds"] == 5
    assert np.array(cv["confusion"]).trace() == len(y)
    cv, _, warning = classify.cross_validate(x[:9], y[:8] + ["나"], "centroid", 5)
    assert cv is None and "2개 이상" in warning  # '가' 8개 + '나' 1개 → 교차검증 불가


def test_classify_api(client):
    data = client.get("/api/apps/presets/support_tickets").json()
    assert {lab["name"] for lab in data["labels"]} == {it["label"] for it in data["items"]}
    src = {"type": "texts", "items": data["items"]}
    mid = _model(client)
    job = _wait(
        client,
        client.post(
            "/api/apps/classify/train", json={"model_id": mid, "source": src, "method": "centroid", "name": "라우팅 테스트"}
        ).json(),
    )
    assert job["status"] == "done", job
    res = job["result"]
    assert res["metrics"]["folds"] == 5 and len(res["metrics"]["per_class"]) == 5 and res["saved"]["n_train"] == 50
    saved_id = res["saved"]["id"]
    pred = client.post(f"/api/apps/classifiers/{saved_id}/predict", json={"texts": [data["items"][0]["text"], "새 문장"]}).json()
    assert len(pred["results"]) == 2 and pred["results"][0]["label"] in res["labels"]
    assert any(m["id"] == saved_id for m in client.get("/api/apps/models?kind=classifier").json())

    zs = _wait(client, client.post("/api/apps/classify/zero-shot", json={"model_id": mid, "source": src, "labels": data["labels"]}).json())
    assert zs["status"] == "done" and "metrics" in zs["result"] and len(zs["result"]["items"]) == 50

    unlabeled = {"type": "texts", "items": [{"text": "라벨 없음"}, {"text": "둘"}]}
    bad = _wait(client, client.post("/api/apps/classify/train", json={"model_id": mid, "source": unlabeled}).json())
    assert bad["status"] == "error" and "라벨" in bad["error"]
    assert client.delete(f"/api/apps/models/{saved_id}").status_code == 200
    assert client.post(f"/api/apps/classifiers/{saved_id}/predict", json={"texts": ["x"]}).status_code == 404


# ── 클러스터링 ──────────────────────────────────────────────────────────────
from app.apps import cluster as clus  # noqa: E402


def _items_from(y, texts=None):
    texts = texts or [f"{lab} 문장 {i}" for i, lab in enumerate(y)]
    return [common.Item(key=str(i), text=t, label=lab) for i, (t, lab) in enumerate(zip(texts, y, strict=True))]


@pytest.mark.parametrize("method", ["kmeans", "agglomerative", "hdbscan"])
def test_cluster_methods_recover_blobs(method):
    x, y = _blobs(n_per=10)
    texts = [{"가": "축구 경기 결과", "나": "김치 요리 방법", "다": "주식 시장 동향"}[lab] + f" {i}" for i, lab in enumerate(y)]
    res = clus.cluster(_items_from(y, texts), x, method=method, k=None, k_max=6, min_cluster_size=4)
    assert res["k"] == 3 and res["agreement"]["ari"] == 1.0 and res["agreement"]["purity"] == 1.0
    assert res["silhouette"] > 0.5 and len(res["points"]) == 30
    kw = {c["id"]: c["keywords"] for c in res["clusters"] if not c["noise"]}
    assert any("축구" in k for k in kw.values()) and any("주식" in k for k in kw.values())
    if method != "hdbscan":
        assert res["k_scores"][1]["k"] == 3  # k=2,3,... 의 실루엣이 기록됨


def test_cluster_explicit_k_and_errors():
    x, y = _blobs(n_per=4)
    assert clus.cluster(_items_from(y), x, "kmeans", k=2)["k"] == 2
    with pytest.raises(common.AppError):
        clus.cluster(_items_from(y[:3]), x[:3])
    with pytest.raises(common.AppError):
        clus.cluster(_items_from(y), x, "kmeans", k=12)


def test_cluster_api(client):
    presets = {p["name"] for p in client.get("/api/apps/presets?app=cluster").json()}
    assert {"support_tickets", "sentiment_reviews"} <= presets
    items = client.get("/api/apps/presets/support_tickets").json()["items"]
    job = _wait(
        client,
        client.post(
            "/api/apps/cluster", json={"model_id": _model(client), "source": {"type": "texts", "items": items}, "method": "kmeans", "k": 5}
        ).json(),
    )
    assert job["status"] == "done", job
    r = job["result"]
    assert r["k"] == 5 and sum(c["size"] for c in r["clusters"]) == 50 and "agreement" in r
    assert all(c["keywords"] for c in r["clusters"]) and all(len(c["representatives"]) <= 3 for c in r["clusters"])


def test_cluster_all_noise_has_no_agreement():
    rng = np.random.default_rng(3)
    x = common.normalize(rng.standard_normal((8, 16)).astype(np.float32))  # 흩어진 점 → HDBSCAN 이 모두 노이즈
    res = clus.cluster(_items_from(["가", "나"] * 4), x, "hdbscan", min_cluster_size=6)
    assert res["k"] == 0 and "agreement" not in res and "노이즈" in res["warning"]


# ── 중복·표절 ───────────────────────────────────────────────────────────────
from app.apps import dedup  # noqa: E402


def test_near_duplicates_groups_and_kinds():
    texts = ["비밀번호를 잊었어요", "비밀번호를 잊었어요", "암호를 잊었을 때 재설정하는 방법", "환불 언제 되나요", "배송지 변경"]
    v = common.normalize(np.array([[1, 0, 0], [1, 0, 0], [0.97, 0.24, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32))
    res = dedup.near_duplicates([common.Item(key=str(i), text=t) for i, t in enumerate(texts)], v, threshold=0.95)
    assert res["n_groups"] == 1 and res["n_remove"] == 2 and res["keep_keys"] == ["0", "3", "4"]
    kinds = {m["key"]: m["kind"] for m in res["groups"][0]["members"]}
    assert kinds == {"0": None, "1": "copy", "2": "paraphrase"}
    longest = dedup.near_duplicates([common.Item(key=str(i), text=t) for i, t in enumerate(texts)], v, 0.95, keep="longest")
    assert longest["groups"][0]["representative"] == "2"  # 가장 긴 텍스트를 남김


def test_plagiarism_kinds():
    ref = [common.Item(key="r1", text="원문")]
    ref_sents = [(ref[0], "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"), (ref[0], "미세먼지가 심한 날에는 마스크를 쓴다")]
    suspect = ["공문서는 어문규범에 맞추어 한글로 작성하여야 한다", "공공 문서는 맞춤법에 따라 한국어로 써야 한다", "우리 팀은 실험을 했다"]
    rv = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    sv = np.array([[1, 0, 0], [0.95, 0.1, 0.1], [0, 0, 1]], dtype=np.float32)
    res = dedup.plagiarism(suspect, sv, ref_sents, rv, threshold=0.85, copy_lex=0.6)
    assert [s["kind"] for s in res["sentences"]] == ["copy", "paraphrase", "original"]
    assert 0 < res["ratio"]["copy"] < res["ratio"]["total"] < 1 and res["sources"][0]["key"] == "r1"


def test_dedup_and_plagiarism_api(client):
    mid = _model(client)
    items = client.get("/api/apps/presets/dedup_questions").json()["items"]
    job = _wait(
        client,
        client.post("/api/apps/dedup", json={"model_id": mid, "source": {"type": "texts", "items": items}, "threshold": 0.99}).json(),
    )
    assert job["status"] == "done", job
    assert job["result"]["n_groups"] >= 1 and job["result"]["kinds"].get("copy", 0) >= 1  # 글자까지 같은 첫 두 줄
    p = client.get("/api/apps/presets/plagiarism_essay").json()
    job = _wait(
        client,
        client.post(
            "/api/apps/plagiarism", json={"model_id": mid, "suspect": p["suspect"], "reference": {"type": "texts", "items": p["items"]}}
        ).json(),
    )
    assert job["status"] == "done", job
    r = job["result"]
    assert r["sentences"][0]["text"] == "인공지능 검색 기술 동향 보고서"  # 줄바꿈은 문장 경계
    assert r["sentences"][1]["kind"] == "copy" and r["ratio"]["copy"] > 0  # 첫 본문 문장은 원문 그대로
    assert r["n_reference"] >= 8


def test_near_duplicates_no_chaining():
    # A~B, B~C 는 임계값 이상이지만 A~C 는 아님 → 연쇄로 A, C 가 묶이면 안 된다
    a, b, c = np.array([1.0, 0, 0]), np.array([0.9, 0.436, 0]), np.array([0.62, 0.785, 0])
    v = common.normalize(np.vstack([a, b, c]).astype(np.float32))
    assert v[0] @ v[1] > 0.88 and v[1] @ v[2] > 0.88 and v[0] @ v[2] < 0.88
    res = dedup.near_duplicates([common.Item(key=k, text=k) for k in "abc"], v, threshold=0.88)
    assert res["n_groups"] == 1 and [m["key"] for m in res["groups"][0]["members"]] == ["a", "b"]
    assert res["nn_similarity"]["median"] > 0.88 and sum(h["n"] for h in res["nn_similarity"]["hist"]) == 3
