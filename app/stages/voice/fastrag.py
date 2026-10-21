"""VC3 짧은 지연 RAG: 지연 예산을 단계별로 나누고 · 캐시 먼저 · 짧은 근거 · 첫 문장부터 흘려보내기 · 단계별 실측과 예산 비교.

말이 끝난 뒤 첫 소리까지가 사람이 어색하지 않은 1초 안팎이어야 하는데, 이 시간을 끝점 대기 · 인식 · 검색 · 첫 문장 생성 · 첫 합성이
나눠 쓴다. 어느 단계가 예산을 넘었는지 턴마다 남겨야 무엇을 고칠지 안다(서빙 맵 실측: 질문당 시간의 2/3 가 근거 읽기).

그래서 음성 답은 채팅 답과 설정이 다르다: 근거 2개 · 근거 글 900자(읽기 시간을 줄임), 답은 2~3문장 · 첫 문장에 핵심 조치(첫 문장만 들어도
쓸모 있게), 번호 목록 대신 말하듯. 같은 질문이 다시 오면 의미 캐시(AS3)의 검증된 답으로 검색 · 생성을 건너뛴다.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np

from app.stages.voice import speech

# 끝(말이 끝난 시각) → 첫 소리. 합 = VOICE_BUDGET_MS 기본값(1200ms) — 설정으로 바꾸면 비율대로 나눈다
SHARE = {"endpoint": 0.34, "stt": 0.17, "retrieve": 0.08, "first_sentence": 0.29, "tts": 0.12}
LABELS = {"endpoint": "끝점 대기", "stt": "인식", "retrieve": "캐시 · 검색", "first_sentence": "첫 문장 생성", "tts": "첫 합성"}
VOICE_INSTRUCTION = (
    "전화 상담 답변입니다. 2~3문장으로 짧게, 첫 문장에 가장 중요한 조치를 말하세요. 번호 목록 · 표 · 괄호 설명 없이 말하듯 쓰고, "
    "오류 코드와 모델명은 그대로 쓰세요. 근거 번호는 붙여도 됩니다(읽을 때 뺍니다)."
)
SEARCH = {"top_k": 2, "max_context_chars": 900, "compress_keep": 2}


def budget(total_ms: float) -> dict[str, float]:
    return {k: round(total_ms * v) for k, v in SHARE.items()}


def stream(
    deltas: Iterator[dict[str, Any]],
    t0: float,
    synth: Callable[[str], str | None] | None = None,
    clock=time.perf_counter,
    mask: Callable[[str], str] | None = None,
) -> Iterator[dict[str, Any]]:
    """LLM 조각 → 문장 사건. t0 = 응답을 시작한 시각(perf_counter). 문장마다 생성된 시각 · 합성까지 끝난 시각을 함께.
    mask: 읽기 전에 문장에 적용(개인정보 가리기) — 문장이 완성된 뒤 · 읽기 전이 소리로 새지 않게 막을 수 있는 마지막 자리다."""
    buf, n, first_token = "", 0, None
    final: dict[str, Any] = {}
    for d in deltas:
        if d.get("done"):
            final = d
            break
        if first_token is None:
            first_token = clock()
        buf += d.get("delta", "")
        done, buf = speech.sentences(buf)
        for s in done:
            yield _sentence(s, n, t0, synth, clock, mask)
            n += 1
    done, _ = speech.sentences(buf, final=True)
    for s in done:
        yield _sentence(s, n, t0, synth, clock, mask)
        n += 1
    yield {"type": "llm_done", "text": final.get("text", ""), "usage": final.get("usage"), "seconds": final.get("seconds"),
           "first_token_ms": round((first_token - t0) * 1000) if first_token else None}  # fmt: skip


def _sentence(s: str, n: int, t0: float, synth, clock, mask=None) -> dict[str, Any]:
    t_gen = clock()
    s = mask(s) if mask else s
    sp = speech.spoken(s)
    audio = synth(sp) if synth else None
    return {
        "type": "sentence",
        "n": n,
        "text": s,
        "spoken": sp,
        "audio": audio,
        "gen_ms": round((t_gen - t0) * 1000),
        "ready_ms": round((clock() - t0) * 1000),
    }


def report(timings: dict[str, float | None], total_budget: float) -> dict[str, Any]:
    """턴 하나의 단계별 시간과 예산 비교 — 넘은 단계 · 첫 소리까지(합)."""
    b = budget(total_budget)
    rows = []
    for k in SHARE:
        v = timings.get(k)
        rows.append({"stage": k, "label": LABELS[k], "ms": v, "budget": b[k], "over": v is not None and v > b[k]})
    first = sum(v for v in (timings.get(k) for k in SHARE) if v is not None)
    return {"stages": rows, "first_audio_ms": round(first), "budget_ms": total_budget, "within": first <= total_budget,
            "worst": max((r for r in rows if r["ms"] is not None), key=lambda r: (r["ms"] or 0) - r["budget"], default=None)}  # fmt: skip


def aggregate(turn_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """여러 턴: 단계별 p50 · p95, 예산 안 비율, 가장 자주 넘은 단계."""
    out = {}
    for k in SHARE:
        v = [r["ms"] for t in turn_reports for r in t["stages"] if r["stage"] == k and r["ms"] is not None]
        out[k] = {"label": LABELS[k], "n": len(v), "p50": round(float(np.percentile(v, 50))) if v else None,
                  "p95": round(float(np.percentile(v, 95))) if v else None, "over": sum(1 for t in turn_reports for r in t["stages"] if r["stage"] == k and r["over"])}  # fmt: skip
    firsts = [t["first_audio_ms"] for t in turn_reports]
    return {"n": len(turn_reports), "stages": out, "first_audio": {"p50": round(float(np.percentile(firsts, 50))) if firsts else None,
            "p95": round(float(np.percentile(firsts, 95))) if firsts else None}, "within": round(sum(t["within"] for t in turn_reports) / len(turn_reports), 3) if turn_reports else None}  # fmt: skip
