"""모델 호환성 점검: 내려받은 모델이 지금 설치된 라이브러리에서 제대로 도는지 짧게 확인한다.

왜: sentence-transformers · transformers · torch 를 올리면 trust_remote_code 모델의 코드가 깨지거나, 프롬프트 이름이 바뀌거나,
dtype 기본값이 달라져 NaN 이 나오는 일이 있다(EmbeddingGemma + fp16). 벤치마크를 몇 시간 돌린 뒤에야 알면 늦으므로,
업그레이드 직후 · 원할 때 모델마다 몇 문장만 넣어 본다.

확인 항목(모델마다)
- 로드: 예외 없이 올라오는가, 걸린 시간
- 차원: 실제 출력 차원이 카탈로그(dim)와 같은가
- 수치: NaN · inf 가 없는가, 정규화 후 길이가 1 인가
- 프롬프트: 카탈로그의 query_prompt / document_prompt 가 모델에 정의돼 있는가(없으면 조용히 무시되어 점수가 떨어진다)
- 상식: 관련 있는 쌍이 무관한 쌍보다 가까운가(한국어 · 영어) — 리랭커는 관련 쌍 점수가 더 높은가
"""

import math
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import numpy as np

from app.stages.embedding.model_manager import ModelSpec, get_manager

# (질의, 관련 문서, 무관한 문서) — 모델이 바뀌어도 답이 분명한 쉬운 쌍만 쓴다(점수 자체가 아니라 '순서'만 본다)
PROBES = [
    ("세탁기 배수가 안 될 때 어떻게 하나요?", "세탁기 물이 빠지지 않으면 배수 필터를 청소하세요.", "주택 임대차 계약은 2년이 기본입니다."),
    (
        "How do I reset my password?",
        "To reset your password, click 'Forgot password' on the login page.",
        "The museum opens at 9 a.m. on weekdays.",
    ),
]
LIBS = ("sentence-transformers", "transformers", "torch", "huggingface-hub")


def lib_versions() -> dict[str, str]:
    out = {}
    for name in LIBS:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "-"
    return out


def check(spec: ModelSpec, catalog_dim: int | None = None, unload_after: bool = True) -> dict[str, Any]:
    """모델 하나 점검. 실패해도 예외를 던지지 않고 결과에 담는다(여러 모델을 이어서 점검하므로)."""
    mgr = get_manager()
    was_loaded = bool(mgr.is_loaded(spec.hf_id))
    issues: list[str] = []
    out: dict[str, Any] = {"model_id": spec.id, "hf_id": spec.hf_id, "kind": spec.kind}
    started = time.perf_counter()
    try:
        lm = mgr.get(spec)
    except Exception as exc:  # noqa: BLE001
        return out | {"ok": False, "stage": "load", "issues": [f"로드 실패: {type(exc).__name__}: {str(exc)[:300]}"],
                      "seconds": round(time.perf_counter() - started, 2)}  # fmt: skip
    out |= {"load_seconds": round(lm.load_seconds, 2), "device": lm.device, "dtype": lm.dtype}
    try:
        if spec.is_reranker:
            margins = []
            for q, pos, neg in PROBES:
                s, _ = mgr.rerank(lm, q, [pos, neg])
                if not np.isfinite(s).all():
                    issues.append("리랭커 점수에 NaN/inf")
                margins.append(float(s[0] - s[1]))
            out["margins"] = [round(m, 4) for m in margins]
            if any(m <= 0 for m in margins):
                issues.append("관련 문서 점수가 무관한 문서보다 높지 않음")
        else:
            defined = lm.prompts
            for role, name in (("query", spec.query_prompt), ("document", spec.document_prompt)):
                if name and name not in defined:
                    issues.append(f"{role}_prompt '{name}' 이 모델에 정의돼 있지 않음 (정의된 것: {', '.join(defined) or '없음'})")
            qs = mgr.encode(lm, [p[0] for p in PROBES], "query")
            ds = mgr.encode(lm, [t for p in PROBES for t in p[1:]], "document")
            out["warnings"] = sorted(set(qs.warnings + ds.warnings))
            q, d = qs.embeddings, ds.embeddings
            out["dim"] = int(q.shape[1])
            if catalog_dim and catalog_dim != q.shape[1]:
                issues.append(f"차원 불일치: 카탈로그 {catalog_dim} · 실제 {q.shape[1]}")
            if not (np.isfinite(q).all() and np.isfinite(d).all()):
                issues.append("임베딩에 NaN/inf — dtype(fp16) 또는 라이브러리 버전 문제일 수 있음")
            else:
                norms = np.linalg.norm(np.vstack([q, d]), axis=1)
                out["norm_range"] = [round(float(norms.min()), 4), round(float(norms.max()), 4)]
                if not np.allclose(norms, 1.0, atol=1e-2):
                    issues.append("정규화 후 길이가 1 이 아님")
                margins = [float(q[i] @ d[2 * i] - q[i] @ d[2 * i + 1]) for i in range(len(PROBES))]
                out["margins"] = [round(m, 4) for m in margins]
                if any(not math.isfinite(m) or m <= 0 for m in margins):
                    issues.append("관련 문서가 무관한 문서보다 가깝지 않음 (프롬프트 · 풀링 설정 확인)")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"인코딩 실패: {type(exc).__name__}: {str(exc)[:300]}")
    finally:
        if unload_after and not was_loaded:  # 점검하려고 올린 모델은 내린다(여러 모델을 돌면 RAM 이 넘친다)
            mgr.unload(spec.hf_id)
    return out | {"ok": not issues, "issues": issues, "seconds": round(time.perf_counter() - started, 2)}


