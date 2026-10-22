"""VD5~VD8 시간축 색인 · 시간 추론 · 검색: 장면 · 추적 · 소리 사건을 한 시간축에 모으고, '처음 · 마지막 · 몇 번 · 무엇 다음'을 계산한다.

시간 질문을 LLM 이 영상 기록을 읽고 답하게 하면, 기록이 길수록 '처음'과 '두 번째'를 헷갈리고 횟수를 틀리게 센다(세는 것은 언어 모델이
약한 일). 그래서 질문을 (무엇이 · 어떤 일 · 연산)으로 풀고, 연산은 색인 위에서 계산한다. 답에는 근거 사건과 앞뒤 클립 구간을 붙인다.
LLM 은 색인으로 풀 수 없는 질문(어떤 모양이었나 등)에만 쓴다. 비교 기준으로 '기록 전체를 LLM 에 주고 묻기'를 같은 질문으로 잰다.
"""

import json
import random
import re
from typing import Any

from app.core import llm
from app.stages.audio import scene as au_scene
from app.stages.video import synth, track

TYPE_LABEL = {"scene_cut": "장면 전환", "appear": "나타남", "disappear": "사라짐", "touch": "닿음", "speech": "말", "beep": "경고음", "thump": "덜컹",
              "hum": "웅웅", "music": "음악"}  # fmt: skip
SOUND_TYPES = {"speech", "beep", "thump", "hum", "music"}
# 질문 낱말 → 사건 종류. '보이다'는 나타남, '울리다 · 나다'는 소리
VERBS = [(r"나타|보이|등장|들어", "appear"), (r"사라|없어|나가", "disappear"), (r"닿|부딪|만나", "touch"), (r"장면.*(바뀌|바뀐|전환)|컷|화면이 바뀌|화면이 바뀐", "scene_cut"),
         (r"경고음|삐", "beep"), (r"덜컹|쿵", "thump"), (r"말(을|한|했)|목소리|대화", "speech")]  # fmt: skip


def build(frames: list[tuple[float, Any]], audio_x: Any = None, palette: dict[str, tuple[int, int, int]] | None = None) -> dict[str, Any]:
    """VD5 · VD7: 컷 · 트랙 · 소리 사건 → 시간 순 사건 목록. 소리 트랙은 오디오 맵(AU2 · AU4)으로 나눈다."""
    # None = 시험 영상의 색표, {} = 색 탐지 끔(실제 영상 — 색 탐지는 시험 영상용)
    pal = {k: v[0] for k, v in synth.OBJECTS.items()} if palette is None else palette
    cs = track.cuts(frames)
    tr = track.track(frames, pal)
    ev = [{"type": "scene_cut", "t": c["t"], "subject": f"장면 {i + 2}", "source": "영상"} for i, c in enumerate(cs)]
    ev += [e | {"source": "추적"} for e in tr["events"]]
    if audio_x is not None and len(audio_x):
        a = au_scene.analyze(audio_x)
        ev += [{"type": s["type"], "t": s["start"], "end": s["end"], "subject": s.get("speaker") or TYPE_LABEL[s["type"]], "source": "소리"}
               for s in a["segments"] if s["type"] in ("speech", "music")]  # fmt: skip
        ev += [
            {"type": e["type"], "t": e["start"], "end": e["end"], "subject": au_scene.EVENT_LABEL[e["type"]], "source": "소리"}
            for e in a["events"]
        ]
    ev.sort(key=lambda e: e["t"])
    shots = [0.0] + [c["t"] for c in cs]
    dur = frames[-1][0] + (frames[1][0] - frames[0][0] if len(frames) > 1 else 0) if frames else 0.0
    keyframes = [{"shot": i + 1, "start": s, "end": (shots[i + 1] if i + 1 < len(shots) else dur), "t": round((s + (shots[i + 1] if i + 1 < len(shots) else dur)) / 2, 1)}
                 for i, s in enumerate(shots)]  # fmt: skip
    return {"events": ev, "tracks": tr["tracks"], "cuts": cs, "keyframes": keyframes, "duration": dur}


def parse(q: str, names: list[str]) -> dict[str, Any]:
    """질문 → {subject, type, op, anchor?}. 'X 다음에 처음 Y' · 'X 전에 마지막 Y' 는 기준 사건(anchor)을 따로 푼다."""
    m = re.search(r"(.+?)\s*(다음에|뒤에|후에|이후|전에|이전)\s*(.+)", q)
    if m:
        anchor = parse(m.group(1), names)
        rest = parse(m.group(3), names)
        return rest | {"anchor": anchor, "relation": "after" if m.group(2) in ("다음에", "뒤에", "후에", "이후") else "before"}
    subj = next((n for n in names if n in q), None)
    typ = next((t for rx, t in VERBS if re.search(rx, q)), None)
    if typ in SOUND_TYPES | {"scene_cut"}:
        subj = None
    op = "count" if re.search(r"몇 ?번|몇 ?회|횟수", q) else "last" if re.search(r"마지막|맨 끝", q) else "first"
    return {"subject": subj, "type": typ, "op": op}


