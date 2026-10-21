"""VC2 말 끊기 · 끼어들기(턴 관리): 에너지 기반 말소리 감지 · 끝점 판단 · 끼어들기 감지.

- 말소리 감지: 20ms 프레임 dB 가 잡음 바닥 + margin 을 넘으면 말소리. 잡음 바닥은 조용한 프레임으로 천천히 따라간다(통화마다 배경 소음이 달라 고정 문턱은 틀림).
- 끝점: 침묵이 short_ms 이어지면 '끝났을지도' — 바로 인식해 본 글이 이어질 말로 끝나면('그리고' · '~는데' · '~고') long_ms 까지 더 기다린다.
  짧게 끊으면 생각 중인 고객의 말을 자르고, 길게 기다리면 응답이 늦다 — 한 문턱으로는 둘 다 맞출 수 없어 글의 모양으로 나눈다.
- 끼어들기: 합성 음성이 나오는 동안 말소리가 barge_ms 이어지면 고객이 끼어든 것. 화면은 같은 문턱으로 바로 소리를 멈추고(왕복 지연 없이),
  서버는 기록(몇 글자까지 말했는지)만 받는다. 스피커 소리가 마이크로 되돌아오는 것은 브라우저의 반향 제거(echoCancellation)에 맡긴다.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.stages.voice import audio

# 말이 아직 이어질 것 같은 끝(연결 어미 · 접속사 · 말줄임). '요' · '다' · '까' 로 끝나면 끝난 말로 본다.
CONTINUE = re.compile(
    r"(그리고|그런데|근데|그래서|그러니까|아니면|하고|인데|는데|은데|고|며|면서|서|면|지만|거든|어서|아서|게|음|어|그|저|\.\.\.|…|,)\s*$"
)


def continues(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(CONTINUE.search(t)) and not re.search(r"(요|다|까|죠|네|니다)[.?!]?\s*$", t)


@dataclass
class Params:
    margin_db: float = 10.0
    min_speech_ms: int = 200
    short_ms: int = 500
    long_ms: int = 1400
    barge_ms: int = 200
    max_utt_ms: int = 15000  # 이보다 긴 말은 잘라 인식(중간 결과)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Endpointer:
    p: Params = field(default_factory=Params)
    buf: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    offset: int = 0  # buf[0] 의 통화 내 표본 위치
    noise: float = -55.0
    speech_start: int | None = None
    last_voice: int | None = None
    pending: tuple[int, int] | None = None  # 끝점 후보(시작, 끝) — 글을 보고 확정
    waited_long: bool = False
    # 이 발화에서 이미 끼어들기를 알렸는지 — 화면은 합성 음성이 실제로 멈출 때까지 조각마다 speaking=true 를 보내므로,
    # 조각마다 다시 알리면 한 번 끼어든 것이 사건 여러 개로 기록돼 보고(끼어들기 수)가 부풀었다
    barged: bool = False
    total: int = 0

    def _ms(self, n: int) -> int:
        return int(n * 1000 / audio.SR)

    def feed(self, x: np.ndarray, agent_speaking: bool = False) -> list[dict[str, Any]]:
        """새 표본을 넣고 사건을 돌려준다: speech_start · barge_in · candidate(끝점 후보 — 인식 후 decide) · cut(너무 긴 말)."""
        ev: list[dict[str, Any]] = []
        start_total = self.total
        self.buf = np.concatenate([self.buf, x.astype(np.float32)])
        self.total += len(x)
        db = audio.frame_db(x)
        for i, d in enumerate(db):
            pos = start_total + i * audio.FRAME
            if d > self.noise + self.p.margin_db:
                if self.speech_start is None:
                    self.speech_start = pos
                self.last_voice = pos + audio.FRAME
                if self.pending:  # 후보 뒤에 다시 말함 → 이어진 말
                    self.pending, self.waited_long = None, False
                    ev.append({"type": "resumed", "at_ms": self._ms(pos)})
                if agent_speaking and not self.barged and self._ms(self.last_voice - self.speech_start) >= self.p.barge_ms:
                    ev.append({"type": "barge_in", "at_ms": self._ms(pos)})
                    self.barged = True  # 발화 하나에 한 번만(조각을 넘어서도)
            else:
                self.noise = 0.98 * self.noise + 0.02 * float(d) if d < self.noise + 3 else self.noise
        if self.speech_start is not None and self.last_voice is not None:
            dur = self._ms(self.last_voice - self.speech_start)
            sil = self._ms(self.total - self.last_voice)
            if dur >= self.p.min_speech_ms and self.pending is None and sil >= self.p.short_ms:
                self.pending = (self.speech_start, self.last_voice)
                ev.append(
                    {"type": "candidate", "start_ms": self._ms(self.speech_start), "end_ms": self._ms(self.last_voice), "silence_ms": sil}
                )
            elif self.pending is not None and self.waited_long and sil >= self.p.long_ms:
                ev.append({"type": "timeout", "silence_ms": sil})
            elif dur >= self.p.max_utt_ms:
                ev.append({"type": "cut", "start_ms": self._ms(self.speech_start), "end_ms": self._ms(self.last_voice)})
            elif dur < self.p.min_speech_ms and sil >= self.p.short_ms:  # 기침 · 잡음 — 버림
                self.speech_start = self.last_voice = None
                self.barged = False
        return ev

    def segment(self, start: int, end: int) -> np.ndarray:
        a, b = max(0, start - self.offset - 3 * audio.FRAME), max(0, end - self.offset + 5 * audio.FRAME)
        return self.buf[a:b]

    def decide(self, text: str, forced: bool = False) -> str:
        """끝점 후보의 글을 보고: 'final'(턴 끝) · 'wait'(이어질 말 — long_ms 까지). forced 는 timeout · cut."""
        if not forced and not self.waited_long and continues(text):
            self.waited_long = True
            return "wait"
        self.close()
        return "final"

    def close(self) -> None:
        end = self.last_voice or self.total
        keep = max(0, end - self.offset)
        self.buf, self.offset = self.buf[keep:], self.offset + keep
        self.speech_start = self.last_voice = self.pending = None
        self.waited_long = self.barged = False
