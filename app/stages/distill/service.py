"""임베딩 증류: 교사(큰 임베딩 모델 또는 리랭커)의 점수 차를 학생(작은 임베딩 모델)이 따라 하도록 학습한다.

설계 이유
- 파인튜닝(5)의 학습 데이터 · 학습기 · 카탈로그 등록 · 실행 기록(FinetuneRun)을 그대로 쓰고, 다른 점은 '정답 신호'뿐이다.
  파인튜닝은 (질문, 정답 지문)만 보지만, 증류는 교사가 매긴 점수 차(정답 − 오답)까지 배운다(MarginMSE).
  점수 '차이'를 배우므로 교사와 학생의 차원이 달라도 되고 교사가 리랭커(크로스 인코더)여도 된다.
- 오답 고르기: 교사가 임베딩 모델이면 교사가 질문과 가장 가깝다고 본 '다른 문서의' 지문을 오답으로 쓴다(어려운 오답 —
  쉬운 오답은 학생도 이미 구분해 배울 것이 적다). 같은 문서의 지문은 실제로 답을 담고 있을 수 있어 뺀다.
  교사가 리랭커면 후보를 다 매기기엔 너무 느려(CPU 10개 22초) 다른 문서에서 무작위로 고른다.
- 비교: 교사 · 학생(학습 전) · 학생(학습 후)을 같은 평가 세트로 재고, 학생이 교사와의 격차를 얼마나 줄였는지와
  인코딩 속도(학생을 쓰는 이유)를 함께 본다.
"""

import random
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.core import llm, stats
from app.core.db import EmbeddingModel, EvalSet, FinetuneRun, SessionLocal
from app.core.jobs import Job, JobCancelled
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.finetune import data, trainer
from app.stages.finetune.service import SubJob, _ensure_index, output_dir, register_model
from app.stages.rag import evaluation, service


