"""IO5 호출 · 비용 상한: 세션(MCP) · 위임 작업(A2A) 하나가 쓸 수 있는 도구 호출 수 · 시간 · 비용.

에이전트 실측에서 한 질문이 20분 걸렸다 — 반복 호출은 끝나지 않을 수 있고, 외부 유료 도구가 붙으면 같은 일이 비용으로 바로 난다.
상한에 닿으면 호출을 막고 그 사실을 감사 기록(status=limit)에 남겨, 부른 쪽이 모은 결과로 답하거나 사람에게 넘기게 한다.
세션 예산은 메모리에 둔다 — 세션은 짧게 살고, 서버가 다시 뜨면 새 세션으로 다시 시작하는 게 맞다.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings

SESSION_TTL = 3600


@dataclass
class Budget:
    max_calls: int
    max_seconds: float
    max_cost: float = 0.0  # 0 = 상한 없음
    calls: int = 0
    cost: float = 0.0
    started: float = field(default_factory=time.monotonic)
    last: float = field(default_factory=time.monotonic)

    @classmethod
    def default(cls) -> Budget:
        st = get_settings()
        return cls(st.interop_max_calls, st.interop_max_seconds, st.interop_max_cost)

    def check(self) -> str | None:
        """다음 호출을 해도 되나 → 안 되면 이유."""
        if self.calls >= self.max_calls:
            return f"호출 상한 {self.max_calls}회에 닿았습니다"
        if (el := time.monotonic() - self.started) > self.max_seconds:
            return f"시간 상한 {self.max_seconds:.0f}초를 넘었습니다({el:.0f}초)"
        if self.max_cost and self.cost >= self.max_cost:
            return f"비용 상한 ${self.max_cost}에 닿았습니다"
        return None

    def charge(self, cost: float = 0.0) -> None:
        self.calls += 1
        self.cost += cost
        self.last = time.monotonic()

    def out(self) -> dict[str, Any]:
        return {"calls": self.calls, "max_calls": self.max_calls, "seconds": round(time.monotonic() - self.started, 1),
                "max_seconds": self.max_seconds, "cost": round(self.cost, 6), "max_cost": self.max_cost}  # fmt: skip


_sessions: dict[str, Budget] = {}
_lock = threading.Lock()


def session(sid: str) -> Budget:
    with _lock:
        now = time.monotonic()
        for k in [k for k, b in _sessions.items() if now - b.last > SESSION_TTL]:  # 오래 쓰지 않은 세션은 버린다
            del _sessions[k]
        return _sessions.setdefault(sid, Budget.default())


def sessions() -> dict[str, dict[str, Any]]:
    with _lock:
        return {k: b.out() for k, b in _sessions.items()}
