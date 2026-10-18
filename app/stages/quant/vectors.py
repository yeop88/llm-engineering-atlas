"""임베딩 양자화 조합 실험: 모델 가중치 정밀도 × 차원(Matryoshka) × 벡터 정밀도를 동시에 적용했을 때의
검색 정확도 · 메모리 · 속도를 공개 검색 벤치마크로 잰다.

설계 이유
- 공개 검색 벤치마크(질문 수백 개)를 쓴다. 양자화 손실은 대개 1~2%p 라 질문이 적은 내 평가 세트로는 우연과 구분되지 않는다.
- 여러 양자화를 '동시에' 쓰면 효과가 곱으로 줄지만 손실도 겹친다. 그래서 고른 기술끼리 모든 조합을 같은 질문으로 채점하고,
  기준(float32 가중치 · 전체 차원 · float32 벡터)과 짝지어 비교한다.
- 인코딩은 가중치 변형마다 한 번만 하고, 차원 · 벡터 정밀도는 그 임베딩을 잘라 · 바꿔 가며 점수만 다시 매긴다. 차이가 오직
  그 조합에서 오도록, 그리고 인코딩(가장 비싼 부분)을 반복하지 않으려고.
- 정확도는 두 가지: 정답 기준 nDCG@10 과, 정답과 무관한 '기준 상위 10개를 얼마나 그대로 찾는가'(overlap@10 — 양자화 오차 자체).
- 메모리 대비 정확도가 다른 어떤 조합에도 지지 않는 조합(파레토 최적)을 표시해 고르기 쉽게 한다.
"""

import copy
import time
from typing import Any

import numpy as np
from sentence_transformers.util.quantization import quantize_embeddings

from app.core import stats
from app.stages.embedding.benchmark import doc_text, retrieval_metrics
from app.stages.embedding.model_manager import LoadedModel, ModelManager
from app.stages.quant.techniques import BY_KEY

VECTOR_KEYS = ["float32", "float16", "int8", "int4", "binary", "binary_rescore", "pq"]
WEIGHT_KEYS = ["w_fp32", "w_bf16", "w_int8"]
PRECISIONS = {k: BY_KEY[k]["name"] for k in VECTOR_KEYS}  # 이전 API 와 호환
_POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)  # 바이트별 1 의 개수(해밍 거리용)


def _hamming(qb: np.ndarray, db: np.ndarray, chunk: int = 32) -> np.ndarray:
    """(nq, nd) 해밍 거리. 질의를 나눠 계산해 중간 배열(nq × nd × 바이트)이 메모리를 넘치지 않게 한다."""
    out = np.empty((qb.shape[0], db.shape[0]), dtype=np.int32)
    for i in range(0, qb.shape[0], chunk):
        out[i : i + chunk] = _POP[qb[i : i + chunk, None, :] ^ db[None, :, :]].sum(axis=-1)
    return out


def _sq_dequant(d: np.ndarray, levels: int) -> np.ndarray:
    """차원별 최소~최대를 levels 칸으로 나눈 스칼라 양자화 → 각 칸의 가운데 값으로 복원(검색은 float 질의 × 복원 문서)."""
    lo, hi = d.min(axis=0), d.max(axis=0)
    step = np.where(hi > lo, (hi - lo) / levels, 1.0)
    codes = np.clip(np.floor((d - lo) / step), 0, levels - 1)
    return (lo + (codes + 0.5) * step).astype(np.float32)


def _pq(q: np.ndarray, d: np.ndarray, m: int) -> np.ndarray:
    """곱 양자화: m 조각 × 256개 코드북(k-means), 질의는 양자화하지 않고 조각별 거리표로 점수(ADC)."""
    from sklearn.cluster import KMeans  # 무거워서 PQ 를 고를 때만 불러온다

    dim = d.shape[1]
    m = max(g for g in range(1, min(m, dim) + 1) if dim % g == 0)  # 차원을 나눠떨어지게 하는 가장 큰 조각 수
    sub = dim // m
    k = min(256, d.shape[0])
    scores = np.zeros((q.shape[0], d.shape[0]), dtype=np.float32)
    for j in range(m):
        ds, qs = d[:, j * sub : (j + 1) * sub], q[:, j * sub : (j + 1) * sub]
        km = KMeans(n_clusters=k, n_init=1, max_iter=25, random_state=0).fit(ds)
        table = qs @ km.cluster_centers_.T.astype(np.float32)  # (nq, k)
        scores += table[:, km.labels_]
    return scores