def make_triplets(
    teacher: ModelSpec, pairs: list[dict[str, Any]], seed: int = 0, job: SubJob | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(질문, 정답) 쌍 → (질문, 정답, 오답, 교사 점수 차). 정답 지문 모음에서 오답을 고른다."""
    manager = get_manager()
    rng = random.Random(seed)
    positives = [p["positive"] for p in pairs]
    docs = [p.get("document_id") for p in pairs]
    out: list[dict[str, Any]] = []
    t = time.perf_counter()
    if teacher.is_reranker:
        lm = manager.get(teacher)
        for i, p in enumerate(pairs):
            others = [j for j in range(len(pairs)) if docs[j] != docs[i]] or [j for j in range(len(pairs)) if j != i]
            j = rng.choice(others)
            sc, _ = manager.rerank(lm, p["anchor"], [p["positive"], positives[j]])
            out.append(p | {"negative": positives[j], "label": float(sc[0] - sc[1]), "negative_kind": "random"})
            if job and i % 10 == 0:
                job.update(i / len(pairs), f"교사(리랭커) 점수 {i}/{len(pairs)}")
    else:
        lm = manager.get(teacher)
        q = manager.encode(lm, [p["anchor"] for p in pairs], "query").embeddings
        d = manager.encode(lm, positives, "document").embeddings
        sim = q @ d.T
        for i, p in enumerate(pairs):
            order = np.argsort(-sim[i])
            j = next((int(k) for k in order if k != i and docs[k] != docs[i]), None)
            if j is None:  # 문서가 하나뿐이면 같은 문서라도 다른 지문을 쓴다
                j = next(int(k) for k in order if k != i)
            out.append(p | {"negative": positives[j], "label": float(sim[i, i] - sim[i, j]), "negative_kind": "hard"})
    labels = [o["label"] for o in out]
    info = {
        "teacher": teacher.hf_id, "teacher_kind": "reranker" if teacher.is_reranker else "embedding", "triplets": len(out),
        "label_mean": round(float(np.mean(labels)), 4) if labels else None,
        # 교사가 오답을 정답보다 높게 본 묶음 비율 — 높으면 질문 생성이 나빴거나 오답이 실제로 답을 담고 있을 수 있다
        "teacher_disagrees": round(float(np.mean([v < 0 for v in labels])), 3) if labels else None,
        "seconds": round(time.perf_counter() - t, 1),
    }  # fmt: skip
    return out, info


def encode_speed(spec: ModelSpec, texts: list[str]) -> float | None:
    """초당 인코딩 글 수 — 학생을 쓰는 이유(속도)를 같은 글로 잰다. 리랭커는 인코딩이 없어 None."""
    if spec.is_reranker or not texts:
        return None
    manager = get_manager()
    lm = manager.get(spec)
    r = manager.encode(lm, texts, "document")
    return round(len(texts) / r.seconds, 1) if r.seconds else None


def compare(job: Job, db, run: FinetuneRun, teacher_id: int, before_id: int, after_id: int, sample: list[str]) -> dict[str, Any]:
    cfg = run.config
    es = db.get(EvalSet, cfg["eval_set_id"])
    if es is None or not es.items:
        return {"skipped": "평가 세트가 없습니다."}
    cs_id = cfg.get("eval_chunk_set_id") or cfg["chunk_set_id"]
    teacher = db.get(EmbeddingModel, teacher_id)
    configs = []
    if teacher.kind == "embedding":
        configs.append(
            {"label": "교사", "index_id": _ensure_index(job, db, cs_id, teacher_id, 0.70, 0.76, "교사"), "mode": "dense", "top_k": 10}
        )
    before_idx = _ensure_index(job, db, cs_id, before_id, 0.76, 0.82, "학생(학습 전)")
    configs.append({"label": "학생 · 학습 전", "index_id": before_idx, "mode": "dense", "top_k": 10})
    if teacher.kind == "reranker":  # 리랭커 교사는 '학생 검색 + 리랭커'를 교사 성능으로 본다
        configs.append({"label": "교사", "index_id": before_idx, "mode": "dense", "top_k": 10, "reranker_id": teacher_id, "rerank_top": 20})
    configs.append(
        {
            "label": "학생 · 학습 후",
            "index_id": _ensure_index(job, db, cs_id, after_id, 0.82, 0.88, "학생(학습 후)"),
            "mode": "dense",
            "top_k": 10,
        }
    )
    # 모델끼리만 비교하므로 연결 계층(검색 향상 등)을 거치지 않고 검색 엔진을 직접 부른다
    res = evaluation.run_eval(lambda q, c: service.search(db, q, c), list(es.items), configs, SubJob(job, 0.88, 0.96, "비교 평가 · "))
    labels = [e["label"] for e in res["results"] if e["status"] == "ok"]
    per = {lab: [evaluation.query_metrics({"rank": q["ranks"][li], "doc_rank": None, "doc_recall@5": 0})[evaluation.PRIMARY] for q in res["queries"]]
           for li, lab in enumerate(labels)}  # fmt: skip
    by = {e["label"]: e for e in res["results"] if e["status"] == "ok"}
    out: dict[str, Any] = {"eval_set": {"id": es.id, "name": es.name, "n": len(es.items)}, "primary": evaluation.PRIMARY,
                           "models": {k: {"metrics": v["metrics"], "ci": v["ci"]} for k, v in by.items()}}  # fmt: skip
    if "학생 · 학습 전" in per and "학생 · 학습 후" in per:
        out["after_vs_before"] = stats.paired_mean(per["학생 · 학습 후"], per["학생 · 학습 전"])
    if "교사" in per and "학생 · 학습 후" in per:
        out["after_vs_teacher"] = stats.paired_mean(per["학생 · 학습 후"], per["교사"])
        # 격차 회복률: (학습 후 − 학습 전) / (교사 − 학습 전). 교사와 학생의 차이가 거의 없으면 의미가 없어 None.
        t, b, a = (by[k]["metrics"][evaluation.PRIMARY] for k in ("교사", "학생 · 학습 전", "학생 · 학습 후"))
        out["gap_closed"] = round((a - b) / (t - b), 3) if abs(t - b) > 0.01 else None
    job.update(0.96, "인코딩 속도 측정")
    speed = {"학생 · 학습 후": encode_speed(ModelSpec.from_row(db.get(EmbeddingModel, after_id)), sample)}
    if teacher.kind == "embedding":
        speed["교사"] = encode_speed(ModelSpec.from_row(teacher), sample)
    out["texts_per_second"] = speed
    return out


def run(job: Job, run_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        r = db.get(FinetuneRun, run_id)
        cfg = r.config
        r.status = "running"
        db.commit()
        try:
            student = db.get(EmbeddingModel, r.base_model_id)
            teacher = db.get(EmbeddingModel, cfg["teacher_model_id"])
            evidences: list[str] = []
            for sid in cfg.get("exclude_eval_set_ids") or []:
                es = db.get(EvalSet, sid)
                if es:
                    evidences += [it.get("evidence") or "" for it in es.items]
            llm_cfg = llm.resolve(cfg.get("provider"), cfg.get("llm_model")) if cfg["data_method"] == "llm" else None
            job.update(0.01, "학습 질문 만드는 중")
            pairs, dstats = data.build_pairs(
                db, cfg["chunk_set_id"], cfg["data_method"], cfg["n_passages"], evidences, llm_cfg, cfg.get("styles"),
                cfg.get("min_chars", 200), cfg.get("seed", 0), SubJob(job, 0.0, 0.2, "데이터 · ") if llm_cfg else None, cfg.get("concurrency", 1),
            )  # fmt: skip
            if len(pairs) < 8:
                raise ValueError(f"학습 쌍이 {len(pairs)}개뿐입니다. 지문 수를 늘리거나 최소 길이를 낮추세요.")
            triplets, tinfo = make_triplets(ModelSpec.from_row(teacher), pairs, cfg.get("seed", 0), SubJob(job, 0.2, 0.32, "교사 · "))
            r.data_stats = dstats | {"distill": tinfo, "examples": [{k: t[k] for k in ("anchor", "label")} | {"positive": t["positive"][:160], "negative": t["negative"][:160]}
                                                                    for t in triplets[:5]]}  # fmt: skip
            db.commit()
            out = output_dir(r.id)
            out.mkdir(parents=True, exist_ok=True)
            get_manager().unload_all()  # 학습 메모리 확보 (교사도 내린다)
            log: list[dict[str, Any]] = []
            try:
                info = trainer.train(
                    SubJob(job, 0.32, 0.68, ""), ModelSpec.from_row(student), triplets, out, cfg | {"loss": "margin_mse"}, log
                )
            finally:
                r.log = log
                db.commit()
            new = register_model(db, student, r, out, info)
            new.name = f"{student.name} · 증류 #{r.id} (교사 {teacher.name})"
            new.tags = sorted(set((new.tags or []) + ["증류"]) - {"파인튜닝"})
            r.output_model_id = new.id
            r.metrics = {"train": info}
            db.commit()
            if cfg.get("eval_set_id"):
                sample = [t["positive"] for t in triplets[:64]]
                r.metrics = r.metrics | {"comparison": compare(job, db, r, teacher.id, student.id, new.id, sample)}
                db.commit()
            r.status, r.finished_at = "done", datetime.now(UTC)
            db.commit()
            return {"run_id": r.id, "output_model_id": new.id, "metrics": r.metrics}
        except JobCancelled:
            r.status, r.finished_at = "cancelled", datetime.now(UTC)
            db.commit()
            raise
        except Exception as exc:
            r.status, r.error, r.finished_at = "error", f"{type(exc).__name__}: {exc}", datetime.now(UTC)
            db.commit()
            raise
