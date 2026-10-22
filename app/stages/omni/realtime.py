"""OM2 실시간 음성 대화: 말하는 도중의 인식을 확정해 나가기 · 끼어들기 · 문장 단위로 들려주기.

스트리밍 인식기는 같은 말을 들을수록 앞 인식을 고친다('세탁기 무늬' → '세탁기 문이'). 고치기 전의 글로 검색하면 틀린 근거를 찾고,
끝까지 기다리면 늦다. 그래서 '연속 일치' 규칙으로 확정한다: 새 가설과 직전 가설이 앞에서부터 같은 낱말들은 다음에 바뀔 가능성이 낮으니
확정하고, 그 뒤만 잠정으로 둔다(스트리밍 음성 인식에서 널리 쓰는 local agreement 규칙 — 설계만 참고해 새로 작성).
확정된 부분이 문장 끝을 지나면 그 문장으로 미리 검색을 시작할 수 있다(early). 끝점(VC2)이 오면 남은 잠정 부분까지 모두 확정한다.

재는 것: 확정한 글이 최종 인식과 같은가(확정 오류 = 확정 뒤에 바뀐 낱말), 깜빡임(화면에 보였다가 바뀐 잠정 낱말 수), 확정 지연(낱말이
처음 나온 뒤 확정될 때까지 가설 몇 개).
"""

import random
import re
from typing import Any

FINAL_PUNCT = re.compile(r"[.?!요까다죠네]$")


def _words(s: str) -> list[str]:
    return (s or "").split()


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


class Stabilizer:
    """가설을 하나씩 받아 확정 · 잠정으로 나눈다. agree=2 이면 연속한 두 가설이 같아야 확정."""

    def __init__(self, agree: int = 2):
        self.agree = max(1, agree)
        self.committed: list[str] = []
        self.recent: list[list[str]] = []
        self.first_seen: dict[int, int] = {}
        self.events: list[dict[str, Any]] = []
        self.flicker = 0
        self._shown: list[str] = []
        self.n = 0

    def push(self, hypothesis: str, final: bool = False) -> dict[str, Any]:
        self.n += 1
        w = _words(hypothesis)
        if self.committed and w[: len(self.committed)] != self.committed:
            # 인식기가 이미 확정한 부분까지 고쳤다 — 확정은 되돌리지 않고(이미 검색 · 표시에 썼음) 확정 오류로 센다
            self.events.append({"n": self.n, "type": "conflict", "hyp": hypothesis})
            w = self.committed + w[len(self.committed) :] if len(w) > len(self.committed) else list(self.committed)
        for i in range(len(self.committed), len(w)):
            self.first_seen.setdefault(i, self.n)
        self.recent = (self.recent + [w])[-self.agree :]
        if final:
            stable = len(w)
        elif len(self.recent) < self.agree:
            stable = len(self.committed)
        else:
            stable = min(_common_prefix(self.recent[0], r) for r in self.recent[1:]) if self.agree > 1 else len(w)
        new = w[len(self.committed) : max(stable, len(self.committed))]
        if new:
            for j in range(len(self.committed), len(self.committed) + len(new)):
                self.events.append({"n": self.n, "type": "commit", "word": w[j], "lag": self.n - self.first_seen.get(j, self.n)})
            self.committed += new
        tentative = w[len(self.committed) :]
        shown = self.committed + tentative
        # 깜빡임: 직전에 보여 준 잠정 낱말이 이번에 다른 낱말로 바뀐 수
        self.flicker += sum(1 for x, y in zip(self._shown, shown, strict=False) if x != y)
        self._shown = shown
        text = " ".join(self.committed)
        return {"n": self.n, "committed": text, "tentative": " ".join(tentative), "new": " ".join(new),
                "early": bool(new) and bool(FINAL_PUNCT.search(text)), "final": final}  # fmt: skip


def run(hypotheses: list[str], agree: int = 2, final_text: str | None = None) -> dict[str, Any]:
    """가설 목록(마지막이 최종)을 차례로 넣어 확정 과정과 지표."""
    st = Stabilizer(agree)
    steps = [st.push(h, final=(i == len(hypotheses) - 1)) for i, h in enumerate(hypotheses)]
    final = _words(final_text if final_text is not None else (hypotheses[-1] if hypotheses else ""))
    committed_before_final = _words(steps[-2]["committed"]) if len(steps) > 1 else []
    wrong = sum(1 for i, x in enumerate(committed_before_final) if i >= len(final) or final[i] != x)
    lags = [e["lag"] for e in st.events if e["type"] == "commit"]
    early_at = next((s["n"] for s in steps if s["early"]), None)
    return {"steps": steps, "final": " ".join(final), "committed_early_words": len(committed_before_final),
            "commit_errors": wrong, "conflicts": sum(1 for e in st.events if e["type"] == "conflict"), "flicker": st.flicker,
            "mean_lag": round(sum(lags) / len(lags), 2) if lags else None, "early_at": early_at, "hypotheses": len(hypotheses)}  # fmt: skip


# 인식기가 흔히 틀렸다가 고치는 꼴(소리가 비슷한 낱말) — 시험 가설을 만들 때 잠정 꼬리를 이렇게 바꾼다
CONFUSE = {"문이": "무늬", "안": "한", "열려요": "열여요", "에러": "에로", "코드": "고드", "세탁기": "세탁이", "건조기": "건조이",
           "물이": "무리", "소리가": "소리아", "나요": "나와"}  # fmt: skip


def simulate(text: str, seed: int = 0, noise: float = 0.5, step_words: int = 1) -> list[str]:
    """최종 글 → 스트리밍 인식기처럼 늘어나는 가설들. 마지막 낱말 한두 개는 noise 확률로 비슷한 소리로 틀렸다가 다음 가설에서 고쳐진다."""
    rnd = random.Random(seed)
    w = _words(text)
    out = []
    for k in range(step_words, len(w) + step_words, step_words):
        cur = list(w[: min(k, len(w))])
        if k < len(w):
            # 가장 새 낱말이 가장 불확실하다 — 마지막 낱말은 noise, 그 앞 낱말은 noise/3 확률로 틀린다
            for j, pr in ((len(cur) - 1, noise), (len(cur) - 2, noise / 3)):
                if j >= 0 and rnd.random() < pr:
                    cur[j] = CONFUSE.get(cur[j], cur[j][:-1] if len(cur[j]) > 1 else cur[j])
        out.append(" ".join(cur))
    if not out or out[-1] != text.strip():
        out.append(" ".join(w))
    return out
