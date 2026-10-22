"""IF1 워크로드 측정 · IF2 미리 채우기 · 생성 분리.

최적화는 기준선이 먼저다. 같은 기법도 '프롬프트가 긴 워크로드'(RAG — 근거 읽기가 지연의 2/3)와 '답이 긴 워크로드'(요약 · 작성)에서 효과가
반대다. 그래서 운영 요청 기록(traces)에서 프롬프트 · 답 토큰 분포, 단계별 시간(검색 · LLM · 검증), 동시 요청 수를 먼저 재고,
서버에 길이를 바꾼 탐침 요청을 보내 미리 채우기(프롬프트 읽기 — 연산 한계) · 생성(토큰마다 가중치 읽기 — 대역폭 한계) 속도를 따로 잰 뒤,
둘을 곱해 '이 워크로드의 요청 하나에서 시간이 어디에 쓰이나'를 계산한다. 요청 기록의 llm 단계 시간은 둘이 섞인 값이라 그대로는 나눌 수 없다.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.db import Trace, utcnow

FILL = "근로기준법에 따르면 사용자는 근로계약을 체결할 때에 근로자에게 임금, 소정근로시간, 휴일, 연차 유급휴가를 명시하여야 한다. "


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def dist(v: list[float]) -> dict[str, Any]:
    return {"n": len(v), "mean": round(sum(v) / len(v), 1) if v else None, "p50": pct(v, 0.5), "p95": pct(v, 0.95), "p99": pct(v, 0.99),
            "max": round(max(v), 1) if v else None}  # fmt: skip


def profile(db: Session, days: float = 30, kinds: list[str] | None = None, limit: int = 20000) -> dict[str, Any]:
    """요청 기록 → 길이 · 단계 시간 · 동시 수 분포. 기록이 끝난 시각(created_at)과 총 시간으로 요청 구간을 되살려 겹침을 센다."""
    q = select(Trace).where(Trace.created_at >= utcnow() - timedelta(days=days)).order_by(Trace.created_at.desc()).limit(limit)
    if kinds:
        q = q.where(Trace.kind.in_(kinds))
    rows = list(db.scalars(q))
    if not rows:
        return {"n": 0}
    steps: dict[str, list[float]] = {}
    for r in rows:
        for st in r.steps or []:
            if isinstance(st, dict) and st.get("name") and st.get("ms") is not None:
                steps.setdefault(st["name"], []).append(float(st["ms"]))
    # 동시 수: 요청마다 [끝 − 총 시간, 끝] 구간 — 시작 · 끝 사건을 시각순으로 훑어 최대 겹침과 평균을 구한다
    ev = []
    for r in rows:
        end = r.created_at.timestamp()
        ev += [(end - (r.total_ms or 0) / 1000, 1), (end, -1)]
    ev.sort()
    cur = peak = 0
    busy = weighted = 0.0
    last = ev[0][0]
    for t, d in ev:
        if cur:
            busy += t - last
            weighted += cur * (t - last)
        cur += d
        peak = max(peak, cur)
        last = t
    kinds_n: dict[str, int] = {}
    for r in rows:
        kinds_n[r.kind] = kinds_n.get(r.kind, 0) + 1
    total = [float(r.total_ms or 0) for r in rows]
    llm_ms = steps.get("llm", [])
    return {"n": len(rows), "days": days, "kinds": kinds_n, "tokens_in": dist([float(r.tokens_in) for r in rows if r.tokens_in]),
            "tokens_out": dist([float(r.tokens_out) for r in rows if r.tokens_out]), "total_ms": dist(total),
            "steps": {k: dist(v) for k, v in sorted(steps.items(), key=lambda x: -sum(x[1]))},
            "llm_share": round(sum(llm_ms) / sum(total), 3) if sum(total) else None,
            "concurrency": {"peak": peak, "mean_when_busy": round(weighted / busy, 2) if busy else 0}}  # fmt: skip


def probe(cfg: llm.LLMConfig, prompt_tokens: tuple[int, ...] = (256, 1024, 2048), out_tokens: tuple[int, ...] = (64, 256),
          progress=lambda f, m: None) -> list[dict[str, Any]]:  # fmt: skip
    """길이를 바꾼 요청으로 미리 채우기 · 생성 속도를 따로(llama-server timings). 캐시를 꺼 매번 처음부터 읽게 한다."""
    out = []
    combos = [(p, o) for p in prompt_tokens for o in out_tokens]
    for i, (p, o) in enumerate(combos):
        progress(i / len(combos), f"프롬프트 ≈{p} · 답 {o}")
        text = (FILL * (p // 40 + 1))[: int(p * 1.6)]  # 한국어 1 토큰 ≈ 1.6 글자(실제 토큰 수는 서버가 알려 준 값을 쓴다)
        r = llm.chat(
            cfg,
            "주어진 글을 읽고 요청한 길이만큼 이어서 씁니다.",
            f"{text}\n\n위 내용을 바탕으로 길게 설명해 주세요.",
            o,
            0.0,
            no_cache=True,
        )
        tm = r.get("timings") or {}
        out.append({"prompt_target": p, "out_target": o, "prompt_tokens": tm.get("prompt_tokens_evaluated") or tm.get("prompt_n"),
                    "out_tokens": (r.get("usage") or {}).get("output_tokens"), "prompt_ms": tm.get("prompt_ms"), "gen_ms": tm.get("generation_ms"),
                    "prompt_tps": tm.get("prompt_per_second"), "gen_tps": tm.get("generation_per_second"), "seconds": r.get("seconds")})  # fmt: skip
    return out


def split(prof: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    """워크로드의 중앙값 · p95 요청에서 미리 채우기 · 생성 시간과 몫. 속도는 탐침의 중앙값(길이마다 조금씩 다름)."""
    ptps = sorted(x["prompt_tps"] for x in probes if x.get("prompt_tps"))
    gtps = sorted(x["gen_tps"] for x in probes if x.get("gen_tps"))
    if not ptps or not gtps or not prof.get("n"):
        return {"available": False}
    pp, gg = ptps[len(ptps) // 2], gtps[len(gtps) // 2]
    res: dict[str, Any] = {"available": True, "prompt_tps": round(pp, 1), "gen_tps": round(gg, 1)}
    for q in ("p50", "p95"):
        tin, tout = prof["tokens_in"].get(q) or 0, prof["tokens_out"].get(q) or 0
        pm, gm = tin / pp * 1000, tout / gg * 1000
        res[q] = {"tokens_in": tin, "tokens_out": tout, "prefill_ms": round(pm), "decode_ms": round(gm),
                  "prefill_share": round(pm / (pm + gm), 3) if pm + gm else None}  # fmt: skip
    share = res["p50"]["prefill_share"] or 0
    # 몫이 큰 쪽이 먼저 줄일 곳 — 미리 채우기: 앞부분 캐시 · 근거 줄이기 · 압축, 생성: 양자화 · 추측 디코딩 · 짧은 답
    res["bottleneck"] = "prefill" if share >= 0.5 else "decode"
    res["advice"] = (["앞부분 캐시(IF6)", "근거 길이 · 압축(S2 · KC)", "미리 채우기 묶음(ubatch) 키우기"] if share >= 0.5
                     else ["가중치 · KV 양자화(IF3 · IF4)", "추측 디코딩(IF7)", "답 길이 상한"])  # fmt: skip
    return res