def run_all(job: Any, model_ids: list[int] | None = None, reason: str = "manual") -> dict[str, Any]:
    """여러 모델 점검 + 실행 이력(kind=compat)에 기록. model_ids 가 없으면 내려받아 둔 모델 전부(내려받기는 하지 않는다)."""
    from sqlalchemy import select

    from app.core import crud
    from app.core.db import EmbeddingModel, SessionLocal
    from app.stages.embedding import hub

    with SessionLocal() as db:
        q = select(EmbeddingModel).order_by(EmbeddingModel.id)
        rows = list(db.scalars(q.where(EmbeddingModel.id.in_(model_ids)) if model_ids else q))
        cached = hub.cache_status(force=True)
        if not model_ids:
            rows = [r for r in rows if r.hf_id in cached]  # 점검 때문에 수 GB 를 내려받지 않게
        targets = [(ModelSpec.from_row(r), r.dim) for r in rows]
    started = time.perf_counter()
    results = []
    for i, (spec, dim) in enumerate(targets):
        job.update(i / max(1, len(targets)), f"{i + 1}/{len(targets)} {spec.hf_id}")
        results.append(check(spec, dim))
    res = {"versions": lib_versions(), "reason": reason, "n": len(results), "n_ok": sum(r["ok"] for r in results),
           "results": results, "seconds": round(time.perf_counter() - started, 2)}  # fmt: skip
    with SessionLocal() as db:
        title = f"호환성 점검 · {res['n_ok']}/{res['n']} 통과 · sentence-transformers {res['versions']['sentence-transformers']}"
        run = crud.record_run(db, "compat", [s.hf_id for s, _ in targets], title,
                              {"model_ids": model_ids, "reason": reason, "versions": res["versions"]}, res, res["seconds"] * 1000)  # fmt: skip
    return res | {"run_id": run.id}


def last_run(db: Any) -> Any:
    from sqlalchemy import select

    from app.core.db import TestRun

    return db.scalars(select(TestRun).where(TestRun.kind == "compat").order_by(TestRun.id.desc()).limit(1)).first()


def needs_check_after_upgrade(db: Any) -> bool:
    """마지막 점검 때와 라이브러리 버전이 다르면 True (처음이면 False — 설치 직후 모든 모델을 올리지 않게)."""
    last = last_run(db)
    return bool(last) and (last.params or {}).get("versions") != lib_versions()
