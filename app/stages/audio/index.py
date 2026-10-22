"""AU5~AU7 시간 구간 색인 · 의미 표현 · 검색 · 요약, 그리고 채점.

구간(종류 · 화자 · 사건 · 시각)을 한 줄 글로 바꿔 색인한다('3.6~9.3초 환경음 · 덜컹 반복(0.9초 간격 7번)').
글로 바꾸는 이유는 RAG 검색 · 요약 · 근거 표시를 그대로 쓰려는 것이다. 말 구간에는 인식한 글을 붙인다.
- 올린 녹음: 음성 인식(VC4)이 설정돼 있으면 그 글을 붙인다.
- 합성 장면: 합성 말은 사람 말이 아니라 인식할 수 없다. 장면을 만들 때 적은 글을 붙이고 출처를 '정답 글(합성)'로 밝힌다.
검색은 글자 2-gram 겹침에 소리 낱말(덜컹 · 웅웅 · 삐 · 음악)을 사건 종류로 바꾼 점수를 더한다. 사건 종류 이름은 고객이 쓰는 말과 다르다.
"""

import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.stages.audio import scene, synth

PRESET = Path(__file__).parent / "presets" / "scenes.json"
# 고객 말 → 사건 · 구간 종류. '덜컹'을 찾는 사람에게 thump 를 돌려주려면 이 다리가 필요하다
SOUND_WORDS = {"thump": ("덜컹", "쿵", "탈수", "흔들"), "hum": ("웅웅", "윙", "소음"), "beep": ("삐", "경고음", "알림음"), "music": ("음악", "대기음"),
               "speech": ("말", "말한", "얘기", "했")}  # fmt: skip


def preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def describe(res: dict[str, Any], texts: dict[tuple[float, float], str] | None = None, text_source: str = "") -> list[dict[str, Any]]:
    """분석 결과 → 색인 항목(구간 · 사건마다 한 줄). texts: (시작, 끝) → 말 글(겹치는 말 구간에 붙임)."""
    items = []
    for s in res["segments"]:
        if s["type"] == "silence":
            continue
        line = f"{s['start']}~{s['end']}초 {scene.LABEL[s['type']]}"
        text = ""
        if s["type"] == "speech":
            line += f" · {s.get('speaker') or '화자?'}"
            for (a, b), t in (texts or {}).items():
                if a < s["end"] and b > s["start"]:
                    text = (text + " " + t).strip()
            if text:
                line += f": {text}"
        items.append({"kind": "segment", "type": s["type"], "start": s["start"], "end": s["end"], "speaker": s.get("speaker"), "text": text, "line": line,
                      "text_source": text_source if text else ""})  # fmt: skip
    for e in res["events"]:
        extra = (
            f"({e['period_s']}초 간격 {e['count']}번)"
            if e["type"] == "thump"
            else f"({e.get('count', 1)}번)"
            if e["type"] == "beep"
            else ""
        )
        items.append(
            {
                "kind": "event",
                "type": e["type"],
                "start": e["start"],
                "end": e["end"],
                "line": f"{e['start']}~{e['end']}초 {scene.EVENT_LABEL[e['type']]}{extra}",
            }
        )
    return sorted(items, key=lambda x: x["start"])


def _bigrams(s: str) -> Counter:
    s = re.sub(r"\s+", "", s.lower())
    return Counter(s[i : i + 2] for i in range(len(s) - 1))


def search(items: list[dict[str, Any]], q: str, k: int = 3) -> list[dict[str, Any]]:
    qb = _bigrams(q)
    want = {t for t, ws in SOUND_WORDS.items() if any(w in q for w in ws)}
    out = []
    for it in items:
        ib = _bigrams((it.get("text") or "") + " " + it["line"])
        overlap = sum((qb & ib).values()) / max(1, sum(qb.values()))
        # 사건 · 종류가 고객 말과 맞으면 큰 점수 — 말 구간(speech)은 글이 맞을 때만 의미가 있어 작게
        bonus = 1.0 if it["type"] in want and it["type"] != "speech" else 0.15 if it["type"] in want else 0.0
        out.append(it | {"score": round(overlap + bonus, 3)})
    return sorted(out, key=lambda x: -x["score"])[:k]


