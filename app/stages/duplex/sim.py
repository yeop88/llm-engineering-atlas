"""FD1~FD7 풀듀플렉스 타이밍 흉내: 내용 이해와 대화 타이밍을 나눠, 타이밍 규칙만 같은 대화로 비교한다.

반이중 음성 상담(VC2)은 '침묵이 일정 시간 이어지면 끝'으로 차례를 넘긴다. 짧게 잡으면 고객이 생각하며 쉬는 사이에 끼어들고,
길게 잡으면 답이 늦다. 사람은 말끝(…는데 / …요)과 억양으로 '아직 말하는 중'인지 알고, 듣는 동안 맞장구를 치고,
위험한 말(타는 냄새 · 연기)에는 바로 끼어든다. 이 흉내는 그 규칙들을 정책으로 나눠 같은 대화에서 잰다.

대화(고객 차례들)는 어절마다 시각이 있고, 차례 안에는 생각하며 쉬는 틈(0.3~1.1초, 연결 어미 뒤)이 있다. 차례 끝 뒤에는 고객이 기다린다.
인식기의 부분 결과는 200ms 늦게 온다(실시간 맵 RT3). 정책:
- 침묵 0.5초 / 침묵 1.4초: 쉼이 그만큼 이어지면 말한다.
- 말끝 규칙: 쉼 0.5초 + 마지막 어절이 끝난 말(…요 · …다)일 때만, 이어질 말(…는데 · …고)이면 1.4초까지 기다린다(VC2 의 continues).
- 말끝 + 미리 준비: 말끝 규칙과 같되, 끝날 것 같은 말끝이 보이는 순간 답을 미리 만들기 시작해 첫 소리까지의 준비 시간을 숨긴다.
재는 것: 응답 간격(고객 말 끝 → 우리 첫 소리) · 끊어 먹기(고객이 아직 말하는 중인데 시작) · 맞장구 정책 · 위험 끼어들기 지연 ·
우리가 말하는 중 고객의 맞장구('네')에 멈추는 잘못 · 진짜 끼어들기를 놓치는 잘못.
"""

import random
import re
from typing import Any

from app.stages.voice.turn import continues

PREP_MS = 700  # 끝을 안 뒤 첫 소리까지(인식 확정 · 검색 · 첫 문장 · 합성) — 실시간 맵의 빠른 서버 어림
STT_LAG = 200
SAFETY = re.compile(r"타는 냄새|연기|불꽃|감전|가스 냄새|물이 새서 콘센트")
BACKCHANNEL_USER = ("네", "음", "아 네", "예")
POLICIES = ("silence500", "silence1400", "ending", "ending_prepare")
LABEL = {"silence500": "침묵 0.5초", "silence1400": "침묵 1.4초", "ending": "말끝 규칙", "ending_prepare": "말끝 + 미리 준비"}

TURNS = [
    ["세탁기가", "탈수할 때", "덜컹거리는데요"],
    ["어제부터", "그랬는데", "오늘은", "더", "심해졌어요"],
    ["모델은", "WM-200", "이고요", "작년에", "샀어요"],
    ["물이", "안", "빠지고", "E4", "가", "떠요"],
    ["그런데", "아까", "말씀하신", "필터는", "어디", "있나요"],
    ["콘센트", "쪽에서", "타는 냄새가", "나는데", "괜찮을까요"],
    ["음", "제가", "확인해", "보니까", "호스가", "꺾여", "있었어요"],
    ["건조기도", "같이", "쓰는데", "그것도", "점검", "되나요"],
]


