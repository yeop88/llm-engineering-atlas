"""의미 기반 응용 API. 무거운 작업(임베딩)은 백그라운드 작업으로 실행하고 결과는 작업 결과·이력에 남는다."""

import json
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.apps import classify, cluster, common, recommend
from app.config import BASE_DIR, get_settings
from app.db import AppModel, EmbeddingModel, SessionLocal, get_db
from app.schemas import AppItemsRequest, ClusterRequest, PredictRequest, RecommendRequest, TrainClassifierRequest, ZeroShotRequest
from app.services.jobs import Job, jobs
from app.services.model_manager import ModelSpec

router = APIRouter(prefix="/api/apps", tags=["apps"])
DB = Annotated[Session, Depends(get_db)]
PRESET_DIR = BASE_DIR / "app" / "data" / "apps"


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
