"""ED1 기기별 모델 선택 · ED2 극단 경량화 조합: 기기 프로필(쓸 수 있는 메모리 · 가속기) → 임베딩 × 벡터 정밀도 × LLM 조합 추천.

후보는 새로 재지 않고 이미 잰 실측에서 모은다 — 벡터 양자화 비교(quant_vectors: 가중치 × 차원 × 정밀도별 recall · 바이트)와
LLM 양자화 비교(quant_llm: 모델별 품질 · 속도), GGUF 파일 크기. 기기에서 새로 재는 것이 아니라서 메모리는 '추정'으로 표시한다:
임베딩 = 파라미터 × 가중치 바이트, 색인 = 청크 수 × 벡터 바이트(실측 표의 bytes.ram), LLM = 파일 크기 + 맥락(KV) 추정.

손실은 압축마다 따로 쟀으므로 조합의 손실은 더해서 추정한다(실측에서 압축은 겹치면 손실이 누적됐다 — quant 실측). 그래서 조합 점수는
'검색 recall × 답변 품질'로 두 손실이 함께 깎이게 하고, 같은 메모리에서 점수가 더 높은 조합이 없는 것만 파레토 앞줄로 표시한다.
"""

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import EmbeddingModel, TestRun

# 기기가 앱에 내줄 수 있는 메모리(budget_gb)는 전체 RAM 보다 훨씬 작다 — OS · 다른 앱 · 화면이 나머지를 쓴다.
# 수치는 흔한 기기 등급의 보수적 가정이며 화면에서 바꿀 수 있다.
PROFILES: dict[str, dict[str, Any]] = {
    "phone": {"label": "스마트폰 (RAM 8GB · NPU)", "ram_gb": 8, "budget_gb": 2.5, "disk_gb": 4, "accel": "npu", "vision": False},
    "tablet": {"label": "현장 태블릿 (RAM 12GB · 모바일 GPU)", "ram_gb": 12, "budget_gb": 5, "disk_gb": 16, "accel": "gpu", "vision": True},
    "kiosk": {"label": "매장 키오스크 (CPU 전용 · RAM 16GB)", "ram_gb": 16, "budget_gb": 8, "disk_gb": 64, "accel": "cpu", "vision": False},
    "laptop": {
        "label": "내장 GPU 노트북 (이 PC 급 · RAM 32GB)",
        "ram_gb": 32,
        "budget_gb": 14,
        "disk_gb": 128,
        "accel": "igpu",
        "vision": True,
    },
}
WEIGHT_BYTES = {"w_fp32": 4.0, "w_fp16": 2.0, "w_bf16": 2.0, "w_int8": 1.0}
KV_GB_PER_1K = 0.06  # 4B 급 · GQA 모델의 맥락 1K 토큰당 KV 캐시(f16) 대략값 — 서빙 실측(S5)의 KV 로그로 고칠 값


def params_b(text: str) -> float | None:
    """카탈로그 파라미터 문자열('308M', '740M (텍스트 270M)', '1.1B') → 십억 단위. 괄호 안 '텍스트'가 있으면 글 모델 크기를 쓴다."""
    m = re.search(r"텍스트\s*([\d.]+)\s*([MB])", text or "") or re.search(r"([\d.]+)\s*([MB])", text or "")
    if not m:
        return None
    return float(m.group(1)) / (1000 if m.group(2) == "M" else 1)


