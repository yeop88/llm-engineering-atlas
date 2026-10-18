"""파인튜닝 실행 전체 흐름: 학습 데이터 → 학습 → 카탈로그 등록 → 학습 전후 비교 → 기록(모델 카드).

비교는 같은 청크 세트에 원래 모델과 학습한 모델의 인덱스를 만들고, 같은 평가 세트로 의미 검색을 돌려
질문별로 짝지어 본다(app.rag.evaluation.run_eval). 평가 세트의 근거 문장이 든 지문은 학습에서 뺐으므로
점수가 오르면 '시험 문제를 외워서'가 아니라 문서 분야에 적응해서 오른 것이다.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core import llm, stats
from app.core.config import get_settings
from app.core.db import EmbeddingModel, EvalSet, FinetuneRun, SessionLocal, VectorIndex
from app.core.jobs import Job, JobCancelled
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.finetune import data, trainer
from app.stages.rag import evaluation, service

COPY_FIELDS = (
    "kind", "provider", "release_date", "params", "dim", "mrl_dims", "max_seq_len", "license", "languages", "modalities", "tags",
    "query_prompt", "document_prompt", "query_prefix", "document_prefix", "query_kwargs", "document_kwargs", "trust_remote_code", "load_kwargs",
)  # fmt: skip


class SubJob:
    """하위 작업(인덱스 구축 등)의 진행률을 전체 작업의 [lo, hi] 구간으로 옮긴다. 취소도 그대로 전달."""

    def __init__(self, job: Job, lo: float, hi: float, prefix: str):
        self.job, self.lo, self.hi, self.prefix = job, lo, hi, prefix

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        p = None if progress is None else self.lo + (self.hi - self.lo) * progress
        self.job.update(p, f"{self.prefix}{message}" if message else None)


def output_dir(run_id: int) -> Path:
    return get_settings().data_dir / "finetuned" / f"ft-{run_id}"


def register_model(db, base: EmbeddingModel, run: FinetuneRun, out: Path, train_info: dict[str, Any]) -> EmbeddingModel:
    row = EmbeddingModel(hf_id=str(out.resolve()), name=f"{base.name} · 파인튜닝 #{run.id}", source="finetuned")
    for f in COPY_FIELDS:
        setattr(row, f, getattr(base, f))
    row.dim = train_info.get("dim") or base.dim
    row.notes = f"{base.hf_id} 를 '{run.name}' 데이터로 파인튜닝 (실행 #{run.id}). 학습 쌍 {train_info.get('train_pairs')}개, {run.config.get('epochs')} 에폭."
    row.tags = sorted(set((base.tags or []) + ["파인튜닝"]))
    db.add(row)
    db.flush()
    return row


def _ensure_index(job: Job, db, chunk_set_id: int, model_id: int, lo: float, hi: float, label: str) -> int:
    idx = db.scalars(
        select(VectorIndex).where(
            VectorIndex.chunk_set_id == chunk_set_id,
            VectorIndex.model_id == model_id,
            VectorIndex.truncate_dim.is_(None),
            VectorIndex.status == "ready",
        )
    ).first()
    if idx:
        return idx.id
    row = db.get(EmbeddingModel, model_id)
    idx = VectorIndex(
        chunk_set_id=chunk_set_id, model_id=model_id, model_hf_id=row.hf_id, store=get_settings().vector_store, store_collection="pending"
    )
    db.add(idx)
    db.flush()
    idx.store_collection = service.store_collection_name(idx.id)
    db.commit()
    service.build_index(SubJob(job, lo, hi, f"{label} 인덱스 · "), idx.id)
    return idx.id


def compare(job: Job, db, run: FinetuneRun, base_id: int, new_id: int) -> dict[str, Any]:
    cfg = run.config
    es = db.get(EvalSet, cfg["eval_set_id"])
    if es is None or not es.items:
        return {"skipped": "평가 세트가 없습니다."}
    cs_id = cfg.get("eval_chunk_set_id") or cfg["chunk_set_id"]
    base_idx = _ensure_index(job, db, cs_id, base_id, 0.70, 0.78, "원래 모델")
    new_idx = _ensure_index(job, db, cs_id, new_id, 0.78, 0.88, "학습한 모델")
    configs = [
        {"label": "원래 모델 · 의미", "index_id": base_idx, "mode": "dense", "top_k": 10},
        {"label": "학습한 모델 · 의미", "index_id": new_idx, "mode": "dense", "top_k": 10},
        {"label": "원래 모델 · 하이브리드", "index_id": base_idx, "mode": "hybrid", "top_k": 10},
        {"label": "학습한 모델 · 하이브리드", "index_id": new_idx, "mode": "hybrid", "top_k": 10},
    ]
    # 학습 전후 '모델'만 비교해야 하므로 연결 계층(run_search)을 거치지 않고 검색 엔진을 직접 부른다.
    # 검색 향상이 끼면 LLM 변형의 영향이 모델 차이에 섞인다.
    res = evaluation.run_eval(lambda q, c: service.search(db, q, c), list(es.items), configs, SubJob(job, 0.88, 0.97, "비교 평가 · "))
    by = {e["label"]: e for e in res["results"] if e["status"] == "ok"}

    def pair(a: str, b: str) -> dict[str, Any] | None:
        if a not in by or b not in by:
            return None
        return {
            "before": by[a]["metrics"], "after": by[b]["metrics"],
            "before_ci": by[a]["ci"], "after_ci": by[b]["ci"],
            "diff": round(by[b]["metrics"][evaluation.PRIMARY] - by[a]["metrics"][evaluation.PRIMARY], 4),
        }  # fmt: skip

    # 짝지은 비교: run_eval 의 '1위 대비'가 아니라 '학습 전 대비'로 질문별 점수를 다시 짝짓는다
    per = {e["label"]: [None] * len(res["queries"]) for e in res["results"] if e["status"] == "ok"}
    labels = [e["label"] for e in res["results"] if e["status"] == "ok"]
    for qi, q in enumerate(res["queries"]):
        for li, lab in enumerate(labels):
            r = q["ranks"][li]
            per[lab][qi] = evaluation.query_metrics({"rank": r, "doc_rank": None, "doc_recall@5": 0})[evaluation.PRIMARY]
    out: dict[str, Any] = {
        "eval_set": {"id": es.id, "name": es.name, "n": len(es.items)},
        "chunk_set_id": cs_id,
        "primary": evaluation.PRIMARY,
    }
    for mode, a, b in (
        ("dense", "원래 모델 · 의미", "학습한 모델 · 의미"),
        ("hybrid", "원래 모델 · 하이브리드", "학습한 모델 · 하이브리드"),
    ):
        p = pair(a, b)
        if p:
            p["paired"] = stats.paired_mean(per[b], per[a])
            out[mode] = p
    out["queries"] = [
        {"query": q["query"], "type": q.get("type"), "ranks": dict(zip(labels, q["ranks"], strict=True))} for q in res["queries"]
    ]
    return out


def run(job: Job, run_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        r = db.get(FinetuneRun, run_id)
        cfg = r.config
        r.status = "running"
        db.commit()
        try:
            base = db.get(EmbeddingModel, r.base_model_id)
            spec = ModelSpec.from_row(base)
            evidences: list[str] = []
            for sid in cfg.get("exclude_eval_set_ids") or []:
                es = db.get(EvalSet, sid)
                if es:
                    evidences += [e for it in es.items for e in evaluation.evidences_of(it)]  # 여러 문서 질문의 근거도 모두 누수 방지 대상
            llm_cfg = llm.resolve(cfg.get("provider"), cfg.get("llm_model")) if cfg["data_method"] == "llm" else None
            job.update(0.01, "학습 데이터 만드는 중")
            pairs, dstats = data.build_pairs(
                db, cfg["chunk_set_id"], cfg["data_method"], cfg["n_passages"], evidences, llm_cfg, cfg.get("styles"),
                cfg.get("min_chars", 200), cfg.get("seed", 0), SubJob(job, 0.0, 0.3, "데이터 · ") if llm_cfg else None, cfg.get("concurrency", 2),
            )  # fmt: skip
            if llm_cfg:
                dstats["llm"] = llm_cfg.public()
            r.data_stats = dstats
            db.commit()
            if len(pairs) < 8:
                raise ValueError(f"학습 쌍이 {len(pairs)}개뿐입니다. 지문 수를 늘리거나 최소 길이를 낮추세요.")
            out = output_dir(r.id)
            out.mkdir(parents=True, exist_ok=True)
            get_manager().unload_all()  # 학습 메모리 확보
            log: list[dict[str, Any]] = []
            try:
                info = trainer.train(SubJob(job, 0.3, 0.68, ""), spec, pairs, out, cfg, log)
            finally:
                r.log = log
                db.commit()
            new = register_model(db, base, r, out, info)
            r.output_model_id = new.id
            r.metrics = {"train": info}
            db.commit()
            if cfg.get("eval_set_id"):
                r.metrics = r.metrics | {"comparison": compare(job, db, r, base.id, new.id)}
                db.commit()
            r.status, r.finished_at = "done", datetime.now(UTC)
            db.commit()
            (out / "README.md").write_text(model_card(r, base, new), encoding="utf-8")
            return {"run_id": r.id, "output_model_id": new.id, "metrics": r.metrics}
        except JobCancelled:
            r.status, r.finished_at = "cancelled", datetime.now(UTC)
            db.commit()
            raise
        except Exception as exc:
            r.status, r.error, r.finished_at = "error", f"{type(exc).__name__}: {exc}", datetime.now(UTC)
            db.commit()
            raise


# ── 기록 (모델 카드) ────────────────────────────────────────────────────────
def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.1f}"


def model_card(r: FinetuneRun, base: EmbeddingModel | None, new: EmbeddingModel | None) -> str:
    """학습한 모델 폴더의 README.md: 무엇을 왜 어떻게 학습했고 결과가 어땠는지."""
    c, d, m = r.config, r.data_stats or {}, r.metrics or {}
    t = m.get("train", {})
    lines = [
        f"# {new.name if new else r.name}",
        "",
        f"- 원래 모델: `{r.base_hf_id}`" + (f" ({base.name})" if base else ""),
        f"- 실행: #{r.id} `{r.name}` · {r.created_at:%Y-%m-%d %H:%M} UTC · 상태 {r.status}",
        f"- 저장 위치: `{new.hf_id if new else output_dir(r.id)}`",
        "",
        "## 학습 데이터",
        "",
        f"- 방법: {'LLM 질문 생성' if c.get('data_method') == 'llm' else 'ICT (지문의 한 문장 → 나머지 지문)'}"
        + (f" · LLM `{d.get('llm', {}).get('model')}`" if d.get("llm") else ""),
        f"- 컬렉션 #{c.get('collection_id')} · 청크 세트 #{c.get('chunk_set_id')} 에서 지문 {d.get('passages')}개 → 학습 쌍 {d.get('pairs')}개 (문서 {d.get('documents')}개, 유형 {d.get('by_type')})",
        f"- 평가 세트 근거 문장이 든 지문 {d.get('excluded_for_eval', 0)}개는 학습에서 제외 (누수 방지)",
        "",
        "## 학습 설정",
        "",
        f"- 손실: {'Cached' if c.get('mini_batch_size') else ''}MultipleNegativesRankingLoss"
        + (f" + Matryoshka {c.get('matryoshka_dims')}" if c.get("matryoshka_dims") else ""),
        f"- 에폭 {c.get('epochs')} · 배치 {c.get('batch_size')} · 학습률 {c.get('learning_rate')} · 최대 길이 {t.get('max_seq_length')} · seed {c.get('seed', 0)} · 장치 {t.get('device')}",
        f"- 프롬프트: {t.get('prompts') or '없음'}",
        f"- 단계 {t.get('steps')} · 손실 {t.get('first_loss')} → {t.get('final_loss')}"
        + (f" · 검증 손실 {t.get('eval_loss')}" if t.get("eval_loss") is not None else "")
        + f" · {t.get('seconds')}초",
    ]
    cmp_ = m.get("comparison")
    if cmp_ and not cmp_.get("skipped"):
        lines += [
            "",
            f"## 학습 전후 비교 — 평가 세트 '{cmp_['eval_set']['name']}' ({cmp_['eval_set']['n']}문항)",
            "",
            "| 검색 | nDCG@10 전 → 후 | Hit@1 | Hit@5 | 차이(95% 구간) | 판정 |",
            "|---|---|---|---|---|---|",
        ]
        for mode, name in (("dense", "의미"), ("hybrid", "하이브리드")):
            p = cmp_.get(mode)
            if not p:
                continue
            pr = p["paired"]
            lines.append(
                f"| {name} | {_pct(p['before']['ndcg@10'])} → **{_pct(p['after']['ndcg@10'])}** | {_pct(p['before']['hit@1'])} → {_pct(p['after']['hit@1'])} | "
                f"{_pct(p['before']['hit@5'])} → {_pct(p['after']['hit@5'])} | {pr['diff'] * 100:+.1f}%p [{pr['ci'][0] * 100:+.1f}, {pr['ci'][1] * 100:+.1f}] | "
                f"{'유의한 차이' if pr['significant'] else '차이 불확실'} (p={pr['p']}) |"
            )
    if r.error:
        lines += ["", "## 오류", "", f"```\n{r.error}\n```"]
    lines += ["", "## 예시 학습 쌍", ""] + [
        f"- **질문** {e['anchor']}\n  - **지문** {e['positive'][:160]}…" for e in d.get("examples", [])[:3]
    ]
    return "\n".join(lines) + "\n"
