"""RT1~RT8 실시간 스트림 재생기: 같은 발화 스트림을 지터 · 손실 · 끊김을 섞어 다시 틀며 단계별 지연 분포 · 복구율을 잰다.

실시간은 평균이 아니라 꼬리(p95 · p99)와 끊김에서 무너진다. 그래서 하나의 턴을 여러 씨앗으로 수백 번 다시 틀어 분포를 본다.
각 부품은 이미 있는 것을 쓴다. 부분 인식 확정은 옴니채널의 연속 일치 규칙(OM2 Stabilizer)과 인식기 흉내(simulate)를,
대화 상태는 대화 메모리 갱신(C3)을, 지연 예산은 음성 짧은 지연 RAG(VC3)의 몫을 쓴다.

시간 흐름(한 턴, ms):
  말하기(낱말마다 word_ms) → 조각(chunk_ms)마다 보냄 → 망: 지연 = 기본 + 지터(로그 정규), 손실이면 재전송(rtt 뒤) 또는 포기
  → 받는 쪽 지터 버퍼(target_ms 만큼 모아 순서대로 내보냄, 늦은 조각은 버퍼가 기다린 만큼 늦게) → 조각마다 인식(stt_ms)
  → 가설 → 확정(agree) → 상태 갱신 → 문장 끝이 확정되면 검색 미리 시작(early)
  → 끝점(말 끝 + endpoint_ms) → 첫 토큰(ttft) → 첫 문장 → 첫 합성 → 첫 소리
끼어들기(RT7): 답을 듣는 중 고객이 말하면 감지(barge_ms) + 취소가 서버까지 가는 망 지연 동안 소리가 더 나간다(멈춤 지연).
세션 복구(RT8): 말하는 도중 연결이 끊겼다 다시 붙는다. 상태를 어디 두는지(전략)에 따라 잃는 낱말 · 겹치는 낱말을 센다.

가짜로 만든 것: 망 · 인식기 · LLM 시간은 분포로 흉내 낸다(씨앗이 같으면 같은 결과). LLM 시간은 실측(live.py)으로 바꿔 넣을 수 있다.
"""

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from app.stages.conversation import memory as cv_mem
from app.stages.omni import realtime as om_rt

STAGES = ("network", "jitter_buffer", "stt", "endpoint", "ttft", "first_sentence", "tts")
LABELS = {"network": "망", "jitter_buffer": "지터 버퍼", "stt": "인식", "endpoint": "끝점 대기", "ttft": "첫 토큰", "first_sentence": "첫 문장",
          "tts": "첫 합성"}  # fmt: skip


@dataclass
class Net:
    base_ms: float = 40.0  # 편도 기본 지연
    jitter_ms: float = 30.0  # 지터 크기(로그 정규의 중앙값 근처)
    loss: float = 0.0  # 조각 손실 확률
    retransmit: bool = True  # 손실 조각을 rtt 뒤 다시 보냄(아니면 그 조각의 낱말은 인식기가 못 들음)


@dataclass
class Params:
    chunk_ms: int = 250
    word_ms: int = 330  # 한국어 상담 발화 낱말(어절) 하나 ≈ 0.3초
    buffer_ms: int = 60  # 지터 버퍼 목표(조각을 이만큼 모았다 순서대로)
    stt_base_ms: float = 60.0  # 조각 하나 인식 고정 비용
    stt_per_s: float = 120.0  # 소리 1초당 인식 비용
    agree: int = 2
    noise: float = 0.4  # 인식기 잠정 꼬리가 틀릴 확률(OM2 simulate)
    endpoint_ms: int = 500  # 말 끝 뒤 침묵 확인(VC2 short_ms)
    ttft_ms: float = 600.0  # 첫 토큰(중앙값) — live 실측으로 바꿀 수 있음
    ttft_sigma: float = 0.35  # 로그 정규 퍼짐
    tok_ms: float = 80.0  # 토큰 사이(12.5 토큰/초)
    first_sentence_tokens: int = 14
    tts_ms: float = 180.0  # 첫 문장 합성
    early_retrieval: bool = True
    barge_ms: int = 200  # 끼어들기 감지(VC2 barge_ms)
    cancel_mode: str = "server"  # server: 취소가 서버까지 가야 멈춤 · client: 기기에서 바로 재생 멈춤
    net: Net = field(default_factory=Net)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _lat(rnd: random.Random, net: Net) -> float:
    # 지터는 오른쪽 꼬리가 긴 분포 — 대부분 작고 가끔 크다(정규 분포로 두면 p99 를 낮게 잡는다)
    return net.base_ms + (rnd.lognormvariate(math.log(max(1.0, net.jitter_ms)), 0.8) if net.jitter_ms > 0 else 0.0)


