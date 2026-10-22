"""RT6 실측: 실제 LLM 스트리밍으로 첫 토큰 · 첫 문장 시간을 재어 재생기의 LLM 시간 분포를 바꿔 넣는다.

재생기의 LLM 시간은 기본값(이 PC 의 llama-server 어림)이다. 모델 · 서버 · 프롬프트가 바뀌면 꼬리가 달라지므로, 같은 음성 지시문(VC3)으로
몇 번 불러 첫 토큰(중앙값 · 로그 퍼짐)과 첫 문장까지의 토큰 간격을 잰다. 같은 질문을 되풀이하면 서버의 프롬프트 캐시가 첫 토큰을
줄여 실제보다 좋게 나오므로 질문을 돌려 가며 묻는다.
"""

import math
import statistics
import time
from typing import Any

from app.core import llm
from app.stages.voice import fastrag, speech


def measure(cfg: llm.LLMConfig, questions: list[str], n: int = 6, context: str = "", progress=lambda f, m: None) -> dict[str, Any]:
    rows = []
    for i in range(n):
        q = questions[i % len(questions)]
        progress(i / n, f"{i + 1}/{n} {q[:20]}")
        user = (f"근거:\n{context}\n\n" if context else "") + f"질문: {q}"
        t0 = time.perf_counter()
        first = first_sentence = None
        buf = ""
        done: dict[str, Any] = {}
        for d in llm.chat_stream(cfg, fastrag.VOICE_INSTRUCTION, user, max_tokens=120, temperature=0.3):
            if d.get("done"):
                done = d
                break
            now = time.perf_counter()
            if first is None:
                first = now
            buf += d.get("delta", "")
            if first_sentence is None and speech.sentences(buf)[0]:
                first_sentence = now
        end = time.perf_counter()
        toks = (done.get("usage") or {}).get("completion_tokens")
        gen_s = end - (first or end)
        rows.append({"question": q, "ttft_ms": round(((first or end) - t0) * 1000, 1),
                     "first_sentence_ms": round(((first_sentence or end) - (first or end)) * 1000, 1),
                     "tok_ms": round(gen_s * 1000 / toks, 1) if toks and toks > 1 else None, "tokens": toks})  # fmt: skip
    ttft = [r["ttft_ms"] for r in rows if r["ttft_ms"] > 0]
    logs = [math.log(x) for x in ttft]
    tok = [r["tok_ms"] for r in rows if r["tok_ms"]]
    fs = [r["first_sentence_ms"] for r in rows]
    tok_ms = statistics.median(tok) if tok else None
    return {"model": cfg.model, "rows": rows, "ttft_ms": round(statistics.median(ttft), 1) if ttft else None,
            "ttft_sigma": round(statistics.pstdev(logs), 3) if len(logs) > 1 else 0.0, "tok_ms": tok_ms,
            "first_sentence_ms": round(statistics.median(fs), 1) if fs else None,
            "first_sentence_tokens": round(statistics.median(fs) / tok_ms) if fs and tok_ms else None}  # fmt: skip
