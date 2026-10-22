"""OM8 옴니 평가: 채널을 바꾸는 시나리오로 맥락 이어짐 · 중복 처리 · 형식 준수 · 채널별 지연 · 채널 간 일관성을 잰다.

채널마다 따로 재면 채널을 넘나들 때 생기는 문제(앞 채널의 사실을 잃음 · 재전송에 답이 두 번 · 채팅 답을 그대로 읽음)를 놓친다.
시나리오의 걸음은 실제 웹훅 모양(envelope.sample)으로 보내고, 처리 · 답 · 렌더 · 전달은 화면과 같은 길(send 함수)을 탄다.
- 맥락 이어짐: 채널을 바꾼 걸음에서 넘김 요약 · 첫 말에 carry 사실이 있나(규칙 채점), 그 걸음의 답에 expect 표기가 있나
- 중복: repeat 로 같은 외부 id 를 다시 보냈을 때 처리 · 답이 한 번만인가
- 형식: 나간 답이 채널 규칙(render.check)을 지키나
- 지연: 첫 응답까지 걸린 시간이 채널 예산(envelope.CHANNELS.budget_ms) 안인가
- 일관성: 같은 group 질문을 다른 채널에서 했을 때 답의 핵심 표기(코드 · 모델 · 숫자)가 겹치는 비율
대기열만의 성질(재전송 · 순서 뒤섞임 · 처리 실패 재시도)은 LLM 없이 drill 로 따로 잰다 — 수백 건을 빠르게 돌릴 수 있게.
"""

import json
import random
import re
import secrets
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.db import OmniIdentity, OmniMessage, OmniSession, utcnow
from app.stages.omni import envelope, queue, render

PRESET = Path(__file__).parent / "presets" / "scenarios.json"
KEY = re.compile(r"[A-Z]{2,4}-\d{2,4}|(?<![A-Za-z0-9])[A-Za-z]{1,2}\d{1,2}(?![A-Za-z0-9])|\d+(?:\.\d+)?\s*(?:분|초|시간|cm|mm|kg|°C|도)")


def scenarios() -> list[dict[str, Any]]:
    return json.loads(PRESET.read_text(encoding="utf-8"))["scenarios"]


def key_terms(text: str) -> set[str]:
    return {re.sub(r"\s", "", m.group(0)).upper() for m in KEY.finditer(text or "")}