def score(precision: str, q: np.ndarray, d: np.ndarray, rescore_mult: int = 4, pq_m: int = 32, k: int = 10) -> tuple[np.ndarray, float]:
    """벡터 정밀도 하나로 (질의 × 문서) 점수와 질의당 검색 시간(ms). q · d 는 정규화된 float32."""
    t = time.perf_counter()
    if precision == "float32":
        s = q @ d.T
    elif precision == "float16":
        s = (q.astype(np.float16) @ d.astype(np.float16).T).astype(np.float32)
    elif precision == "int8":
        # 질의도 문서 범위로 int8 로 바꿔 정수 내적 — 벡터 DB 의 int8 검색과 같은 방식
        di = quantize_embeddings(d, "int8", calibration_embeddings=d)
        qi = quantize_embeddings(q, "int8", calibration_embeddings=d)
        t = time.perf_counter()
        s = (qi.astype(np.int32) @ di.astype(np.int32).T).astype(np.float32)
    elif precision == "int4":
        # 4비트는 질의까지 줄이면 손실이 커서, 보통처럼 질의는 float 로 두고 문서만 4비트(비대칭)
        deq = _sq_dequant(d, 16)
        t = time.perf_counter()
        s = q @ deq.T
    elif precision in ("binary", "binary_rescore"):
        db, qb = quantize_embeddings(d, "ubinary"), quantize_embeddings(q, "ubinary")
        t = time.perf_counter()
        ham = _hamming(qb, db)
        if precision == "binary":
            s = -ham.astype(np.float32)
        else:
            # 해밍 상위 k×배수 후보만 float32 질의 · int8(복원) 문서로 다시 점수. 후보 밖은 해밍 순서를 유지하되 항상 뒤로.
            deq = _sq_dequant(d, 256)
            n_cand = min(d.shape[0], k * rescore_mult)
            cand = np.argpartition(ham, n_cand - 1, axis=1)[:, :n_cand]
            s = -ham.astype(np.float32) - 1e6
            s[np.arange(len(q))[:, None], cand] = np.einsum("qd,qcd->qc", q, deq[cand])
    elif precision == "pq":
        s = _pq(q, d, pq_m)  # 코드북 학습 시간은 색인 비용이라 검색 시간에서 뺄 수 없어 함께 잰다(표에 표시)
    else:
        raise ValueError(f"알 수 없는 정밀도: {precision}")
    return s, (time.perf_counter() - t) * 1000 / len(q)


def bytes_per_vector(precision: str, dim: int, pq_m: int = 32) -> dict[str, float]:
    """메모리(검색할 때 RAM 에 둬야 하는 것)와 디스크(재점수용 int8 을 함께 저장) 바이트."""
    if precision == "pq":
        m = max(g for g in range(1, min(pq_m, dim) + 1) if dim % g == 0)
        return {"ram": float(m), "disk": float(m)}
    ram = {"float32": 4 * dim, "float16": 2 * dim, "int8": dim, "int4": dim / 2, "binary": dim / 8, "binary_rescore": dim / 8}[precision]
    return {"ram": ram, "disk": ram + (dim if precision == "binary_rescore" else 0)}


def _overlap(ref: np.ndarray, other: np.ndarray, k: int = 10) -> float:
    a = np.argsort(-ref, axis=1)[:, :k]
    b = np.argsort(-other, axis=1)[:, :k]
    return float(np.mean([len(set(x) & set(y)) / k for x, y in zip(a, b, strict=True)]))


def weight_variant(lm: LoadedModel, kind: str) -> LoadedModel:
    """가중치 정밀도를 바꾼 사본. 관리 중인 원본을 바꾸면 다른 화면의 결과가 달라지므로 복사본에 적용한다."""
    if kind == "w_fp32":
        return lm
    import torch

    model = copy.deepcopy(lm.model)
    if not isinstance(model, torch.nn.Module):  # torch 모델이 아니면(테스트의 가짜 모델 등) 바꿀 가중치가 없다
        pass
    elif kind == "w_bf16":
        model = model.to("cpu", torch.bfloat16)
    elif kind == "w_int8":
        # Linear 가중치만 int8 — 임베딩 · 정규화 층은 그대로 둔다(PyTorch 동적 양자화의 표준 대상)
        model = torch.ao.quantization.quantize_dynamic(model.to("cpu"), {torch.nn.Linear}, dtype=torch.qint8)
    else:
        raise ValueError(f"알 수 없는 가중치 정밀도: {kind}")
    return LoadedModel(key=f"{lm.key}::{kind}", spec=lm.spec, profile=lm.profile, model=model, device="cpu", dtype=kind,
                       load_seconds=0.0, loaded_at=lm.loaded_at)  # fmt: skip


def _truncate(x: np.ndarray, dim: int | None) -> np.ndarray:
    if not dim or dim >= x.shape[1]:
        return x
    y = x[:, :dim]
    return (y / np.maximum(np.linalg.norm(y, axis=1, keepdims=True), 1e-12)).astype(np.float32)