def chunks(n_words: int, p: Params) -> list[dict[str, Any]]:
    """말하기 → 조각: 조각마다 보낸 시각(조각 끝)과 그 안에서 끝나는 낱말."""
    speech_ms = n_words * p.word_ms
    out = []
    t = 0
    while t < speech_ms:
        end = min(t + p.chunk_ms, speech_ms)
        words = [i for i in range(n_words) if t < (i + 1) * p.word_ms <= end]
        out.append({"i": len(out), "start": t, "sent": end, "words": words, "ms": end - t})
        t = end
    return out


def deliver(cs: list[dict[str, Any]], p: Params, rnd: random.Random) -> list[dict[str, Any]]:
    """RT1 · RT2 망 + 지터 버퍼: 조각마다 도착 · 버퍼에서 나간 시각. 순서는 지킨다(앞 조각이 늦으면 뒤도 기다림)."""
    rtt = 2 * p.net.base_ms
    played = 0.0
    out = []
    for c in cs:
        arrive = c["sent"] + _lat(rnd, p.net)
        lost = rnd.random() < p.net.loss
        if lost and p.net.retransmit:
            arrive += rtt + _lat(rnd, p.net)  # 받는 쪽이 빠진 번호를 알리고(NACK) 다시 받는 데 왕복 + 편도
        ready = arrive + p.buffer_ms
        out_t = max(ready, played)  # 순서대로 내보내므로 앞 조각보다 먼저 나갈 수 없다
        played = out_t
        out.append(c | {"arrive": round(arrive, 1), "out": round(out_t, 1), "lost": lost, "dropped": lost and not p.net.retransmit})
    return out


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return round(s[k], 1)


def dist(xs: list[float]) -> dict[str, float | None]:
    return {
        "p50": _pct(xs, 0.5),
        "p95": _pct(xs, 0.95),
        "p99": _pct(xs, 0.99),
        "mean": round(sum(xs) / len(xs), 1) if xs else None,
        "n": len(xs),
    }