def vector_candidates(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    """최근 벡터 양자화 실측의 (모델 × 가중치 × 차원 × 정밀도) 행. 같은 조합은 최신 실행만."""
    params = {r.hf_id: params_b(r.params) for r in db.scalars(select(EmbeddingModel))}
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for r in db.scalars(select(TestRun).where(TestRun.kind == "quant_vectors").order_by(TestRun.id.desc()).limit(limit)):
        for m in (r.result or {}).get("results") or []:
            if m.get("status") != "ok":
                continue
            base = next((x for x in m["rows"] if x.get("is_base")), None)
            for x in m["rows"]:
                key = (m["hf_id"], x["weight"], x["dim"], x["precision"])
                if x.get("status") != "ok" or key in seen:
                    continue
                seen.add(key)
                p = params.get(m["hf_id"])
                out.append({"hf_id": m["hf_id"], "weight": x["weight"], "dim": x["dim"], "precision": x["precision"], "label": x.get("label"),
                            "recall": x["metrics"].get("recall@10"), "base_recall": (base or x)["metrics"].get("recall@10"),
                            "bytes_per_vector": x["bytes"]["ram"], "disk_per_vector": x["bytes"]["disk"],
                            "model_gb": round(p * WEIGHT_BYTES.get(x["weight"], 4.0), 2) if p else None,
                            "source": f"quant_vectors #{r.id}"})  # fmt: skip
    return out


def _quant_tag(name: str) -> str:
    m = re.search(r"(q\d(?:_k)?(?:_[a-z0-9]+)?)", name.lower())
    return m.group(1) if m else ""


def match_file(alias: str, files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """실측 기록의 모델 별칭('gemma-4-e4b-q8') → GGUF 파일. 별칭 낱말이 모두 파일 이름에 있고, 비트 표시가 없으면 Q4(서버 기본)로 본다."""
    toks = [t for t in alias.lower().split("-") if t and not re.fullmatch(r"q\d+", t)]
    bits = next((t for t in alias.lower().split("-") if re.fullmatch(r"q\d+", t)), "q4")
    hits = [f for f in files if all(t in f["name"].lower() for t in toks)]
    return next((f for f in hits if _quant_tag(f["name"]).startswith(bits)), None)


def llm_candidates(db: Session, files: list[dict[str, Any]], ctx: int, limit: int = 40) -> list[dict[str, Any]]:
    """GGUF 파일마다 메모리 추정 + (있으면) LLM 양자화 실측의 품질 · 지연.

    품질은 같은 평가 세트끼리만 비교할 수 있다 — 세트마다 파일별 최신 실측을 모은 뒤, 가장 많은 파일을 잰 세트(같으면 최근 세트)
    하나만 쓴다. 파일마다 '가장 최근 실측'을 따로 고르면 세트가 섞여(법률 세트 0.67 vs 24문항 세트 0.83) 순서가 뒤집힌다."""
    by_set: dict[str, dict[str, dict[str, Any]]] = {}
    order: list[str] = []
    for r in db.scalars(select(TestRun).where(TestRun.kind == "quant_llm").order_by(TestRun.id.desc()).limit(limit)):
        es = str(((r.result or {}).get("eval_set") or {}).get("name"))
        if es not in by_set:
            by_set[es] = {}
            order.append(es)
        for m in (r.result or {}).get("results") or []:
            f = match_file(m.get("model", ""), files) if m.get("status") == "ok" else None
            if f and f["name"] not in by_set[es]:
                by_set[es][f["name"]] = {
                    "quality": m.get("quality"),
                    "mean_seconds": m.get("mean_seconds"),
                    "eval_set": es,
                    "source": f"quant_llm #{r.id}",
                }
    best = max(order, key=lambda s: (len(by_set[s]), -order.index(s)), default=None)
    measured = by_set.get(best, {}) if best else {}
    return [
        f | {"ram_gb": round(f["gb"] + KV_GB_PER_1K * ctx / 1024, 2), "quant": _quant_tag(f["name"]) or "?"} | measured.get(f["name"], {})
        for f in files
    ]


def recommend(
    profile: dict[str, Any], vecs: list[dict[str, Any]], llms: list[dict[str, Any]], n_chunks: int, top: int = 12
) -> dict[str, Any]:
    """예산 안의 조합을 '검색 recall × 답변 품질' 순으로. LLM 없이 검색만 하는 조합도 후보 — 작은 기기는 근거만 보여 주는 것이 답일 수 있다."""
    budget = float(profile["budget_gb"])
    best_q = max((x["quality"] for x in llms if x.get("quality") is not None), default=None)
    rows: list[dict[str, Any]] = []
    for v in vecs:
        if v["model_gb"] is None or v["recall"] is None:
            continue
        index_gb = n_chunks * v["bytes_per_vector"] / 2**30
        disk_gb = n_chunks * v["disk_per_vector"] / 2**30
        for lm in [None, *llms]:
            q = lm.get("quality") if lm else None
            total = v["model_gb"] + index_gb + (lm["ram_gb"] if lm else 0)
            # 품질을 모르는 LLM 은 점수를 매기지 않는다(추측하지 않음) — 표에는 남겨 '재야 할 후보'로 보인다
            score = v["recall"] * (q if q is not None else (1.0 if lm is None else 0.0))
            over = [f"메모리 {total:.2f}GB > {budget}GB"] if total > budget else []
            if lm and lm["gb"] + disk_gb + v["model_gb"] > profile["disk_gb"]:
                over.append("저장 공간 초과")
            rows.append({"embedding": v["hf_id"], "weight": v["weight"], "dim": v["dim"], "precision": v["precision"], "llm": lm["name"] if lm else None,
                         "llm_quant": lm["quant"] if lm else None, "ram_gb": round(total, 2), "index_mb": round(index_gb * 1024, 1),
                         "recall": v["recall"], "quality": q, "eval_set": lm.get("eval_set") if lm else None, "score": round(score, 4) if (lm is None or q is not None) else None,
                         "loss": {"retrieval": round(v["base_recall"] - v["recall"], 4),
                                  "answer": round(best_q - q, 4) if (best_q is not None and q is not None) else None},
                         "fits": not over, "over": over, "sources": [v["source"]] + ([lm["source"]] if lm and lm.get("source") else [])})  # fmt: skip
    fits = [r for r in rows if r["fits"]]
    _pareto(fits)
    with_llm = sorted((r for r in fits if r["llm"]), key=lambda r: (r["score"] is None, -(r["score"] or 0), r["ram_gb"]))
    search_only = sorted((r for r in fits if not r["llm"]), key=lambda r: (-r["recall"], r["ram_gb"]))
    nearest = sorted((r for r in rows if not r["fits"] and r["llm"]), key=lambda r: r["ram_gb"])[:3]
    return {"profile": profile, "n_chunks": n_chunks, "with_llm": with_llm[:top], "search_only": search_only[:top // 2],
            "nearest": nearest if not with_llm else [], "n_candidates": len(rows), "n_fit": len(fits)}  # fmt: skip


def _pareto(rows: list[dict[str, Any]]) -> None:
    """메모리를 늘리지 않고는 점수를 올릴 수 없는 조합만 앞줄."""
    scored = sorted((r for r in rows if r["score"] is not None), key=lambda r: (r["ram_gb"], -r["score"]))
    best = -1.0
    for r in scored:
        r["pareto"] = r["score"] > best
        best = max(best, r["score"])


def gguf_files(d: Path | None) -> list[dict[str, Any]]:
    """답변용 GGUF 파일(비전 투영 · 추측 디코딩 보조 제외). 같은 폴더에 mmproj 가 있으면 사진을 볼 수 있는 모델로 표시."""
    if not d or not d.is_dir():
        return []
    mm = [f.name.lower() for f in d.glob("*.gguf") if "mmproj" in f.name.lower()]
    files = [f for f in sorted(d.glob("*.gguf")) if not f.name.lower().startswith(("mmproj", "mtp")) and "mmproj" not in f.name.lower()]
    return [{"name": f.name, "path": str(f), "gb": round(f.stat().st_size / 2**30, 2),
             "vision": any(f.name.lower().split("_")[0].split("-it")[0] in m for m in mm)} for f in files]  # fmt: skip
