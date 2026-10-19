"""의미 기반 응용 API. 무거운 작업(임베딩)은 백그라운드 작업으로 실행하고 결과는 작업 결과·이력에 남는다."""

import json
import time
from collections import Counter
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud
from app.core.config import APP_DIR, get_settings
from app.core.db import AppModel, EmbeddingModel, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.korean import noun_phrases_many, split_sentences
from app.stages.apps import anomaly, classify, cluster, common, dedup, keywords, recommend
from app.stages.apps.schemas import (
    AnomalyRequest,
    AppItemsRequest,
    ClusterRequest,
    DedupRequest,
    KeywordsRequest,
    PlagiarismRequest,
    PredictRequest,
    RecommendRequest,
    SummaryRequest,
    TrainClassifierRequest,
    ZeroShotRequest,
)
from app.stages.embedding.model_manager import ModelSpec

router = APIRouter(prefix="/api/apps", tags=["apps"])
DB = Annotated[Session, Depends(get_db)]
PRESET_DIR = APP_DIR / "stages" / "apps" / "presets"


def submit(
    app_name: str, title: str, model_hf_ids: list[str], params: dict[str, Any], fn: Callable[[Job, Session], dict[str, Any]]
) -> dict:
    """응용 작업 공통 실행기: 별도 세션에서 실행하고 끝나면 이력(test_runs)에 기록한다."""

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as db:
            try:
                result = fn(job, db)
            except common.AppError:
                raise
            seconds = time.perf_counter() - started
            result["seconds"] = round(seconds, 2)
            summary = {k: v for k, v in result.items() if k in ("metrics", "summary", "n_items", "seconds")}
            run = crud.record_run(db, f"app_{app_name}", model_hf_ids, title, params, summary, seconds * 1000)
            result["run_id"] = run.id
        return result

    return jobs.submit(f"app_{app_name}", title, work, app=app_name).to_dict()


# ── 공통 ────────────────────────────────────────────────────────────────────
@router.get("/presets")
def presets(app: str | None = None) -> list[dict]:
    out = []
    for p in sorted(PRESET_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if app and app != data.get("app") and app not in data.get("also", []):  # 다른 기능에서도 쓸 수 있는 예시
            continue
        out.append({k: data[k] for k in ("name", "app", "title", "description") if k in data} | {"n": len(data.get("items", []))})
    return out


@router.get("/presets/{name}")
def preset(name: str) -> dict:
    p = PRESET_DIR / f"{name}.json"
    if not p.is_file() or p.parent != PRESET_DIR:
        raise HTTPException(404, "예시 데이터를 찾을 수 없습니다.")
    return json.loads(p.read_text(encoding="utf-8"))


@router.post("/items")
def items(body: AppItemsRequest, db: DB) -> dict:
    """입력 소스를 펼쳐서 보여 준다 (추천에서 좋아요할 아이템 고르기 등)."""
    try:
        its = common.resolve_source(db, body.source.model_dump())
    except common.AppError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"n": len(its), "items": [common.item_out(it) for it in its[: body.limit]]}


@router.get("/cache")
def cache_stats() -> dict:
    return common.cache.stats()