def _match(e: dict[str, Any], p: dict[str, Any]) -> bool:
    if p.get("type") and e["type"] != p["type"]:
        return False
    return not p.get("subject") or p["subject"] in (e.get("subject"), e.get("object"))


def answer(idx: dict[str, Any], q: str) -> dict[str, Any]:
    names = list(synth.OBJECTS)
    p = parse(q, names)
    if not p.get("type") and not p.get("subject"):
        return {"q": q, "parsed": p, "answer": None, "reason": "무엇을 묻는지 색인 낱말로 풀지 못함 — LLM 으로 넘길 질문"}
    ev = [e for e in idx["events"] if _match(e, p)]
    if p.get("anchor"):
        anc = [e for e in idx["events"] if _match(e, p["anchor"])]
        if not anc:
            return {"q": q, "parsed": p, "answer": None, "reason": "기준 사건이 색인에 없음"}
        t0 = anc[0]["t"] if p["anchor"].get("op") != "last" else anc[-1]["t"]
        ev = [e for e in ev if e["t"] > t0] if p["relation"] == "after" else [e for e in ev if e["t"] < t0]
        if p["relation"] == "before" and p["op"] == "first":
            p["op"] = "last"  # 'X 전에 Y' 는 X 에 가장 가까운(마지막) Y 를 뜻한다
    if p["op"] == "count":
        return {"q": q, "parsed": p, "answer": len(ev), "evidence": ev[:10], "clips": [[max(0, e["t"] - 1), e["t"] + 2] for e in ev[:10]]}
    if not ev:
        return {"q": q, "parsed": p, "answer": None, "reason": "해당 사건 없음", "evidence": []}
    e = ev[0] if p["op"] == "first" else ev[-1]
    return {"q": q, "parsed": p, "answer": e["t"], "evidence": [e], "clips": [[max(0, e["t"] - 1), e["t"] + 2]]}


def log_text(idx: dict[str, Any]) -> str:
    """LLM 비교용 기록: 사건을 시간 순 한 줄씩(색인과 같은 정보 — 계산을 LLM 이 하느냐만 다르게)."""
    return "\n".join(
        f"{e['t']:.1f}초 {TYPE_LABEL.get(e['type'], e['type'])}: {e.get('subject', '')}{' ↔ ' + e['object'] if e.get('object') else ''}"
        for e in idx["events"]
    )


def llm_answer(lcfg: llm.LLMConfig, idx: dict[str, Any], q: str) -> dict[str, Any]:
    sys = '영상 사건 기록을 보고 질문에 답합니다. 반드시 JSON 만: 시각을 묻으면 {"t": 초}, 횟수를 묻으면 {"count": 수}, 없으면 {"t": null}.'
    r = llm.chat(lcfg, sys, f"기록:\n{log_text(idx)}\n\n질문: {q}", 120, 0.0, json_mode=True)
    try:
        d = llm.parse_json(r["text"])
    except llm.LLMError, ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    v = d.get("count", d.get("t"))
    try:
        v = float(v) if v is not None else None
    except TypeError, ValueError:
        v = None
    return {"answer": v, "raw": r["text"][:120], "seconds": r.get("seconds")}


def _i(word: str) -> str:
    """이/가 — 받침이 있으면 '이'."""
    ch = word[-1]
    return word + ("이" if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "가")


def _e(word: str) -> str:
    return word + "에"


