"""E7 A/B · 온라인 실험: 요청을 두 설정(A · B)에 나눠 보내고 품질 · 만족도 · 비용 · 지연을 비교한다.

오프라인 평가가 '세트에서 좋은가'라면 A/B 는 '실제 요청에서 좋은가'를 본다(Best-of 는 보상이 유의하게 올랐지만 품질은 불확실했다).
나누기: 실험 id + 요청 키(세션 · 사용자)의 해시로 정한다 — 같은 사람은 같은 팔에 남아 경험이 섞이지 않고, 다시 돌려도 같은 배정이 나온다.
판정: 팔마다 피드백 좋아요율 · 근거 일치 · 질문 관련성 · 거절률 · 지연 · 비용, B − A 차이의 부트스트랩 95% 구간(팔이 달라 짝지을 수 없다).
요청이 적은 실험실에서는 평가 세트 질문을 실제 요청처럼 흘려보내 볼 수 있다(재생 — 피드백은 없고 자동 지표만).
"""

import hashlib
from typing import Any

import numpy as np

from app.core.db import Experiment, Trace
from app.stages.evalops.drift import unpaired


def assign(exp: Experiment, key: str) -> str:
    h = int(hashlib.sha256(f"{exp.id}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "B" if h < exp.split else "A"


def _metrics(ts: list[Trace]) -> dict[str, list[float]]:
    m: dict[str, list[float]] = {"latency_ms": [], "cost": [], "tokens": [], "supported": [], "relevant": [], "refused": [], "liked": []}
    for t in ts:
        v = t.verify or {}
        m["latency_ms"].append(t.total_ms)
        m["cost"].append(t.cost)
        m["tokens"].append(t.tokens_in + t.tokens_out)
        if v.get("supported_ratio") is not None and not v.get("refused"):
            m["supported"].append(float(v["supported_ratio"]))
        if v.get("relevant_ratio") is not None and not v.get("refused"):
            m["relevant"].append(float(v["relevant_ratio"]))
        m["refused"].append(float(bool(v.get("refused"))))
        if t.feedback:
            m["liked"].append(float(t.feedback == 1))
    return m


def report(exp: Experiment, traces: list[Trace]) -> dict[str, Any]:
    arms = {a: [t for t in traces if t.arm == a] for a in ("A", "B")}
    ms = {a: _metrics(ts) for a, ts in arms.items()}
    out: dict[str, Any] = {"arms": {}, "diff": {}}
    for a, m in ms.items():
        out["arms"][a] = (
            {"n": len(arms[a]), "label": (exp.arms.get(a) or {}).get("label", a)}
            | {k: (round(float(np.mean(v)), 4) if v else None) for k, v in m.items()}
            | {"p95_ms": round(float(np.percentile(m["latency_ms"], 95)), 1) if m["latency_ms"] else None, "n_feedback": len(m["liked"])}
        )
    for k in ("liked", "supported", "relevant", "refused", "latency_ms", "cost"):
        out["diff"][k] = unpaired(ms["A"][k], ms["B"][k])
    # 판정 문장: 품질(근거 일치)이 유의하게 나빠지지 않으면서 지연 · 비용이 줄면 B 를 권한다
    d = out["diff"]
    worse = (d["supported"]["significant"] and d["supported"]["diff"] < 0) or (d["liked"]["significant"] and d["liked"]["diff"] < 0)
    better = (d["supported"]["significant"] and d["supported"]["diff"] > 0) or (d["liked"]["significant"] and d["liked"]["diff"] > 0)
    cheaper = d["latency_ms"]["significant"] and d["latency_ms"]["diff"] < 0
    out["verdict"] = ("B 가 품질이 유의하게 낮음 — A 유지" if worse else "B 가 품질이 유의하게 높음" if better
                      else "품질 차이 불확실 · B 가 유의하게 빠름" if cheaper else "차이 불확실 — 더 모으기")  # fmt: skip
    return out