def summary(items: list[dict[str, Any]]) -> str:
    """시간 순 한 줄씩 — 요약 LLM 에 넘기거나 상담 기록에 붙인다(사건 · 화자 · 시각이 근거로 남게)."""
    return "\n".join(it["line"] for it in items)


# ── 채점 ─────────────────────────────────────────────────────────────────
def random_parts(seed: int) -> list[dict[str, Any]]:
    """규칙을 맞출 때 쓰지 않은 장면 — 종류 · 길이 · 화자 수 · 덜컹 간격을 씨앗으로 섞는다."""
    r = random.Random(seed)
    spks = r.sample(["A", "B", "C"], r.choice([1, 2, 3]))
    parts = []
    for _ in range(r.randint(4, 7)):
        k = r.choice(["speech", "speech", "speech", "music", "noise", "beep", "thump", "hum"])
        parts.append({"kind": k, "dur": round(r.uniform(1.5, 4.0), 1), "spk": r.choice(spks), "period": round(r.uniform(0.6, 1.4), 2)})
        parts.append({"kind": "silence", "dur": round(r.uniform(0.3, 0.8), 1)})
    return parts


def _energy_vad(f: dict[str, Any]) -> list[str]:
    """비교 기준: 크기만 보는 말소리 감지 — 소리가 있으면 모두 '말'(음성 상담 맵의 끝점 감지가 보는 것)."""
    import numpy as np

    db = f["db"]
    floor = float(np.percentile(db, 10)) if len(db) else 0
    return ["speech" if d > max(floor + 10, -60) else "silence" for d in db]


def _event_match(pred: list[dict[str, Any]], truth: list[dict[str, Any]]) -> tuple[int, int, int]:
    tr = [t for t in truth if t["kind"] in scene.EVENT_LABEL]
    used, tp = set(), 0
    for p in pred:
        j = next(
            (j for j, t in enumerate(tr) if j not in used and t["kind"] == p["type"] and p["start"] < t["end"] and p["end"] > t["start"]),
            None,
        )
        if j is not None:
            used.add(j)
            tp += 1
    return tp, len(pred) - tp, len(tr) - tp


def _diar(pieces: list[dict[str, Any]], truth: dict[str, Any]) -> tuple[float, float, int] | None:
    pairs = []
    for p in pieces:
        mid = (p["start"] + p["end"]) / 2
        t = next((s for s in truth["segments"] if s["start"] <= mid < s["end"]), None)
        if t and t["type"] == "speech":
            pairs.append((t["spk"], p["speaker"]))
    if not pairs:
        return None
    cl: dict[str, Counter] = {}
    tl: dict[str, Counter] = {}
    for a, b in pairs:
        cl.setdefault(b, Counter())[a] += 1
        tl.setdefault(a, Counter())[b] += 1
    # 순도: 같은 화자로 묶인 조각이 한 사람인가 · 덮음: 한 사람의 조각이 한 화자로 묶였나(쪼개짐을 잡는다)
    return (
        sum(c.most_common(1)[0][1] for c in cl.values()) / len(pairs),
        sum(c.most_common(1)[0][1] for c in tl.values()) / len(pairs),
        abs(len(cl) - len(tl)),
    )


