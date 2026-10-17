"""벤치마크 데이터셋 로딩과 검색(Recall/MRR/nDCG)·STS(Spearman/Pearson) 평가."""

import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
from app.services.jobs import Job
from app.services.model_manager import ModelManager, ModelSpec

K_VALUES = (1, 3, 5, 10)


# ── 데이터셋 ────────────────────────────────────────────────────────────────
class DatasetError(ValueError):
    pass


def validate_dataset(data: dict[str, Any]) -> dict[str, Any]:
    kind = data.get("type")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", str(data.get("name", ""))):
        raise DatasetError("name 은 영문/숫자/_/- 로 된 1~64자여야 합니다.")
    if kind == "retrieval":
        corpus, queries = data.get("corpus"), data.get("queries")
        if not corpus or not queries:
            raise DatasetError("retrieval 데이터셋에는 corpus 와 queries 가 필요합니다.")
        ids = {d["id"] for d in corpus}
        if len(ids) != len(corpus):
            raise DatasetError("corpus 의 id 가 중복됩니다.")
        for q in queries:
            if not q.get("text") or not q.get("relevant"):
                raise DatasetError(f"쿼리 {q.get('id')} 에 text/relevant 가 없습니다.")
            missing = set(q["relevant"]) - ids
            if missing:
                raise DatasetError(f"쿼리 {q.get('id')} 의 relevant {sorted(missing)} 가 corpus 에 없습니다.")
    elif kind == "sts":
        pairs = data.get("pairs")
        if not pairs or len(pairs) < 3:
            raise DatasetError("sts 데이터셋에는 3개 이상의 pairs(s1, s2, score) 가 필요합니다.")
        for p in pairs:
            if not {"s1", "s2", "score"} <= p.keys():
                raise DatasetError("pairs 의 각 항목에는 s1, s2, score 가 필요합니다.")
    else:
        raise DatasetError("type 은 'retrieval' 또는 'sts' 여야 합니다.")
    return data


def _dataset_files() -> dict[str, tuple[Path, bool]]:
    s = get_settings()
    files: dict[str, tuple[Path, bool]] = {}
    for builtin, folder in ((True, s.datasets_dir), (False, s.user_datasets_dir)):
        for p in sorted(folder.glob("*.json")):
            files[p.stem] = (p, builtin)
    return files


def list_datasets() -> list[dict[str, Any]]:
    out = []
    for name, (path, builtin) in _dataset_files().items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        out.append(
            {
                "name": name,
                "type": data.get("type"),
                "title": data.get("title", name),
                "description": data.get("description", ""),
                "builtin": builtin,
                "size": len(data.get("queries", data.get("pairs", []))),
                "corpus_size": len(data.get("corpus", [])),
            }
        )
    return out


def load_dataset(name: str) -> dict[str, Any]:
    entry = _dataset_files().get(name)
    if entry is None:
        raise DatasetError(f"데이터셋 '{name}' 을 찾을 수 없습니다.")
    return json.loads(entry[0].read_text(encoding="utf-8"))


def save_user_dataset(data: dict[str, Any]) -> str:
    validate_dataset(data)
    name = data["name"]
    if name in _dataset_files() and _dataset_files()[name][1]:
        raise DatasetError("내장 데이터셋과 같은 이름은 사용할 수 없습니다.")
    path = get_settings().user_datasets_dir / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return name


def delete_user_dataset(name: str) -> bool:
    entry = _dataset_files().get(name)
    if entry is None or entry[1]:
        return False
    entry[0].unlink()
    return True


def doc_text(doc: dict[str, Any]) -> str:
    title = doc.get("title")
    return f"{title}\n{doc['text']}" if title else doc["text"]