def turn(text: str, p: Params, seed: int, known_models=(), known_codes=()) -> dict[str, Any]:
    """한 턴 재생: 조각 → 망 → 인식 가설(조각마다) → 확정 → 상태 → 끝점 → 답 첫 소리. 단계별 시간과 품질 지표."""
    rnd = random.Random(seed)
    words = text.split()
    cs = deliver(chunks(len(words), p), p, rnd)
    hyps_all = om_rt.simulate(text, seed=seed, noise=p.noise)  # 낱말 하나 늘 때마다 가설 하나(마지막은 최종)
    st = om_rt.Stabilizer(p.agree)
    mem = cv_mem.empty()
    heard = 0  # 인식기가 지금까지 들은 낱말 수
    stt_free = 0.0  # 인식기가 다음 조각을 받을 수 있는 시각(조각을 차례로 처리)
    early_at = None
    state_updates = []
    dropped_words: set[int] = set()
    t_last = 0.0
    for c in cs:
        start = max(c["out"], stt_free)
        done = start + p.stt_base_ms + p.stt_per_s * c["ms"] / 1000
        stt_free = done
        t_last = done
        if c["dropped"]:
            dropped_words |= set(c["words"])
        if not c["words"]:
            continue
        heard = c["words"][-1] + 1
        hyp = hyps_all[min(heard, len(hyps_all)) - 1]
        if dropped_words:  # 못 들은 낱말은 가설에서 빠진다(재전송을 끈 손실)
            hyp = " ".join(w for i, w in enumerate(hyp.split()) if i not in dropped_words)
        r = st.push(hyp)
        if r["new"]:
            new_mem = cv_mem.update(mem, "user", r["committed"], known_models, known_codes)
            if {k: new_mem.get(k) for k in ("product_model", "codes")} != {k: mem.get(k) for k in ("product_model", "codes")}:
                state_updates.append({"at": round(done, 1), "product": new_mem.get("product_model"), "codes": new_mem.get("codes")})
            mem = new_mem
        if r["early"] and early_at is None:
            early_at = done
    speech_end = len(words) * p.word_ms
    final_hyp = " ".join(w for i, w in enumerate(words) if i not in dropped_words)
    fin = st.push(final_hyp, final=True)
    # 끝점에서 남은 잠정 부분까지 확정되므로 상태도 한 번 더 — 이것을 빼면 확정이 늦은 설정(agree 가 큰)일수록 상태가 덜 찬 채로 채점된다
    mem = cv_mem.update(mem, "user", fin["committed"], known_models, known_codes) if fin["new"] else mem
    final_mem = cv_mem.update(cv_mem.empty(), "user", text, known_models, known_codes)
    # 끝점: 서버가 말 끝 뒤 침묵을 endpoint_ms 들어야 끝으로 본다 — 침묵 조각도 망 · 버퍼를 지나오므로 마지막 조각의 지연만큼 늦게 안다
    tail_delay = (cs[-1]["out"] - cs[-1]["sent"]) if cs else 0.0
    endpoint_at = max(speech_end + tail_delay + p.endpoint_ms, t_last)
    # 검색 · 미리 채우기를 문장 끝 확정 때 시작했으면 끝점 뒤에는 남은 몫만(검색 120ms 를 앞당김)
    retrieve_ms = 120.0
    saved = min(retrieve_ms, max(0.0, endpoint_at - early_at)) if (p.early_retrieval and early_at is not None) else 0.0
    ttft = rnd.lognormvariate(math.log(p.ttft_ms), p.ttft_sigma)
    first_sentence = p.first_sentence_tokens * p.tok_ms * rnd.uniform(0.8, 1.2)
    tts = p.tts_ms * rnd.uniform(0.85, 1.3)
    answer_start = endpoint_at + retrieve_ms - saved
    first_token_at = answer_start + ttft
    first_sound_at = first_token_at + first_sentence + tts + _lat(rnd, p.net)  # 소리가 고객에게 가는 편도
    net_ms = sum(c["arrive"] - c["sent"] for c in cs) / max(1, len(cs))
    buf_ms = sum(c["out"] - c["arrive"] for c in cs) / max(1, len(cs))
    return {
        "first_sound_ms": round(first_sound_at - speech_end, 1),  # 말이 끝난 뒤 첫 소리까지(사람이 느끼는 지연)
        "first_token_ms": round(first_token_at - speech_end, 1),
        "stages": {
            "network": round(net_ms, 1),
            "jitter_buffer": round(buf_ms, 1),
            "stt": round(max(0.0, t_last - (cs[-1]["out"] if cs else 0)), 1),
            "endpoint": round(endpoint_at - speech_end, 1),
            "ttft": round(ttft, 1),
            "first_sentence": round(first_sentence, 1),
            "tts": round(tts, 1),
        },  # fmt: skip
        "early_saved_ms": round(saved, 1),
        "commit_errors": sum(1 for i, w in enumerate(fin["committed"].split()) if i >= len(words) or words[i] != w),
        "flicker": st.flicker,
        "lost_chunks": sum(c["lost"] for c in cs),
        "dropped_words": len(dropped_words),
        "state_ok": (mem.get("product_model") == final_mem.get("product_model"))
        and sorted(mem.get("codes") or []) == sorted(final_mem.get("codes") or []),
        "state_updates": state_updates,
        "speech_ms": speech_end,
    }