def run(items: list[dict[str, Any]], send: Callable[..., dict[str, Any]], brief: Callable[[str, str], dict[str, Any]],
        progress: Callable[[float, str], None] = lambda f, m: None) -> dict[str, Any]:  # fmt: skip
    """send(channel, payload, frame_code) → {duplicate, reply(렌더 결과|None), answer, seconds, session_id}.
    brief(session_id, to_channel) → handoff.brief 결과 + greeting. 시나리오마다 새 고객(주소)을 쓴다."""
    rows, groups = [], {}
    total = sum(len(s["steps"]) for s in items)
    done = 0
    for sc in items:
        tag = secrets.token_hex(3)
        addr = {"web_chat": f"web-{tag}", "messenger": f"tg-{tag}", "kakao": f"kk-{tag}", "email": f"eval-{tag}@example.com"}
        phone = f"010-9{random.Random(tag).randint(100, 999)}-{random.Random(tag + 'x').randint(1000, 9999)}"
        prev_channel, sid = None, None
        for i, st in enumerate(sc["steps"]):
            ch = st["channel"]
            a = phone if ch in envelope.PHONE_CHANNELS else addr[ch]
            ext = f"{sc['id']}-{tag}-{i}"
            payload = envelope.sample(ch, a, st["text"], external_id=ext)
            if ch not in envelope.PHONE_CHANNELS:
                # 메신저 · 카톡형 · 웹 채팅 · 이메일은 계정에 확인된 번호가 있는 고객으로 본다 — 전화 · 문자와 같은 고객으로 이어지는 실제 경로.
                # 주소만 다르고 번호가 없으면 이어지지 않는 것이 맞다(추측으로 묶지 않음) — 그 경우는 같은 세션 비율로 드러난다
                payload["verified_phone"] = phone
            switched = prev_channel is not None and ch != prev_channel
            b = brief(sid, ch) if switched and sid else None
            r = send(ch, payload, st.get("frame"))
            dup_ok = None
            if st.get("repeat"):
                again = [send(ch, payload, st.get("frame")) for _ in range(st["repeat"])]
                dup_ok = all(x["duplicate"] and not x.get("new_reply") for x in again)
            sid = r.get("session_id") or sid
            reply = r.get("reply") or {}
            ans = r.get("answer") or ""
            expect = st.get("expect") or []
            hit = [e for e in expect if e.upper() in (ans + " " + reply.get("text", "")).upper()]
            carry = None
            if st.get("carry"):
                if b is None:
                    b = brief(sid, ch)
                hay = " ".join(
                    [b.get("summary", ""), b.get("facts", ""), b.get("greeting", ""), " ".join(b.get("codes") or []), b.get("product", "")]
                )
                got = [c for c in st["carry"] if c.upper() in hay.upper()]
                carry = {"carried": len(got), "of": len(st["carry"]), "missing": [c for c in st["carry"] if c not in got]}
            budget = envelope.CHANNELS[ch]["budget_ms"]
            ms = round((r.get("seconds") or 0) * 1000)
            violations = render.check(reply, ch) if reply else ["답 없음"]
            row = {"scenario": sc["id"], "step": i, "channel": ch, "text": st["text"], "switched": switched, "session": sid,
                   "expect_hit": len(hit), "expect_of": len(expect), "carry": carry, "dup_ok": dup_ok, "ms": ms, "budget_ms": budget,
                   "in_budget": ms <= budget, "violations": violations, "reply": reply.get("text", "")[:300],
                   "pointer": r.get("pointer"), "same_session": r.get("same_session")}  # fmt: skip
            rows.append(row)
            if st.get("group"):
                groups.setdefault(f"{sc['id']}:{st['group']}", []).append(key_terms(ans))
            prev_channel = ch
            done += 1
            progress(done / max(1, total), f"{sc['id']} {i + 1}/{len(sc['steps'])}")
    cons = []
    for g in groups.values():
        if len(g) >= 2:
            inter, union = set.intersection(*g), set.union(*g)
            cons.append(len(inter) / len(union) if union else 1.0)
    exp = [r for r in rows if r["expect_of"]]
    car = [r["carry"] for r in rows if r["carry"]]
    dup = [r["dup_ok"] for r in rows if r["dup_ok"] is not None]
    switched = [r for r in rows if r["switched"]]

    def ratio(xs: list[Any]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    by_channel: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = by_channel.setdefault(r["channel"], {"n": 0, "ms": [], "in_budget": 0, "format_ok": 0})
        c["n"] += 1
        c["ms"].append(r["ms"])
        c["in_budget"] += r["in_budget"]
        c["format_ok"] += not r["violations"]
    for c in by_channel.values():
        ms = sorted(c.pop("ms"))
        c |= {
            "p50_ms": ms[len(ms) // 2],
            "max_ms": ms[-1],
            "in_budget": round(c["in_budget"] / c["n"], 3),
            "format_ok": round(c["format_ok"] / c["n"], 3),
        }
    summary = {
        "expect": ratio([r["expect_hit"] / r["expect_of"] for r in exp]),
        "carry": ratio([c["carried"] / c["of"] for c in car]),
        "same_session": ratio([bool(r["same_session"]) for r in switched]),
        "dedup": ratio(dup),
        "format_ok": ratio([not r["violations"] for r in rows]),
        "in_budget": ratio([r["in_budget"] for r in rows]),
        "consistency": ratio(cons),
        "steps": len(rows),
    }
    return {"summary": summary, "by_channel": by_channel, "rows": rows}


def drill(db: Session, n: int = 200, dup_rate: float = 0.3, shuffle: float = 0.3, fail_rate: float = 0.2, seed: int = 0) -> dict[str, Any]:
    """대기열 훈련(LLM 없음): 메시지 n 개를 재전송(dup_rate) · 순서 뒤섞임(shuffle) · 처리 실패(fail_rate)를 섞어 보내고,
    고유 메시지마다 처리 한 번 · 답 한 번인지, 보낸 시각 순서로 처리했는지 확인한다. 끝나면 훈련 세션을 지운다."""
    rnd = random.Random(seed)
    s = OmniSession(id="drill-" + secrets.token_hex(5), customer="drill", channels=["messenger"], memory={}, handoffs=[], status="drill")
    db.add(s)
    db.flush()
    t0 = utcnow()
    base = [{"channel": "messenger", "external_id": f"d{seed}-{i}", "address": "drill", "name": "", "kind": "text", "text": f"메시지 {i}",
             "images": [], "at": t0 + timedelta(seconds=i), "meta": {}} for i in range(n)]  # fmt: skip
    stream = []
    for e in base:
        stream.append(e)
        while rnd.random() < dup_rate:
            stream.append(e)  # 웹훅 재전송 — 같은 외부 id
    for i in range(len(stream) - 1):  # 이웃끼리 바꿔 순서 뒤섞임(네트워크 지연)
        if rnd.random() < shuffle:
            stream[i], stream[i + 1] = stream[i + 1], stream[i]
    processed: list[str] = []
    dups = sends = retries = 0

    def handler(m: OmniMessage) -> dict[str, Any]:
        if rnd.random() < fail_rate:
            raise RuntimeError("일시 오류(훈련)")
        processed.append(m.external_id)
        return {"text": f"답: {m.text}"}

    for e in stream:
        _, dup = queue.accept(db, s, e)
        dups += dup
        # 받을 때마다 대기 중인 것을 보낸 시각 순서로 처리(실제로는 일꾼이 주기적으로) — 실패한 것은 다음 차례에 다시
        for m in queue.pending(db, s.id):
            out = queue.process(db, m, handler)
            if out is None:
                # 한 세션 안에서는 앞 메시지가 처리될 때까지 뒤 메시지를 멈춘다 — 건너뛰면 '문이 안 열려요' 보다 '그럼 어떻게 해요?' 에 먼저 답한다
                retries += 1
                break
            _, new = queue.deliver(db, s, m, "messenger", render.render(out["text"], "messenger"))
            sends += new
            # 같은 처리를 다시 해도(일꾼이 두 번 집어 감) 답은 한 번 — 전달 멱등 확인
            _, again = queue.deliver(db, s, m, "messenger", render.render(out["text"], "messenger"))
            sends += again
    for _ in range(queue.MAX_ATTEMPTS):  # 남은 재시도
        for m in queue.pending(db, s.id):
            if (out := queue.process(db, m, handler)) is None:
                break
            sends += queue.deliver(db, s, m, "messenger", render.render(out["text"], "messenger"))[1]
    st = queue.stats(db, s.id)
    uniq = len(base)
    # 순서: 뒤섞여 늦게 온 메시지는 이미 뒤 메시지가 처리된 뒤라 순서를 지킬 수 없다(late 로 표시) — 그것을 뺀 나머지가 보낸 시각 순서인가
    late = {m.external_id for m in queue.history(db, s.id, limit=10 * n) if (m.meta or {}).get("late")}
    seq = [int(x.rsplit("-", 1)[1]) for x in processed if x not in late]
    order_ok = seq == sorted(seq)
    out = {"messages": uniq, "received": len(stream), "duplicates": dups, "processed": len(processed), "processed_unique": len(set(processed)),
           "replies": sends, "retries": retries, "failed": st.get("in:failed", 0), "late": st.get("late", 0),
           "exactly_once": len(processed) == len(set(processed)) and sends == len(set(processed)),
           "in_order": order_ok}  # fmt: skip
    db.execute(delete(OmniMessage).where(OmniMessage.session_id == s.id))
    db.execute(delete(OmniSession).where(OmniSession.id == s.id))
    db.execute(delete(OmniIdentity).where(OmniIdentity.customer == "drill"))
    db.commit()
    return out
