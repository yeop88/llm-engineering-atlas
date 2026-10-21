"""PF1 API 게이트웨이: 모든 요청의 입구에서 속도 제한 · 사용량 기록.

인증(토큰 · 테넌트 구분)은 이미 앞(core.auth 미들웨어)에서 하고, 여기는 그 사용자로 분당 요청 수를 센다(이동 창 60초).
제한은 사용자 · 테넌트 단위 — 한 고객사가 몰아서 부르면 다른 고객사가 느려지는 것을 막으려고. 넘으면 429 와 Retry-After.
사용량은 메모리에 경로 묶음별로 세고(요청마다 DB 에 쓰면 그 자체가 부하), 화면은 이 값을 본다 — 서비스 답변의 비용 · 토큰은
요청 기록(traces)에 따로 남으므로 비용 배분(PF7)은 그쪽을 쓴다.
"""

import threading
import time
from collections import Counter, deque
from typing import Any

from app.core.config import get_settings

_lock = threading.Lock()
_windows: dict[str, deque[float]] = {}
_usage: Counter[tuple[str, str, str]] = Counter()  # (테넌트, 사용자, 경로 묶음) → 요청 수
_denied: Counter[str] = Counter()
_started = time.time()


def route_group(path: str) -> str:
    """'/api/rag/answer/stream' → 'rag' — 경로 묶음(단계) 단위로 세야 화면이 읽을 만하다."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "page"
    if parts[0] == "api":
        return parts[1] if len(parts) > 1 else "api"
    return parts[0] if parts[0] in ("mcp", "a2a") else "page"


def limit_for(user: str, tenant: str) -> int:
    st = get_settings()
    over = st.rate_limit_overrides or {}
    return int(over.get(user) or over.get(f"tenant:{tenant}") or st.rate_limit_per_min or 0)


def check(user: str, tenant: str, path: str, now: float | None = None) -> tuple[bool, int]:
    """→ (허용, 다시 시도까지 초). 제한 0 = 끔. 정적 파일 · 상태 확인은 세지 않는다."""
    if path.startswith(("/static/", "/api/health")):
        return True, 0
    now = now or time.time()
    grp = route_group(path)
    lim = limit_for(user, tenant)
    with _lock:
        _usage[(tenant, user, grp)] += 1
        if not lim:
            return True, 0
        w = _windows.setdefault(f"{tenant}:{user}", deque())
        while w and now - w[0] > 60:
            w.popleft()
        if len(w) >= lim:
            _denied[f"{tenant}:{user}"] += 1
            return False, max(1, int(60 - (now - w[0])) + 1)
        w.append(now)
        return True, 0


def usage() -> dict[str, Any]:
    with _lock:
        rows = [{"tenant": t, "user": u, "route": g, "n": n} for (t, u, g), n in _usage.most_common(200)]
        denied = dict(_denied)
        live = {k: len(v) for k, v in _windows.items()}
    return {"since": _started, "rows": rows, "denied": denied, "last_minute": live, "limit_per_min": get_settings().rate_limit_per_min}