# ── 지표 ────────────────────────────────────────────────────────────────────
def retrieval_metrics(scores: np.ndarray, doc_ids: list[str], relevant: list[set[str]]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """scores: (n_queries, n_docs) 유사도 행렬."""
    order = np.argsort(-scores, axis=1)
    per_query: list[dict[str, Any]] = []
    sums: dict[str, float] = defaultdict(float)
    for qi, rel in enumerate(relevant):
        ranked = [doc_ids[j] for j in order[qi]]
        hits = [d in rel for d in ranked]
        first = next((i for i, h in enumerate(hits) if h), None)
        m: dict[str, float] = {}
        for k in K_VALUES:
            m[f"recall@{k}"] = sum(hits[:k]) / len(rel)
        m["mrr@10"] = 1.0 / (first + 1) if first is not None and first < 10 else 0.0
        dcg = sum(1.0 / math.log2(i + 2) for i, h in enumerate(hits[:10]) if h)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), 10)))
        m["ndcg@10"] = dcg / idcg if idcg else 0.0
        for k, v in m.items():
            sums[k] += v
        per_query.append(
            {
                "rank_of_first_relevant": (first + 1) if first is not None else None,
                "top": [
                    {"id": ranked[i], "score": round(float(scores[qi, order[qi][i]]), 4), "relevant": hits[i]}
                    for i in range(min(5, len(ranked)))
                ],
                **{k: round(v, 4) for k, v in m.items()},
            }
        )
    n = max(1, len(relevant))
    return {k: v / n for k, v in sums.items()}, per_query