def barge(p: Params, seed: int, answer_ms: float = 6000.0) -> dict[str, Any]:
    """RT7: 답 재생 중 끼어들기 — 고객이 말을 시작한 뒤 소리가 멈출 때까지(멈춤 지연)와, 멈춘 뒤까지 나간 소리(겹친 소리 ms)."""
    rnd = random.Random(seed)
    t_barge = rnd.uniform(500, answer_ms - 500)
    detect = p.barge_ms + p.chunk_ms * rnd.random()  # 끼어들기는 조각 단위로 보이므로 조각 길이만큼 늦을 수 있다
    if p.cancel_mode == "client":
        stop = detect  # 기기가 스스로 재생을 멈춘다(서버는 뒤따라 생성 · 합성을 멈춤)
    else:
        # 감지(서버) → 고객 쪽 소리 버퍼는 이미 받은 만큼 계속 재생: 감지까지 + 망 편도(취소) + 기기 재생 버퍼
        stop = detect + _lat(rnd, p.net) + _lat(rnd, p.net) + p.buffer_ms
    heard_sentences = int(t_barge // 1800)  # 한 문장 ≈ 1.8초 — 끼어들기 전에 끝까지 들은 문장만 '들었다'로 남김
    # 멈출 때까지 고객의 말과 답 소리가 겹친다 — 겹친 시간 = 멈춤 지연(그동안 고객은 자기 말이 안 들린다고 느낌)
    return {"stop_ms": round(stop, 1), "heard_sentences": heard_sentences, "barge_at": round(t_barge, 1)}


def recover(text: str, p: Params, seed: int, strategy: str, cut_s: float = 1.0) -> dict[str, Any]:
    """RT8: 말하는 도중 연결이 cut_s 초 끊겼다 다시 붙는다.

    전략: none(다시 붙으면 새 세션 — 서버가 확정한 것도 잃음) · server(서버가 확정한 낱말을 들고 있다 이어 감, 끊긴 동안 말한 소리는 잃음)
    · server+replay(기기가 보내고 확인받지 못한 소리를 들고 있다 다시 보냄 — 잃는 것 없음, 대신 이미 받은 조각을 다시 받으면 겹침).
    """
    rnd = random.Random(seed)
    words = text.split()
    n = len(words)
    cut_at = rnd.uniform(0.25, 0.75) * n * p.word_ms
    cut_end = cut_at + cut_s * 1000
    said_before = [i for i in range(n) if (i + 1) * p.word_ms <= cut_at]
    said_during = [i for i in range(n) if cut_at < (i + 1) * p.word_ms <= cut_end]
    one_way = _lat(rnd, p.net)
    # 끊기기 직전 편도 지연 안에 보낸 낱말은 서버에 닿지 못했다. 그 앞 왕복 안에 보낸 낱말은 서버가 받았지만 확인(ACK)이 기기에 못 왔다
    server_got = [i for i in said_before if (i + 1) * p.word_ms <= cut_at - one_way]
    client_acked = [i for i in said_before if (i + 1) * p.word_ms <= cut_at - 2 * one_way]
    after = [i for i in range(n) if (i + 1) * p.word_ms > cut_end]
    resent: list[int] = []
    if strategy == "none":
        kept = after  # 새 세션 — 서버가 받은 것도 이어 쓰지 못한다
    elif strategy == "server":
        kept = server_got + after  # 끊긴 동안 말한 것 · 떠 있던 것은 잃는다
    else:
        # 기기가 확인받지 못한 소리(끊긴 동안 녹음한 것 포함)를 다시 보낸다 — 잃는 것은 없다
        resent = [i for i in range(n) if i not in client_acked and i not in after]
        kept = list(range(n))
    lost = n - len(set(kept))
    # 순번 없이 다시 보내면 서버가 이미 받은 낱말을 또 받는다(겹침) — 조각 순번으로 거르면 0
    dup_no_seq = len(set(resent) & set(server_got))
    return {"strategy": strategy, "lost_words": lost, "lost_share": round(lost / max(1, n), 3), "recovered": lost == 0, "resent_words": len(resent),
            "dup_if_no_seq": dup_no_seq, "said_during_cut": len(said_during)}  # fmt: skip


def run(utterances: list[str], p: Params, seeds: int = 50, known_models=(), known_codes=(), cut_s: float = 1.0) -> dict[str, Any]:
    turns = [turn(u, p, s * 1000 + i, known_models, known_codes) for i, u in enumerate(utterances) for s in range(seeds)]
    fs = [t["first_sound_ms"] for t in turns]
    # 끼어들기는 두 방식을 같은 씨앗으로 — 서버가 감지해 취소를 보내는 방식과 기기가 스스로 재생을 멈추는 방식
    bar = {m: [barge(_with(p, cancel_mode=m), s) for s in range(seeds * 2)] for m in ("server", "client")}
    rec = {
        st: [recover(u, p, s * 1000 + i, st, cut_s) for i, u in enumerate(utterances) for s in range(seeds)]
        for st in ("none", "server", "server+replay")
    }
    n = max(1, len(turns))
    return {
        "params": p.to_dict(),
        "n_turns": len(turns),
        "first_sound": dist(fs),
        "first_token": dist([t["first_token_ms"] for t in turns]),
        "stages": {k: dist([t["stages"][k] for t in turns]) for k in STAGES},
        "early_saved": dist([t["early_saved_ms"] for t in turns]),
        "commit_errors": round(sum(t["commit_errors"] for t in turns) / n, 3),
        "flicker": round(sum(t["flicker"] for t in turns) / n, 2),
        "state_ok": round(sum(t["state_ok"] for t in turns) / n, 3),
        "dropped_words": round(sum(t["dropped_words"] for t in turns) / n, 2),
        "lost_chunks": round(sum(t["lost_chunks"] for t in turns) / n, 2),
        "over_budget_1200": round(sum(x > 1200 for x in fs) / n, 3),
        "barge": {m: dist([b["stop_ms"] for b in bs]) for m, bs in bar.items()},
        "recover": {
            st: {
                "recovery_rate": round(sum(r["recovered"] for r in rs) / max(1, len(rs)), 3),
                "lost_share": round(sum(r["lost_share"] for r in rs) / max(1, len(rs)), 3),
                "resent_words": round(sum(r["resent_words"] for r in rs) / max(1, len(rs)), 2),
                "dup_if_no_seq": round(sum(r["dup_if_no_seq"] for r in rs) / max(1, len(rs)), 2),
            }
            for st, rs in rec.items()
        },  # fmt: skip
        "labels": LABELS,
    }


def sweep(utterances: list[str], base: Params, networks: dict[str, dict[str, Any]], chunk_ms: list[int], buffer_ms: list[int], seeds: int = 30,
          known_models=(), known_codes=()) -> dict[str, Any]:  # fmt: skip
    """망 조건 × 조각 길이 × 지터 버퍼 — 칸마다 첫 소리 p50 · p95 · p99 · 예산 초과 · 확정 오류 · 상태 정확."""
    rows = []
    for nname, nv in networks.items():
        for cm in chunk_ms:
            for bm in buffer_ms:
                p = _copy(base)
                p.chunk_ms, p.buffer_ms, p.net = cm, bm, Net(**nv)
                r = run(utterances, p, seeds, known_models, known_codes)
                rows.append({"network": nname, "chunk_ms": cm, "buffer_ms": bm, "first_sound": r["first_sound"], "over_budget_1200": r["over_budget_1200"],
                             "commit_errors": r["commit_errors"], "state_ok": r["state_ok"], "dropped_words": r["dropped_words"],
                             "stages_p95": {k: v["p95"] for k, v in r["stages"].items()}, "barge_stop_p95": r["barge"][p.cancel_mode]["p95"]})  # fmt: skip
    return {"rows": rows, "labels": LABELS}


def _with(p: Params, **kw: Any) -> Params:
    q = _copy(p)
    for k, v in kw.items():
        setattr(q, k, v)
    return q


def _copy(p: Params) -> Params:
    d = p.to_dict()
    net = Net(**d.pop("net"))
    return Params(**d, net=net)