def _pareto(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        r["pareto"] = r["status"] == "ok" and not any(
            o is not r and o["status"] == "ok" and o["bytes"]["ram"] <= r["bytes"]["ram"] and o["metrics"]["ndcg@10"] >= r["metrics"]["ndcg@10"]
            and (o["bytes"]["ram"] < r["bytes"]["ram"] or o["metrics"]["ndcg@10"] > r["metrics"]["ndcg@10"])
            for o in rows
        )  # fmt: skip


def evaluate(manager: ModelManager, lm: LoadedModel, data: dict[str, Any], opts: dict[str, Any], job=None) -> dict[str, Any]:
    """opts: weights · dims(None = 전체) · precisions · rescore_mult · pq_m · batch_size."""
    corpus, queries = data["corpus"], data["queries"]
    doc_ids = [x["id"] for x in corpus]
    relevant = [set(x["relevant"]) for x in queries]
    weights = ["w_fp32", *[w for w in opts["weights"] if w != "w_fp32"]]  # 기준 가중치는 항상 포함
    precisions = ["float32", *[p for p in opts["precisions"] if p != "float32"]]
    dims = [None, *[d for d in opts["dims"] if d]]
    rows: list[dict[str, Any]] = []
    base: dict[str, Any] = {}
    full_dim = None
    for wi, w in enumerate(weights):
        if job:
            job.update(wi / len(weights), f"{lm.spec.hf_id} · {BY_KEY[w]['name']} 인코딩")
        try:
            lmv = weight_variant(lm, w)
            t = time.perf_counter()
            d = manager.encode(lmv, [doc_text(x) for x in corpus], "document", batch_size=opts.get("batch_size", 32))
            q = manager.encode(lmv, [x["text"] for x in queries], "query", batch_size=opts.get("batch_size", 32))
            enc_s = time.perf_counter() - t
        except Exception as exc:  # 이 CPU 에서 bf16 미지원 등 — 그 가중치만 실패로 두고 나머지 조합은 잰다
            rows.append({"weight": w, "dim": None, "precision": None, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        full_dim = full_dim or int(d.embeddings.shape[1])
        tps = round((len(corpus) + len(queries)) / enc_s, 1) if enc_s else None
        for dim in dims:
            if dim and dim >= d.embeddings.shape[1]:
                continue
            de, qe = _truncate(d.embeddings, dim), _truncate(q.embeddings, dim)
            for p in precisions:
                try:
                    s, ms = score(p, qe, de, opts.get("rescore_mult", 4), opts.get("pq_m", 32))
                except Exception as exc:
                    rows.append({"weight": w, "dim": dim, "precision": p, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
                    continue
                m, pq = retrieval_metrics(s, doc_ids, relevant)
                nd = [x["ndcg@10"] for x in pq]
                is_base = w == "w_fp32" and dim is None and p == "float32"
                if is_base:
                    base = {"scores": s, "ndcg": nd}
                b = bytes_per_vector(p, int(de.shape[1]), opts.get("pq_m", 32))
                rows.append({
                    "weight": w, "dim": int(de.shape[1]), "precision": p, "status": "ok", "is_base": is_base,
                    "label": " + ".join(x for x in [BY_KEY[w]["name"] if w != "w_fp32" else "", f"{int(de.shape[1])}차원" if dim else "", BY_KEY[p]["name"]] if x),
                    "metrics": {k: round(v, 4) for k, v in m.items()}, "ci": stats.mean_ci(nd), "_nd": nd, "_s": s,
                    "bytes": b, "gb_per_million": {k: round(v * 1e6 / 2**30, 3) for k, v in b.items()},
                    "search_ms": round(ms, 3), "encode_texts_per_s": tps,
                })  # fmt: skip
    ok = [r for r in rows if r["status"] == "ok"]
    if not base:  # 기준(float32 가중치 · 전체 차원 · float32)을 못 만들면 비교 자체가 안 된다
        raise RuntimeError(next((r["error"] for r in rows if r["status"] == "error"), "기준 임베딩을 만들지 못했습니다."))
    for r in ok:
        r["ram_ratio"] = round(r["bytes"]["ram"] / (4 * full_dim), 4)
        r["vs_base"] = None if r["is_base"] else stats.paired_mean(r.pop("_nd"), base["ndcg"])
        r["overlap@10"] = round(_overlap(base["scores"], r.pop("_s")), 4)
        r.pop("_nd", None)
    _pareto(rows)
    rows.sort(key=lambda r: (r["status"] != "ok", -(r.get("metrics") or {}).get("ndcg@10", 0)))
    return {"dim": full_dim, "n_corpus": len(corpus), "n_queries": len(queries), "rows": rows}