def dialogue(seed: int) -> list[dict[str, Any]]:
    """고객 차례 4개: 어절마다 (시작 · 끝 ms), 연결 어미 뒤 생각하는 쉼, 끝 뒤 기다림."""
    r = random.Random(seed)
    turns = []
    for words in r.sample(TURNS, 4):
        t, ws = 0, []
        for k, w in enumerate(words):
            dur = int(len(w) * r.uniform(150, 210))
            ws.append({"w": w, "start": t, "end": t + dur})
            t += dur
            if k < len(words) - 1:
                # 이어질 말(…는데 · …고) 뒤에는 생각하며 쉬는 일이 잦다 — 침묵 규칙이 끼어드는 곳. 끝난 말(…이고요) 뒤에도 가끔 쉰다 — 말끝 규칙이 끼어드는 곳
                think = 0.7 if continues(w) else 0.25
                t += int(r.uniform(300, 1100)) if r.random() < think else int(r.uniform(40, 160))
        # 끝을 안 뒤 첫 소리까지의 준비 시간 · 인식 지연은 차례마다 흔들린다(로그 정규 · ±)
        turns.append(
            {
                "words": ws,
                "end": t,
                "text": " ".join(words),
                "prep": int(PREP_MS * r.lognormvariate(0, 0.25)),
                "lag": int(STT_LAG * r.uniform(0.7, 1.6)),
            }
        )
    return turns


FINISHED = re.compile(r"(요|다|까|죠|니다)[.?!]?\s*$")


def finished(text: str) -> bool:
    """끝난 말: 마지막 어절이 '…요 · …다 · …까'. 처음에는 '이어질 말(…는데 · …고)이 아니면 끝'으로 봤다.
    그러자 '세탁기가 · 아까'처럼 끝도 연결도 아닌 어절 뒤의 쉼에서 끼어들었다(차례의 48%)."""
    return bool(FINISHED.search((text or "").strip()))


def _decide(policy: str, turn: dict[str, Any]) -> tuple[int, int, bool]:
    """→ (우리가 첫 소리를 낸 시각, 끝으로 판단한 시각, 끊어 먹었나). 차례 안의 쉼마다 정책이 '끝'이라 판단하는지 본다."""
    ws = turn["words"]
    gaps = [(ws[k]["end"], ws[k + 1]["start"]) for k in range(len(ws) - 1)] + [(turn["end"], 10**9)]
    for end, nxt in gaps:
        heard = " ".join(w["w"] for w in ws if w["end"] <= end)  # 이 쉼까지 들은 말
        if policy == "silence500":
            wait = 500
        elif policy == "silence1400":
            wait = 1400
        else:
            wait = 500 if finished(heard) else 1400
        lag = turn["lag"]
        wait = max(wait, lag) if policy.startswith("ending") else wait  # 말끝을 보려면 부분 인식이 와야 한다
        decide = end + wait
        if decide < nxt:  # 다음 어절이 오기 전에 '끝'이라 판단
            prep = turn["prep"]
            if policy == "ending_prepare" and finished(heard):
                # 끝날 것 같은 말끝이 들린 순간(인식 지연 뒤)부터 미리 만든다 — 판단까지 기다린 시간만큼 준비가 줄어든다
                prep = max(150, turn["prep"] - (wait - lag))
            speak = decide + prep
            # 차례 중간의 쉼에서 '끝'이라 판단했으면 끊어 먹기 — 고객이 다시 말하기 전에 우리가 시작했든 겹쳤든, 차례를 빼앗은 것이다
            return speak, decide, nxt < 10**9
    return turn["end"] + 1400 + turn["prep"], turn["end"] + 1400, False


def run_policy(policy: str, seeds: int = 50) -> dict[str, Any]:
    gaps, cut = [], 0
    n = 0
    for s in range(seeds):
        for tr in dialogue(s):
            speak, decide, cut_in = _decide(policy, tr)
            n += 1
            if cut_in:
                cut += 1
            else:
                gaps.append(speak - tr["end"])
    gaps.sort()
    q = lambda p: gaps[min(len(gaps) - 1, int(p * len(gaps)))] if gaps else None  # noqa: E731
    return {
        "policy": policy,
        "label": LABEL[policy],
        "turns": n,
        "cut_in": round(cut / n, 3),
        "gap_p50": q(0.5),
        "gap_p95": q(0.95),
        "gap_mean": round(sum(gaps) / len(gaps)) if gaps else None,
    }