# ── 콘텐츠 추천 ─────────────────────────────────────────────────────────────
@router.post("/recommend")
def run_recommend(body: RecommendRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    if not body.liked and not body.interest.strip():
        raise HTTPException(400, "좋아요한 아이템이나 관심사 문장이 하나 이상 필요합니다.")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        vec = common.embed(spec, [it.text for it in its], "document", body.truncate_dim, job)
        interest = common.embed(spec, [body.interest], "query", body.truncate_dim)[0] if body.interest.strip() else None
        res = recommend.recommend(its, vec, body.liked, body.disliked, interest, body.top_k, body.diversity, body.negative_weight)
        return res | {"n_items": len(its), "summary": {"liked": len(body.liked), "disliked": len(body.disliked)}}

    return submit(
        "recommend",
        f"콘텐츠 추천 ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"source"}) | {"source": src.get("type")},
        fn,
    )


# ── 저장된 응용 모델 ────────────────────────────────────────────────────────
def artifact_path(model_id: int):
    return get_settings().data_dir / "app_models" / f"{model_id}.joblib"


def _app_model_out(m: AppModel) -> dict[str, Any]:
    return {
        "id": m.id, "kind": m.kind, "name": m.name, "model_id": m.model_id, "model_hf_id": m.model_hf_id, "truncate_dim": m.truncate_dim,
        "method": m.method, "labels": m.labels, "config": m.config, "metrics": m.metrics, "n_train": m.n_train, "created_at": m.created_at.isoformat(),
    }  # fmt: skip


@router.get("/models")
def list_app_models(db: DB, kind: str | None = None) -> list[dict]:
    stmt = select(AppModel).order_by(AppModel.created_at.desc())
    if kind:
        stmt = stmt.where(AppModel.kind == kind)
    return [_app_model_out(m) for m in db.scalars(stmt)]


@router.delete("/models/{app_model_id}")
def delete_app_model(app_model_id: int, db: DB) -> dict:
    m = db.get(AppModel, app_model_id)
    if m is None:
        raise HTTPException(404, "저장된 모델을 찾을 수 없습니다.")
    artifact_path(m.id).unlink(missing_ok=True)
    db.delete(m)
    db.commit()
    return {"deleted": app_model_id}


def _load_app_model(db: Session, app_model_id: int, kind: str) -> tuple[AppModel, ModelSpec]:
    m = db.get(AppModel, app_model_id)
    if m is None or m.kind != kind:
        raise HTTPException(404, "저장된 모델을 찾을 수 없습니다.")
    row = db.get(EmbeddingModel, m.model_id) if m.model_id else None
    if row is None:
        raise HTTPException(400, f"이 모델이 쓰는 임베딩 모델({m.model_hf_id})이 카탈로그에서 삭제되었습니다.")
    if not artifact_path(m.id).is_file():
        raise HTTPException(500, "모델 파일이 없습니다. 다시 학습하세요.")
    return m, ModelSpec.from_row(row)


# ── 텍스트 분류 ─────────────────────────────────────────────────────────────
@router.post("/classify/zero-shot")
def run_zero_shot(body: ZeroShotRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()
    names = [lab.name for lab in body.labels]
    if len(set(names)) != len(names):
        raise HTTPException(400, "라벨 이름이 중복됩니다.")

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        x = common.embed(spec, [it.text for it in its], "plain", body.truncate_dim, job, task="classification")
        label_texts = [f"{lab.name}: {lab.description}" if lab.description else lab.name for lab in body.labels]
        lv = common.embed(spec, label_texts, "plain", body.truncate_dim, task="classification")
        preds = classify.zero_shot(x, lv, names, body.temperature)
        out: dict[str, Any] = {
            "labels": names,
            "items": [common.item_out(it, **p) for it, p in zip(its, preds, strict=True)],
            "n_items": len(its),
        }
        gold = [it.label for it in its]
        if all(g in names for g in gold):  # 정답 라벨이 있으면 평가
            pred = [p["label"] for p in preds]
            out["metrics"] = classify.report(gold, pred, names)
            out["errors"] = classify.errors([it.text for it in its], gold, pred)
        out["summary"] = {k: out["metrics"][k] for k in ("accuracy", "macro_f1")} if "metrics" in out else {}
        return out

    return submit(
        "classify",
        f"제로샷 분류 {len(names)}종 ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        {"labels": names, "temperature": body.temperature},
        fn,
    )


@router.post("/classify/train")
def run_train_classifier(body: TrainClassifierRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        if any(not it.label for it in its):
            raise common.AppError("학습에는 모든 줄에 라벨이 필요합니다 ([라벨] 텍스트).")
        y = [it.label for it in its]
        labels = sorted(set(y))
        if len(labels) < 2:
            raise common.AppError("라벨이 2종류 이상 필요합니다.")
        x = common.embed(spec, [it.text for it in its], "plain", body.truncate_dim, job, (0.0, 0.8), task="classification")
        job.update(0.85, "교차검증 중")
        cv, pred, warning = classify.cross_validate(x, y, body.method, body.k)
        out: dict[str, Any] = {
            "labels": labels,
            "method": body.method,
            "n_items": len(its),
            "warning": warning,
            "counts": {lab: y.count(lab) for lab in labels},
        }
        if cv:
            out["metrics"] = cv
            out["errors"] = classify.errors([it.text for it in its], y, pred)
            out["summary"] = {"accuracy": cv["accuracy"], "macro_f1": cv["macro_f1"]}
        if body.save:
            clf = classify.Classifier(body.method, labels, body.k).fit(x, y)
            m = AppModel(
                kind="classifier", name=body.name or f"분류기 {'·'.join(labels)[:60]}", model_id=spec.id, model_hf_id=spec.hf_id,
                truncate_dim=body.truncate_dim, method=body.method, labels=labels, config={"k": body.k, "role": "plain", "task": "classification"},
                metrics=out.get("summary", {}), n_train=len(its),
            )  # fmt: skip
            s.add(m)
            s.commit()
            clf.save(artifact_path(m.id))
            out["saved"] = _app_model_out(m)
        return out

    return submit(
        "classify",
        f"분류기 학습 · {classify.METHODS[body.method]} ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"source"}),
        fn,
    )


@router.post("/classifiers/{app_model_id}/predict")
def predict(app_model_id: int, body: PredictRequest, db: DB) -> dict:
    """저장된 분류기로 예측 (동기). 서비스에서 바로 호출하는 용도."""
    m, spec = _load_app_model(db, app_model_id, "classifier")
    clf = classify.Classifier.load(artifact_path(m.id))
    started = time.perf_counter()
    x = common.embed(spec, body.texts, "plain", m.truncate_dim, task=m.config.get("task"))
    preds = clf.predict(x)
    return {"classifier": {"id": m.id, "name": m.name, "method": m.method}, "seconds": round(time.perf_counter() - started, 3),
            "results": [{"text": t} | p for t, p in zip(body.texts, preds, strict=True)]}  # fmt: skip


# ── 클러스터링 ──────────────────────────────────────────────────────────────
@router.post("/cluster")
def run_cluster(body: ClusterRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        x = common.embed(spec, [it.text for it in its], "plain", body.truncate_dim, job, (0.0, 0.7), task="clustering")
        job.update(0.75, "군집 수 찾는 중" if body.method != "hdbscan" and not body.k else "군집화 중")
        res = cluster.cluster(its, x, body.method, body.k, body.k_max, body.min_cluster_size)
        res["n_items"] = len(its)
        res["summary"] = {"k": res["k"], "silhouette": res["silhouette"], "noise": res["noise"]} | (
            {"ari": res["agreement"]["ari"]} if "agreement" in res else {}
        )
        return res

    return submit(
        "cluster",
        f"클러스터링 · {cluster.METHODS[body.method]} ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"source"}),
        fn,
    )


# ── 중복·표절 ───────────────────────────────────────────────────────────────
MAX_REF_SENTENCES = 20_000


@router.post("/dedup")
def run_dedup(body: DedupRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        x = common.embed(spec, [it.text for it in its], "plain", body.truncate_dim, job, (0.0, 0.85), task="similarity")
        job.update(0.9, "유사 쌍 찾는 중")
        return dedup.near_duplicates(its, x, body.threshold, body.keep)

    return submit(
        "dedup", f"중복 검사 · 임계값 {body.threshold} ({spec.hf_id.split('/')[-1]})", [spec.hf_id], body.model_dump(exclude={"source"}), fn
    )


@router.post("/plagiarism")
def run_plagiarism(body: PlagiarismRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    ref_src = body.reference.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        refs = common.resolve_source(s, ref_src)
        job.update(0.02, "문장 나누는 중")
        ref_sents = [(it, sent) for it in refs for sent in split_sentences(it.text) if len(sent) >= 8][:MAX_REF_SENTENCES]
        suspect = [sent for sent in split_sentences(body.suspect) if len(sent) >= 8]
        rv = common.embed(spec, [t for _, t in ref_sents], "plain", body.truncate_dim, job, (0.05, 0.8), task="similarity")
        sv = common.embed(spec, suspect, "plain", body.truncate_dim, job, (0.8, 0.95), task="similarity")
        res = dedup.plagiarism(suspect, sv, ref_sents, rv, body.threshold, body.copy_lex)
        return res | {"n_items": len(refs)}

    return submit(
        "plagiarism", f"표절 검사 ({spec.hf_id.split('/')[-1]})", [spec.hf_id], body.model_dump(exclude={"suspect", "reference"}), fn
    )


# ── 이상·신종 탐지 ──────────────────────────────────────────────────────────
@router.post("/anomaly")
def run_anomaly(body: AnomalyRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()
    test = [it for it in (body.test or []) if it.text.strip()]

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        texts = [it.text for it in its] + [it.text.strip() for it in test]
        x = common.embed(spec, texts, "plain", body.truncate_dim, job, (0.0, 0.8), task="classification")
        job.update(0.85, "경계 학습 중")
        xt, xs = x[: len(its)], x[len(its) :]
        if not test:
            res = anomaly.explore(its, xt, body.method, body.k, body.quantile, body.normal_label)
            return res | {"n_items": len(its)}
        det = anomaly.Detector(body.method, body.k, body.quantile, body.normal_label).fit(
            xt, [it.label for it in its], [it.text for it in its]
        )
        preds = det.predict(xs)
        out: dict[str, Any] = {"mode": "detect", "n_items": len(its), "n_test": len(test), **det.info()}
        out["items"] = [{"text": it.text.strip(), "gold": it.label.strip()} | p for it, p in zip(test, preds, strict=True)]
        counts: dict[str, int] = {}
        for p in preds:
            counts[p["verdict"]] = counts.get(p["verdict"], 0) + 1
        out["counts"] = counts
        gold = [it.label.strip() for it in test]
        if all(gold):
            out["metrics"] = anomaly.evaluate(det, gold, preds)
            known = set(det.groups)
            cat = ["정상" if g == det.normal_label else ("기존 유형" if g in known else "신종") for g in gold]
            out["hist"] = anomaly.score_hist([p["anomaly_score"] for p in preds], cat)
            out["summary"] = {k: out["metrics"][k] for k in ("accuracy", "auc", "false_alarm_rate") if k in out["metrics"]} | (
                {"novel_recall": out["metrics"]["novel"]["recall"]} if "novel" in out["metrics"] else {}
            )
        else:
            out["hist"] = anomaly.score_hist([p["anomaly_score"] for p in preds])
            out["summary"] = counts
        if body.save:
            m = AppModel(
                kind="anomaly", name=body.name or f"탐지기 {'·'.join(det.groups)[:60]}", model_id=spec.id, model_hf_id=spec.hf_id,
                truncate_dim=body.truncate_dim, method=body.method, labels=det.groups,
                config={"k": body.k, "quantile": body.quantile, "normal_label": body.normal_label, "role": "plain", "task": "classification"},
                metrics=out.get("summary", {}), n_train=len(det.train_y),
            )  # fmt: skip
            s.add(m)
            s.commit()
            det.save(artifact_path(m.id))
            out["saved"] = _app_model_out(m)
        return out

    mode = "신종 탐지" if test else "이상치 찾기"
    return submit(
        "anomaly",
        f"{mode} · {anomaly.METHODS[body.method]} ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"source", "test"}) | {"n_test": len(test)},
        fn,
    )


@router.post("/detectors/{app_model_id}/score")
def score(app_model_id: int, body: PredictRequest, db: DB) -> dict:
    """저장된 탐지기로 판정 (동기). verdict = 정상 라벨 / 알려진 유형 / 신종."""
    m, spec = _load_app_model(db, app_model_id, "anomaly")
    det = anomaly.Detector.load(artifact_path(m.id))
    started = time.perf_counter()
    x = common.embed(spec, body.texts, "plain", m.truncate_dim, task=m.config.get("task"))
    preds = det.predict(x)
    return {"detector": {"id": m.id, "name": m.name, "method": m.method, "groups": det.groups}, "seconds": round(time.perf_counter() - started, 3),
            "results": [{"text": t} | p for t, p in zip(body.texts, preds, strict=True)]}  # fmt: skip


# ── 키워드·요약 ─────────────────────────────────────────────────────────────
def _passages(text: str, size: int = 600) -> list[str]:
    """긴 문서를 문장 경계에서 size 자 안팎으로 묶는다 (문서 벡터 = 조각 벡터 평균, 모델 입력 길이 한계 대비)."""
    out, cur = [], ""
    for sent in split_sentences(text) or [text]:
        if cur and len(cur) + len(sent) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


@router.post("/keywords")
def run_keywords(body: KeywordsRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        job.update(0.02, "키워드 후보 추출 중 (형태소)")
        cands = [keywords.candidates(ph, body.min_freq) for ph in noun_phrases_many([it.text for it in its], body.max_words)]
        vocab = sorted({w for c in cands for w, _ in c})
        passages = [_passages(it.text) for it in its]
        flat = [p for ps in passages for p in ps]
        pv = common.embed(spec, flat, "document", body.truncate_dim, job, (0.05, 0.5))
        wv = common.embed(spec, vocab, "query", body.truncate_dim, job, (0.5, 0.95)) if vocab else None
        widx = {w: i for i, w in enumerate(vocab)}
        out_items, pos, tags = [], 0, Counter()
        for it, ps, c in zip(its, passages, cands, strict=True):
            doc = pv[pos : pos + len(ps)].mean(axis=0)
            pos += len(ps)
            kws = keywords.keywords(doc, c, wv[[widx[w] for w, _ in c]], body.top_n, body.diversity) if c else []
            tags.update(k["keyword"] for k in kws)
            out_items.append(common.item_out(it, keywords=kws, n_candidates=len(c)))
        return {
            "items": out_items,
            "n_items": len(its),
            "top_tags": [{"keyword": k, "docs": n} for k, n in tags.most_common(30)],
            "summary": {"vocab": len(vocab)},
        }

    return submit("keywords", f"키워드 추출 ({spec.hf_id.split('/')[-1]})", [spec.hf_id], body.model_dump(exclude={"source"}), fn)


@router.post("/summary")
def run_summary(body: SummaryRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")

    def fn(job: Job, s: Session) -> dict[str, Any]:
        sents = [x for x in split_sentences(body.text) if len(x) >= 5]
        v = common.embed(spec, sents, "plain", body.truncate_dim, job, (0.0, 0.9), task="similarity")
        res = keywords.summarize(sents, v, body.n, body.diversity, body.lead_bonus)
        return res | {"n_items": len(sents), "summary": {"coverage": res["coverage"], "compression": res["compression"]}}

    return submit(
        "summary",
        f"추출 요약 {body.n}문장 ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"text"}) | {"chars": len(body.text)},
        fn,
    )