def score_scene(parts: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    x, truth = synth.scene(parts, seed=seed)
    f = scene.features(x)
    res = scene.analyze(x)
    tf = synth.frame_truth(truth, len(res["frames"]))
    acc = sum(a == b for a, b in zip(tf, res["frames"], strict=True)) / max(1, len(tf))
    vad = _energy_vad(f)
    # 기준선은 '말 · 침묵'만 알므로 말이 아닌 소리를 모두 틀린다 — 비교는 '소리가 있는가'(침묵 아님)와 종류 둘로
    vad_acc = sum(a == b for a, b in zip(tf, vad, strict=True)) / max(1, len(tf))
    tp, fp, fn = _event_match(res["events"], truth["segments"])
    d = _diar(res["speaker_pieces"], truth)
    by: dict[str, list[int]] = {}
    for a, b in zip(tf, res["frames"], strict=True):
        by.setdefault(a, [0, 0])
        by[a][0] += a == b
        by[a][1] += 1
    return {"frame_acc": round(acc, 3), "vad_acc": round(vad_acc, 3), "by_class": {k: round(v[0] / v[1], 3) for k, v in by.items()}, "tp": tp, "fp": fp, "fn": fn,
            "diar": d, "seconds": truth["seconds"], "res": res, "truth": truth}  # fmt: skip


def evaluate(held_out: int = 40) -> dict[str, Any]:
    p = preset()
    named = {}
    rows = []
    for i, sc in enumerate(p["scenes"]):
        r = score_scene(sc["parts"], seed=i)
        texts = {(s["start"], s["end"]): s["text"] for s in r["truth"]["segments"] if s.get("text")}
        items = describe(r["res"], texts, "정답 글(합성)")
        named[sc["name"]] = (r, items)
        rows.append({"scene": sc["name"], "frame_acc": r["frame_acc"], "vad_acc": r["vad_acc"], "events": f"{r['tp']}/{r['tp'] + r['fn']} (오탐 {r['fp']})",
                     "speakers": len(r["res"]["speakers"]), "true_speakers": len({s["spk"] for s in r["truth"]["segments"] if s["type"] == "speech"}),
                     "summary": summary(items)})  # fmt: skip
    hits = []
    for q in p["queries"]:
        r, items = named[q["scene"]]
        top = search(items, q["q"], 1)
        tsegs = [
            s
            for s in r["truth"]["segments"]
            if (q.get("type") and s["kind"] == q["type"]) or (q.get("text") and q["text"] in (s.get("text") or ""))
        ]
        ok = bool(top) and any(top[0]["start"] < t["end"] and top[0]["end"] > t["start"] for t in tsegs)
        hits.append({"q": q["q"], "scene": q["scene"], "top": top[0]["line"] if top else None, "hit": ok})
    ho = [score_scene(random_parts(1000 + s), seed=1000 + s) for s in range(held_out)]

    def agg(rs: list[dict[str, Any]]) -> dict[str, Any]:
        tp, fp, fn = sum(r["tp"] for r in rs), sum(r["fp"] for r in rs), sum(r["fn"] for r in rs)
        ds = [r["diar"] for r in rs if r["diar"]]
        cls: dict[str, list[float]] = {}
        for r in rs:
            for k, v in r["by_class"].items():
                cls.setdefault(k, []).append(v)
        return {"n": len(rs), "frame_acc": round(sum(r["frame_acc"] for r in rs) / len(rs), 3), "vad_acc": round(sum(r["vad_acc"] for r in rs) / len(rs), 3),
                "by_class": {k: round(sum(v) / len(v), 3) for k, v in cls.items()},
                "event_precision": round(tp / max(1, tp + fp), 3), "event_recall": round(tp / max(1, tp + fn), 3),
                "diar_purity": round(sum(d[0] for d in ds) / len(ds), 3) if ds else None, "diar_coverage": round(sum(d[1] for d in ds) / len(ds), 3) if ds else None,
                "speaker_count_err": round(sum(d[2] for d in ds) / len(ds), 2) if ds else None}  # fmt: skip

    return {"preset": agg([named[s["name"]][0] for s in p["scenes"]]), "held_out": agg(ho), "scenes": rows, "search": hits,
            "search_hit": round(sum(h["hit"] for h in hits) / max(1, len(hits)), 3)}  # fmt: skip