def backchannel(seeds: int = 50, wait_ms: int = 400) -> dict[str, Any]:
    """FD5 맞장구: 이어질 말끝(…는데 · …고) 뒤에 wait_ms 동안 다음 어절이 안 들리면 '네'(0.3초). 그 순간에는 쉼이 얼마나 길지 모른다.

    처음에는 '쉼이 0.6초 넘으면'으로 정했는데, 그것은 쉼이 끝난 뒤에야 아는 값이라 실제로는 쓸 수 없는 규칙이었다.
    지금은 판단 시각(말 끝 + 인식 지연 + wait_ms)까지 들은 것만 보고 정한다. 겹침 = 고객이 '네'가 끝나기 전에 다시 말함.
    """
    placed = overlap = chances = 0
    for s in range(seeds):
        for tr in dialogue(s):
            ws = tr["words"]
            for k in range(len(ws) - 1):
                heard = " ".join(w["w"] for w in ws[: k + 1])
                if not continues(heard):
                    continue
                chances += 1
                at = ws[k]["end"] + tr["lag"] + wait_ms
                if ws[k + 1]["start"] <= at:  # 그 전에 다시 말했다 — 맞장구 안 함
                    continue
                placed += 1
                if at + 300 > ws[k + 1]["start"]:
                    overlap += 1
    return {"wait_ms": wait_ms, "chances": chances, "placed": placed, "overlap_rate": round(overlap / max(1, placed), 3)}


def safety(seeds: int = 50) -> dict[str, Any]:
    """FD5 안전 끼어들기: 위험한 말이 들리면 차례가 끝나기를 기다리지 않고 경고 — 위험 말 끝 → 경고 첫 소리 지연."""
    lat, wait_lat, missed, n = [], [], 0, 0
    for s in range(seeds):
        for tr in dialogue(s):
            hit = next((w for w in tr["words"] if SAFETY.search(w["w"])), None)
            if not hit:
                continue
            n += 1
            heard_at = hit["end"] + tr["lag"]
            if heard_at > tr["end"] + 500:
                missed += 1
            lat.append(heard_at + 300 - hit["end"])  # 정해 둔 경고 문장은 미리 합성해 둔다(300ms 재생 시작)
            wait_lat.append(_decide("ending", tr)[0] - hit["end"])  # 끼어들지 않고 차례가 끝나기를 기다렸다면
    return {"n": n, "latency_ms": round(sum(lat) / len(lat)) if lat else None, "before_turn_end": round(1 - missed / max(1, n), 3),
            "wait_policy_latency_ms": round(sum(wait_lat) / len(wait_lat)) if wait_lat else None}  # fmt: skip


def duplex_stop(seeds: int = 50) -> dict[str, Any]:
    """FD6: 우리가 말하는 중 고객 소리 — 맞장구('네' · '음', 0.4초 미만)면 계속, 그보다 길거나 내용이 있으면 멈춤. 소리 길이만 보는 정책과 비교."""
    r = random.Random(7)
    rows = {"length_only": [0, 0], "length_text": [0, 0]}  # [맞장구에 멈춘 잘못, 진짜 끼어들기를 놓친 잘못]
    n_bc = n_real = 0
    for _ in range(seeds * 4):
        if r.random() < 0.6:
            text, dur = r.choice(BACKCHANNEL_USER), r.randint(150, 450)
            real = False
            n_bc += 1
        else:
            text, dur = r.choice(["잠깐만요", "아니요 그게 아니라", "그건 해 봤어요", "다시 말씀해 주세요"]), r.randint(300, 1200)
            real = True
            n_real += 1
        stop_len = dur >= 250  # 끼어들기 감지(VC2 barge_ms 200) — 길이만
        stop_txt = dur >= 250 and text not in BACKCHANNEL_USER  # 부분 인식 글로 맞장구를 거름
        for k, stop in (("length_only", stop_len), ("length_text", stop_txt)):
            if stop and not real:
                rows[k][0] += 1
            if not stop and real:
                rows[k][1] += 1
    return {k: {"false_stop": round(v[0] / max(1, n_bc), 3), "missed_barge": round(v[1] / max(1, n_real), 3)} for k, v in rows.items()}


def evaluate(seeds: int = 50) -> dict[str, Any]:
    return {"seeds": seeds, "policies": [run_policy(p, seeds) for p in POLICIES], "backchannel": [backchannel(seeds, w) for w in (200, 400, 700)], "safety": safety(seeds),
            "duplex_stop": duplex_stop(seeds), "prep_ms": PREP_MS}  # fmt: skip
