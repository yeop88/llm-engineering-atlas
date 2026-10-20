"""E6 드리프트 · 이상 감지: 들어오는 질문의 분포 · 검색 확신도 · 거절률이 기준 기간과 달라지면 알린다.

평가 세트는 만든 시점의 질문만 담는다. 새 제품 · 새 법령이 나오면 세트에 없는 질문이 늘어 품질이 떨어지는데 평가 세트로는 안 보인다.
신호 세 가지:
1. 새로운 질문 비율 — 최근 질문마다 기준 질문 중 가장 가까운 것과의 의미 유사도(질문 임베딩)가 기준값보다 낮으면 '새로운 질문'.
   기준 기간 자체의 비율(자기 자신을 뺀 가장 가까운 것)과 비교한다 — 원래 다양한 질문이 들어오는 서비스를 경보로 착각하지 않게.
2. 검색 확신도(1 · 2위 점수 차) · 1위 점수 평균의 변화 — 자료가 낡거나 질문 모양이 바뀌면 떨어진다.
3. 거절률 변화 — '근거에서 찾을 수 없습니다'가 늘면 자료에 없는 질문이 늘었다는 뜻.
새로운 질문은 서로 비슷한 것끼리 묶어 평가 세트 후보로 보낸다(드리프트를 평가 세트가 따라가게).
"""

from typing import Any

import numpy as np

from app.core import stats
from app.stages.apps import common as apps_common
from app.stages.embedding.model_manager import ModelSpec

NOVEL_SIM = 0.6  # 가장 가까운 기준 질문과 이보다 낮으면 '새로운 질문' (KURE 기준 잠정값, 실측 문서 참고)
GROUP_SIM = 0.72  # 새로운 질문끼리 이 이상이면 한 묶음


def _nearest(a: np.ndarray, b: np.ndarray, self_exclude: bool = False) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros(len(a))
    sim = a @ b.T
    if self_exclude:
        np.fill_diagonal(sim, -1.0)
    return sim.max(axis=1)


def unpaired(a: list[float], b: list[float], n_boot: int = 1000, seed: int = 0) -> dict[str, Any]:
    """두 기간 평균 차이(b − a)의 부트스트랩 95% 구간 — 기간이 달라 짝지을 수 없다."""
    if len(a) < 2 or len(b) < 2:
        return {"diff": round(float(np.mean(b) - np.mean(a)) if a and b else 0.0, 4), "ci": [0.0, 0.0], "significant": False}
    rng = np.random.default_rng(seed)
    aa, bb = np.asarray(a, float), np.asarray(b, float)
    diffs = rng.choice(bb, (n_boot, len(bb))).mean(1) - rng.choice(aa, (n_boot, len(aa))).mean(1)
    lo, hi = float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))
    return {"diff": round(float(bb.mean() - aa.mean()), 4), "ci": [round(lo, 4), round(hi, 4)], "significant": bool(lo > 0 or hi < 0)}


def groups(texts: list[str], vecs: np.ndarray, sim: float = GROUP_SIM) -> list[dict[str, Any]]:
    """욕심쟁이 묶기: 앞에서부터 대표 질문을 정하고 그와 비슷한 것을 모은다(군집 수를 정하지 않아도 되게)."""
    left = list(range(len(texts)))
    out = []
    while left:
        i = left.pop(0)
        members = [i] + [j for j in left if float(vecs[i] @ vecs[j]) >= sim]
        left = [j for j in left if j not in members]
        out.append({"representative": texts[i], "n": len(members), "examples": [texts[j] for j in members[:5]]})
    return sorted(out, key=lambda g: -g["n"])


def analyze(spec: ModelSpec, base_q: list[str], recent_q: list[str], base_sig: list[dict[str, Any]] | None = None,
            recent_sig: list[dict[str, Any]] | None = None, novel_sim: float = NOVEL_SIM, job: Any = None) -> dict[str, Any]:  # fmt: skip
    if len(base_q) < 3 or len(recent_q) < 3:
        raise ValueError(f"질문이 너무 적습니다(기준 {len(base_q)}개 · 최근 {len(recent_q)}개, 각각 3개 이상 필요).")
    eb = apps_common.embed(spec, base_q, "query", job=job, progress=(0.0, 0.45))
    er = apps_common.embed(spec, recent_q, "query", job=job, progress=(0.45, 0.9))
    near_base = _nearest(eb, eb, self_exclude=True)
    near_recent = _nearest(er, eb)
    novel_base = (near_base < novel_sim).astype(float).tolist()
    novel_recent = (near_recent < novel_sim).astype(float).tolist()
    cb, cr = eb.mean(0), er.mean(0)
    shift = 1.0 - float(cb @ cr / (np.linalg.norm(cb) * np.linalg.norm(cr) + 1e-9))
    out: dict[str, Any] = {
        "n_base": len(base_q), "n_recent": len(recent_q), "novel_sim": novel_sim,
        "centroid_shift": round(shift, 4),
        "novel": {"base_rate": round(float(np.mean(novel_base)), 3), "recent_rate": round(float(np.mean(novel_recent)), 3),
                  **unpaired(novel_base, novel_recent)},
        "nearest_sim": {"base_mean": round(float(near_base.mean()), 3), "recent_mean": round(float(near_recent.mean()), 3)},
    }  # fmt: skip
    if base_sig and recent_sig:
        for key in ("gap", "top1"):
            a = [float(s.get(key) or 0) for s in base_sig if s]
            b = [float(s.get(key) or 0) for s in recent_sig if s]
            out[key] = {
                "base_mean": round(float(np.mean(a)), 4) if a else None,
                "recent_mean": round(float(np.mean(b)), 4) if b else None,
            } | unpaired(a, b)
        a = [float(bool(s.get("refused"))) for s in base_sig]
        b = [float(bool(s.get("refused"))) for s in recent_sig]
        out["refusal"] = {"base_rate": round(float(np.mean(a)), 3), "recent_rate": round(float(np.mean(b)), 3)} | unpaired(a, b)
    novel_idx = [i for i, v in enumerate(novel_recent) if v]
    out["novel_groups"] = groups([recent_q[i] for i in novel_idx], er[novel_idx]) if novel_idx else []
    alerts = []
    if out["novel"]["significant"] and out["novel"]["diff"] > 0:
        alerts.append(f"새로운 질문이 늘었습니다({out['novel']['base_rate']:.0%} → {out['novel']['recent_rate']:.0%})")
    if out.get("refusal", {}).get("significant") and out["refusal"]["diff"] > 0:
        alerts.append(f"거절률이 늘었습니다({out['refusal']['base_rate']:.0%} → {out['refusal']['recent_rate']:.0%})")
    if out.get("gap", {}).get("significant") and out["gap"]["diff"] < 0:
        alerts.append("검색 확신도(1 · 2위 차이)가 떨어졌습니다")
    out["alerts"] = alerts
    out["stat_note"] = f"95% 부트스트랩 구간({stats.N_BOOT}회) — 구간이 0 을 지나지 않을 때만 유의"
    return out
