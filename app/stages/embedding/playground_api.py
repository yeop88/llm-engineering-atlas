"""실시간 테스트: 임베딩 생성, 유사도 행렬, 다중 모델 검색 비교, 이미지-텍스트 검색."""

import io
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import crud
from app.core.db import get_db
from app.core.schemas import EmbedRequest, ProjectionRequest, RetrieveRequest, SimilarityRequest
from app.stages.embedding import projection
from app.stages.embedding.model_manager import LoadedModel, ModelSpec, get_manager

router = APIRouter(prefix="/api", tags=["playground"])
DB = Annotated[Session, Depends(get_db)]


def _load(spec: ModelSpec, multimodal: bool = False) -> LoadedModel:
    try:
        return get_manager().get(spec, multimodal=multimodal)
    except Exception as exc:
        raise HTTPException(500, f"{spec.hf_id} 로드 실패: {type(exc).__name__}: {exc}") from exc


@router.post("/embed")
def embed(body: EmbedRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    lm = _load(spec)
    r = get_manager().encode(lm, body.texts, body.role, truncate_dim=body.truncate_dim, normalize=body.normalize)
    norms = np.linalg.norm(r.embeddings, axis=1)
    items = [
        {
            "text": t,
            "norm": round(float(n), 4),
            "preview": [round(float(x), 5) for x in v[: body.preview]],
            "stats": {
                "mean": round(float(v.mean()), 5),
                "std": round(float(v.std()), 5),
                "min": round(float(v.min()), 5),
                "max": round(float(v.max()), 5),
            },
        }
        for t, v, n in zip(body.texts, r.embeddings, norms, strict=False)
    ]
    result = {
        "hf_id": spec.hf_id,
        "dim": int(r.embeddings.shape[1]),
        "count": len(items),
        "seconds": round(r.seconds, 4),
        "texts_per_second": round(len(items) / r.seconds, 1) if r.seconds else None,
        "applied": r.applied,
        "warnings": r.warnings,
        "items": items,
    }
    crud.record_run(
        db,
        "embed",
        [spec.hf_id],
        body.texts[0],
        body.model_dump(exclude={"texts"}) | {"n": len(body.texts)},
        {k: result[k] for k in ("dim", "count", "seconds")},
        r.seconds * 1000,
    )
    return result


@router.post("/similarity")
def similarity(body: SimilarityRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    lm = _load(spec)
    r = get_manager().encode(lm, body.texts, body.role, truncate_dim=body.truncate_dim)
    matrix = (r.embeddings @ r.embeddings.T).round(4).tolist()
    result = {
        "hf_id": spec.hf_id,
        "dim": int(r.embeddings.shape[1]),
        "texts": body.texts,
        "matrix": matrix,
        "seconds": round(r.seconds, 4),
        "applied": r.applied,
        "warnings": r.warnings,
    }
    crud.record_run(
        db,
        "similarity",
        [spec.hf_id],
        f"{len(body.texts)}개 문장 유사도",
        {"truncate_dim": body.truncate_dim, "role": body.role},
        {"texts": body.texts, "matrix": matrix},
        r.seconds * 1000,
    )
    return result


@router.post("/retrieve")
def retrieve(body: RetrieveRequest, db: DB) -> dict:
    manager = get_manager()
    outputs: list[dict[str, Any]] = []
    for spec in crud.get_specs(db, body.model_ids, "embedding"):
        try:
            lm = _load(spec)
            d = manager.encode(lm, body.documents, "document", truncate_dim=body.truncate_dim)
            q = manager.encode(lm, [body.query], "query", truncate_dim=body.truncate_dim)
        except HTTPException as exc:
            outputs.append({"hf_id": spec.hf_id, "error": exc.detail})
            continue
        except Exception as exc:
            outputs.append({"hf_id": spec.hf_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        scores = (q.embeddings @ d.embeddings.T)[0]
        order = np.argsort(-scores)[: body.top_k]
        outputs.append(
            {
                "hf_id": spec.hf_id,
                "dim": int(d.embeddings.shape[1]),
                "seconds": round(d.seconds + q.seconds, 4),
                "applied": {"query": q.applied, "document": d.applied},
                "warnings": sorted(set(q.warnings + d.warnings)),
                "ranking": [{"index": int(i), "score": round(float(scores[i]), 4), "text": body.documents[i]} for i in order],
            }
        )
    total = sum(o.get("seconds", 0) for o in outputs)
    crud.record_run(
        db, "retrieval", [o["hf_id"] for o in outputs], body.query,
        {"top_k": body.top_k, "truncate_dim": body.truncate_dim, "n_docs": len(body.documents)},
        {"top1": {o["hf_id"]: o["ranking"][0]["index"] for o in outputs if "ranking" in o}}, total * 1000,
    )  # fmt: skip
    return {"query": body.query, "results": outputs}


@router.post("/projection")
def project(body: ProjectionRequest, db: DB) -> dict:
    """모델별로 임베딩을 2D 로 투영. 축 값은 의미가 없고 점 사이 거리/군집만 비교한다."""
    if body.method == "tsne" and len(body.items) < 10:
        raise HTTPException(400, "t-SNE 는 문장이 10개 이상일 때 사용할 수 있습니다. PCA 를 사용하세요.")
    texts = [it.text for it in body.items]
    groups = [it.group or "기본" for it in body.items]
    manager = get_manager()
    outputs: list[dict[str, Any]] = []
    for spec in crud.get_specs(db, body.model_ids, "embedding"):
        try:
            lm = _load(spec)
            r = manager.encode(lm, texts, body.role)
        except HTTPException as exc:
            outputs.append({"hf_id": spec.hf_id, "error": exc.detail})
            continue
        if body.method == "pca":
            coords, explained = projection.pca_2d(r.embeddings)
        else:
            coords, explained = projection.tsne_2d(r.embeddings), None
        outputs.append(
            {
                "hf_id": spec.hf_id,
                "dim": int(r.embeddings.shape[1]),
                "seconds": round(r.seconds, 4),
                "explained_variance": round(explained, 4) if explained is not None else None,
                "points": [[round(float(x), 4), round(float(y), 4)] for x, y in coords],
                "alignment": projection.pair_alignment(r.embeddings, groups) if body.pair_groups else None,
                "applied": r.applied,
                "warnings": r.warnings,
            }
        )
    result = {"method": body.method, "texts": texts, "groups": groups, "results": outputs}
    summary = {o["hf_id"]: o["alignment"]["margin"] for o in outputs if o.get("alignment")}
    crud.record_run(
        db, "projection", [o["hf_id"] for o in outputs], f"임베딩 지도 ({body.method.upper()}, {len(texts)}개 문장)",
        {"method": body.method, "role": body.role, "n": len(texts)}, {"alignment_margin": summary}, sum(o.get("seconds", 0) for o in outputs) * 1000,
    )  # fmt: skip
    return result


def _encode_images(lm: LoadedModel, images: list[Image.Image]) -> tuple[np.ndarray, float]:
    # 인코딩 자체는 RAG 이미지 색인과 같은 ModelManager.encode_images 를 쓴다(입력 형식 판별 로직을 한 곳에만 두려고).
    try:
        r = get_manager().encode_images(lm, images)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return r.embeddings, r.seconds


@router.post("/multimodal/retrieve")
async def multimodal_retrieve(
    db: DB,
    model_ids: Annotated[str, Form(description="쉼표로 구분한 모델 id")],
    query: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File(description="검색 대상 이미지")],
) -> dict:
    ids = [int(x) for x in model_ids.split(",") if x.strip()]
    if not files:
        raise HTTPException(400, "이미지를 1장 이상 올려주세요.")
    images: list[Image.Image] = []
    names: list[str] = []
    for f in files[:64]:
        try:
            images.append(Image.open(io.BytesIO(await f.read())).convert("RGB"))
            names.append(f.filename or f"image{len(names)}")
        except Exception as exc:
            raise HTTPException(400, f"{f.filename}: 이미지를 열 수 없습니다 ({exc})") from exc

    def work() -> list[dict[str, Any]]:
        manager = get_manager()
        out = []
        for spec in crud.get_specs(db, ids, "embedding"):
            if not spec.is_multimodal:
                out.append({"hf_id": spec.hf_id, "error": "텍스트 전용 모델입니다 (modalities 에 image 가 없음)."})
                continue
            try:
                lm = _load(spec, multimodal=True)
                img_emb, img_s = _encode_images(lm, images)
                q = manager.encode(lm, [query], "query")
            except HTTPException as exc:
                out.append({"hf_id": spec.hf_id, "error": exc.detail})
                continue
            scores = (q.embeddings @ img_emb.T)[0]
            order = np.argsort(-scores)
            out.append(
                {
                    "hf_id": spec.hf_id,
                    "seconds": round(img_s + q.seconds, 4),
                    "applied": {"query": q.applied},
                    "warnings": q.warnings,
                    "ranking": [{"index": int(i), "name": names[i], "score": round(float(scores[i]), 4)} for i in order],
                }
            )
        return out

    outputs = await run_in_threadpool(work)
    crud.record_run(
        db,
        "multimodal",
        [o["hf_id"] for o in outputs],
        query,
        {"n_images": len(images)},
        {"top1": {o["hf_id"]: o["ranking"][0]["name"] for o in outputs if "ranking" in o}},
        sum(o.get("seconds", 0) for o in outputs) * 1000,
    )
    return {"query": query, "results": outputs}