def questions(p: dict[str, Any], truth: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """정답 사건에서 질문을 만든다: 처음 · 마지막 · 몇 번 · 'X 다음에 처음 Y' · 'X 전에 마지막 Y'."""
    r = random.Random(seed)
    out = []
    objs = sorted({e["subject"] for e in truth if e["type"] == "appear"})
    for o in objs:
        ap = [e["t"] for e in truth if e["type"] == "appear" and e["subject"] == o]
        out.append({"q": f"{_i(o)} 처음 나타난 때는?", "gold": ap[0], "kind": "처음"})
        out.append({"q": f"{_i(o)} 몇 번 나타났나?", "gold": len(ap), "kind": "몇 번"})
        dis = [e["t"] for e in truth if e["type"] == "disappear" and e["subject"] == o]
        if dis:
            out.append({"q": f"{_i(o)} 마지막으로 사라진 때는?", "gold": dis[-1], "kind": "마지막"})
    touches = [e for e in truth if e["type"] == "touch"]
    if touches:
        a, b = touches[0]["subject"], touches[0]["object"]
        out.append({"q": f"{_i(a)} {_e(b)} 처음 닿은 때는?", "gold": touches[0]["t"], "kind": "처음"})
    for snd, word in (("beep", "경고음"), ("thump", "덜컹 소리")):
        ts = [e["t"] for e in truth if e["type"] == snd]
        if ts:
            out.append({"q": f"{_i(word)} 처음 울린 때는?", "gold": ts[0], "kind": "처음"})
    cuts = [e["t"] for e in truth if e["type"] == "scene_cut"]
    out.append({"q": "장면이 몇 번 바뀌었나?", "gold": len(cuts), "kind": "몇 번"})
    if cuts and objs:
        o = r.choice(objs)
        after = [e["t"] for e in truth if e["type"] == "appear" and e["subject"] == o and e["t"] > cuts[0]]
        if after:
            out.append({"q": f"장면이 처음 바뀐 다음에 {_i(o)} 처음 나타난 때는?", "gold": after[0], "kind": "다음"})
        before = [e["t"] for e in truth if e["type"] == "appear" and e["subject"] == o and e["t"] < cuts[-1]]
        if before:
            out.append({"q": f"장면이 마지막으로 바뀌기 전에 {_i(o)} 나타난 마지막 때는?", "gold": before[-1], "kind": "전"})
    return out


def correct(q: dict[str, Any], got: float | None) -> bool:
    if got is None:
        return False
    return int(round(got)) == q["gold"] if q["kind"] == "몇 번" else abs(got - q["gold"]) <= 1.0


def evaluate(n: int = 10, lcfg: llm.LLMConfig | None = None, progress=lambda f, m: None) -> dict[str, Any]:
    """영상 n 개(씨앗 200~): 컷 · 사건 찾기 정확, 질문 정답률 — 색인 계산(찾은 색인 · 정답 색인) vs 기록 전체를 LLM 에(lcfg 가 있을 때)."""
    rows, det = [], {"cut_tp": 0, "cut_fp": 0, "cut_fn": 0, "ev_tp": 0, "ev_fn": 0, "ev_fp": 0}
    for k in range(n):
        sd = 200 + k
        progress(k / n, f"영상 {k + 1}/{n}")
        p = synth.plan(sd)
        fr = synth.frames(p)
        idx = build(fr, synth.audio_track(p))
        truth = synth.truth_events(p)
        gold_idx = {"events": [e | {"source": "정답"} for e in truth]}
        # 찾기 정확: 같은 종류 · 같은 대상 · 1초 안
        for typ in ("scene_cut", "appear", "disappear", "touch", "beep", "thump", "speech"):
            ts = [e for e in truth if e["type"] == typ]
            ps = [e for e in idx["events"] if e["type"] == typ]
            used = set()
            for e in ts:
                j = next(
                    (
                        j
                        for j, x in enumerate(ps)
                        if j not in used
                        and abs(x["t"] - e["t"]) <= 1.0
                        and (typ in SOUND_TYPES | {"scene_cut"} or x.get("subject") == e.get("subject"))
                    ),
                    None,
                )
                if j is None:
                    det["cut_fn" if typ == "scene_cut" else "ev_fn"] += 1
                else:
                    used.add(j)
                    det["cut_tp" if typ == "scene_cut" else "ev_tp"] += 1
            det["cut_fp" if typ == "scene_cut" else "ev_fp"] += len(ps) - len(used)
        for q in questions(p, truth, sd):
            a = answer(idx, q["q"])
            g = answer(gold_idx, q["q"])
            row = {"video": sd, "q": q["q"], "kind": q["kind"], "gold": q["gold"], "index": a["answer"], "index_ok": correct(q, a["answer"]),
                   "gold_index_ok": correct(q, g["answer"])}  # fmt: skip
            if lcfg is not None:
                la = llm_answer(lcfg, idx, q["q"])
                row |= {"llm": la["answer"], "llm_ok": correct(q, la["answer"]), "llm_s": la["seconds"]}
            rows.append(row)
    kinds = sorted({r["kind"] for r in rows})

    def rate(rs: list[dict[str, Any]], k: str) -> float | None:
        vs = [r[k] for r in rs if k in r]
        return round(sum(vs) / len(vs), 3) if vs else None

    by = {k: {"n": sum(r["kind"] == k for r in rows), "index": rate([r for r in rows if r["kind"] == k], "index_ok"),
              "gold_index": rate([r for r in rows if r["kind"] == k], "gold_index_ok"), "llm": rate([r for r in rows if r["kind"] == k], "llm_ok")} for k in kinds}  # fmt: skip
    pr = lambda tp, fp, fn: {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3)}  # noqa: E731
    return {"videos": n, "questions": len(rows), "cuts": pr(det["cut_tp"], det["cut_fp"], det["cut_fn"]), "events": pr(det["ev_tp"], det["ev_fp"], det["ev_fn"]),
            "index": rate(rows, "index_ok"), "gold_index": rate(rows, "gold_index_ok"), "llm": rate(rows, "llm_ok"), "by_kind": by, "rows": rows,
            "model": lcfg.model if lcfg else None}  # fmt: skip


def dumps(idx: dict[str, Any]) -> str:
    return json.dumps(idx, ensure_ascii=False)
