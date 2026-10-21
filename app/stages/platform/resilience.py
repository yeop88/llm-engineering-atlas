"""PF6 장애 대응 · 대체 모델: 모델 서버 · 벡터 DB 가 멈추면 대체 경로로 넘어가고, 품질 차이를 알린다.

차단기(circuit breaker): 같은 대상이 연달아 실패하면(5번) 30초 동안 부르지 않고 바로 대체로 — 죽은 서버를 매번 기다리면(시간 초과
120초) 모든 요청이 느려진다. 30초 뒤 한 번 시험해 성공하면 다시 연다. LLM 은 LLM_FALLBACKS(설정 순서) 사슬로 넘기고, 대체로 답하면
'대체 모델' 표시가 요청 기록에 남는다 — 같은 품질이 아니라는 것을 숨기지 않는다. 벡터 DB 는 연결 계층이 BM25 로 넘긴다.
"""

import threading
import time
from typing import Any

from app.core import llm
from app.core.config import get_settings

FAILS, COOL = 5, 30.0


class Breaker:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self.lock:
            s = self.state.get(key)
            if not s or s["fails"] < FAILS:
                return True
            return time.monotonic() - s["opened"] >= COOL  # 반쯤 열림: 시험 한 번

    def ok(self, key: str) -> None:
        with self.lock:
            self.state[key] = {
                "fails": 0,
                "opened": 0.0,
                "last_ok": time.time(),
                "last_error": (self.state.get(key) or {}).get("last_error"),
            }

    def fail(self, key: str, err: str) -> None:
        with self.lock:
            s = self.state.setdefault(key, {"fails": 0, "opened": 0.0})
            s["fails"] += 1
            s["last_error"], s["last_fail"] = err[:200], time.time()
            if s["fails"] >= FAILS:
                s["opened"] = time.monotonic()

    def out(self) -> dict[str, Any]:
        with self.lock:
            return {k: {"fails": v["fails"], "open": v["fails"] >= FAILS and time.monotonic() - v["opened"] < COOL, "last_error": v.get("last_error")}
                    for k, v in self.state.items()}  # fmt: skip


BREAKER = Breaker()


def key_of(c: llm.LLMConfig) -> str:
    return f"llm:{c.provider}:{c.model}@{c.base_url}"


def chain(primary: llm.LLMConfig) -> list[llm.LLMConfig]:
    st = get_settings()
    out = [primary]
    for f in st.llm_fallbacks or []:
        try:
            c = llm.resolve(f.get("provider"), f.get("model"))
            if f.get("base_url"):
                c = llm.LLMConfig(c.provider, c.model, f["base_url"].rstrip("/"), c.api_key, c.timeout)
        except llm.LLMError:
            continue
        if key_of(c) != key_of(primary):
            out.append(c)
    return out


def chat(primary: llm.LLMConfig, *args: Any, **kw: Any) -> tuple[dict[str, Any], llm.LLMConfig, list[str]]:
    """→ (응답, 실제로 답한 설정, 건너뛰거나 실패한 대상). 모두 실패하면 마지막 오류."""
    skipped: list[str] = []
    last: Exception | None = None
    for c in chain(primary):
        k = key_of(c)
        if not BREAKER.allow(k):
            skipped.append(f"{c.model}(차단기 열림)")
            continue
        try:
            r = llm.chat(c, *args, **kw)
            BREAKER.ok(k)
            return r, c, skipped
        except llm.LLMError as exc:
            BREAKER.fail(k, str(exc))
            skipped.append(f"{c.model}({str(exc)[:60]})")
            last = exc
    raise last or llm.LLMError("쓸 수 있는 LLM 이 없습니다(차단기 열림)")