def _rank(a: np.ndarray) -> np.ndarray:
    """동점은 평균 순위로 처리."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=np.float64)
    ranks[order] = np.arange(1, len(a) + 1)
    for v in np.unique(a):
        idx = np.where(a == v)[0]
        if len(idx) > 1:
            ranks[idx] = ranks[idx].mean()
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    xs, ys = x - x.mean(), y - y.mean()
    denom = math.sqrt(float((xs**2).sum() * (ys**2).sum()))
    return float((xs * ys).sum() / denom) if denom else 0.0


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return pearson(_rank(np.asarray(x)), _rank(np.asarray(y)))


# ── Matryoshka 차원 스윕 ────────────────────────────────────────────────────
def truncate_normalize(emb: np.ndarray, dim: int) -> np.ndarray:
    """앞쪽 dim 개 성분만 남기고 다시 L2 정규화 (sentence-transformers 의 truncate_dim 과 같은 결과)."""
    out = emb[:, :dim].astype(np.float32, copy=True)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return out / norms


def sweep_dims_for(full_dim: int, candidates: list[int] | None) -> list[int]:
    """모델 차원보다 작은 후보 차원 + 전체 차원 (내림차순)."""
    if not candidates:
        return []
    return sorted({full_dim, *(d for d in candidates if 8 <= d < full_dim)}, reverse=True)


# ── 실행 ────────────────────────────────────────────────────────────────────
def _evaluate_retrieval(manager: ModelManager, lm, data, truncate_dim, batch_size, sweep: list[int] | None = None) -> dict[str, Any]:
    corpus, queries = data["corpus"], data["queries"]
    doc_ids = [d["id"] for d in corpus]
    d = manager.encode(lm, [doc_text(x) for x in corpus], "document", truncate_dim=truncate_dim, batch_size=batch_size)
    q = manager.encode(lm, [x["text"] for x in queries], "query", truncate_dim=truncate_dim, batch_size=batch_size)
    scores = q.embeddings @ d.embeddings.T
    relevant = [set(x["relevant"]) for x in queries]
    overall, per_query = retrieval_metrics(scores, doc_ids, relevant)

    by_group: dict[str, dict[str, float]] = {}
    groups: dict[str, list[int]] = defaultdict(list)
    for i, x in enumerate(queries):
        groups[x.get("lang") or x.get("group") or "all"].append(i)
    if len(groups) > 1:
        for g, idx in groups.items():
            by_group[g] = {k: round(float(np.mean([per_query[i][k] for i in idx])), 4) for k in overall} | {"n": len(idx)}

    dim_sweep = []
    for dim in sweep_dims_for(int(d.embeddings.shape[1]), sweep):
        m, _ = retrieval_metrics(truncate_normalize(q.embeddings, dim) @ truncate_normalize(d.embeddings, dim).T, doc_ids, relevant)
        dim_sweep.append({"dim": dim, "metrics": {k: round(v, 4) for k, v in m.items()}})

    n_texts = len(corpus) + len(queries)
    enc_seconds = d.seconds + q.seconds
    return {
        "metrics": {k: round(v, 4) for k, v in overall.items()},
        "dim_sweep": dim_sweep,
        "by_group": by_group,
        "per_query": [{"id": x["id"], "text": x["text"], "lang": x.get("lang"), **pq} for x, pq in zip(queries, per_query, strict=False)],
        "dim": int(d.embeddings.shape[1]),
        "encode_seconds": round(enc_seconds, 3),
        "texts_per_second": round(n_texts / enc_seconds, 1) if enc_seconds else None,
        "applied": {"query": q.applied, "document": d.applied},
        "warnings": sorted(set(d.warnings + q.warnings)),
    }


def _evaluate_sts(manager: ModelManager, lm, data, truncate_dim, batch_size, sweep: list[int] | None = None) -> dict[str, Any]:
    pairs = data["pairs"]
    a = manager.encode(lm, [p["s1"] for p in pairs], "plain", truncate_dim=truncate_dim, batch_size=batch_size)
    b = manager.encode(lm, [p["s2"] for p in pairs], "plain", truncate_dim=truncate_dim, batch_size=batch_size)
    cos = (a.embeddings * b.embeddings).sum(axis=1)
    gold = np.array([float(p["score"]) for p in pairs])
    dim_sweep = []
    for dim in sweep_dims_for(int(a.embeddings.shape[1]), sweep):
        c = (truncate_normalize(a.embeddings, dim) * truncate_normalize(b.embeddings, dim)).sum(axis=1)
        dim_sweep.append({"dim": dim, "metrics": {"spearman": round(spearman(c, gold), 4), "pearson": round(pearson(c, gold), 4)}})
    enc_seconds = a.seconds + b.seconds
    return {
        "metrics": {"spearman": round(spearman(cos, gold), 4), "pearson": round(pearson(cos, gold), 4)},
        "dim_sweep": dim_sweep,
        "by_group": {},
        "per_pair": [
            {"s1": p["s1"], "s2": p["s2"], "gold": p["score"], "cosine": round(float(c), 4)} for p, c in zip(pairs, cos, strict=False)
        ],
        "dim": int(a.embeddings.shape[1]),
        "encode_seconds": round(enc_seconds, 3),
        "texts_per_second": round(2 * len(pairs) / enc_seconds, 1) if enc_seconds else None,
        "applied": {"plain": a.applied},
        "warnings": sorted(set(a.warnings + b.warnings)),
    }


def run_benchmark(
    job: Job,
    manager: ModelManager,
    specs: list[ModelSpec],
    dataset_name: str,
    truncate_dim: int | None = None,
    batch_size: int | None = None,
    unload_after: bool = False,
    sweep_dims: list[int] | None = None,
) -> dict[str, Any]:
    """sweep_dims 가 있으면 전체 차원으로 한 번만 인코딩한 뒤 잘라서 차원별 지표를 함께 계산한다."""
    data = validate_dataset(load_dataset(dataset_name))
    if sweep_dims:
        truncate_dim = None
    evaluate = _evaluate_retrieval if data["type"] == "retrieval" else _evaluate_sts
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for i, spec in enumerate(specs):
        job.update(i / len(specs), f"[{i + 1}/{len(specs)}] {spec.hf_id} 로드 중")
        entry: dict[str, Any] = {"model_id": spec.id, "hf_id": spec.hf_id}
        try:
            was_loaded = bool(manager.is_loaded(spec.hf_id))
            t0 = time.perf_counter()
            lm = manager.get(spec)
            entry["load_seconds"] = round(time.perf_counter() - t0, 2) if not was_loaded else 0.0
            job.update((i + 0.3) / len(specs), f"[{i + 1}/{len(specs)}] {spec.hf_id} 평가 중")
            entry |= evaluate(manager, lm, data, truncate_dim, batch_size, sweep_dims)
            entry["status"] = "ok"
            if unload_after:
                manager.unload(spec.hf_id)
        except Exception as exc:
            entry |= {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        results.append(entry)
    primary = "ndcg@10" if data["type"] == "retrieval" else "spearman"
    return {
        "dataset": {k: data.get(k) for k in ("name", "type", "title")},
        "primary_metric": primary,
        "truncate_dim": truncate_dim,
        "sweep_dims": sorted(set(sweep_dims or []), reverse=True),
        "total_seconds": round(time.perf_counter() - started, 2),
        "results": sorted(results, key=lambda r: r.get("metrics", {}).get(primary, -1), reverse=True),
    }
