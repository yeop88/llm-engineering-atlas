"""OM5 채널 간 이어 가기: 채널을 바꿀 때 넘길 것(요약 · 사실 · 이미 한 조치 · 미해결 질문 · 다음 할 일)을 정해 두고, 새 채널의 첫 말에 쓴다.

전화로 바꿨더니 처음부터 다시 묻는 것이 옴니채널에서 가장 큰 불만이다. 넘김 요약은 LLM 없이도 만들 수 있게 규칙이 먼저다:
사실(제품 · 코드 · 증상 · 안내한 조치)은 대화 메모리(C3)에서, 미해결 질문은 '고객이 물었는데 답이 안 나갔거나(처리 실패 · 대기)
답이 근거 없음으로 끝난 질문'이다. LLM 이 있으면 한 문장 요약만 맡기고, 그 요약도 통화 요약(VC7)과 같은 방식으로 원문과 맞춰 본다.
새 채널의 첫 말은 '이어서'를 분명히 한다 — 고객이 같은 설명을 반복하지 않게 사실을 한 번 되짚고, 미해결 질문부터 묻는다.
"""

import re
from typing import Any

from app.core import llm
from app.stages.conversation import memory as conv_memory
from app.stages.omni.envelope import CHANNELS
from app.stages.voice import summary as voice_summary

NOT_FOUND = re.compile(r"찾지 못|확인되지 않|근거가 없|모르겠|상담원에게 연결")
QUESTION = re.compile(r"\?|[가-힣](?:나요|까요|가요|죠|어요|에요|예요|니까|는지)\s*$")
SUMMARY_SYSTEM = "옴니채널 상담 기록을 다음 상담원 · 다음 채널이 이어받도록 한 문장으로 요약합니다. 기록에 없는 내용은 쓰지 않습니다."


def _turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"role": "customer" if m["direction"] == "in" else "agent", "text": m["text"], "channel": m["channel"]}
        for m in messages
        if m.get("text")
    ]


def open_questions(messages: list[dict[str, Any]]) -> list[str]:
    """답이 안 나갔거나 '찾지 못함'으로 끝난 고객 질문(최근 것부터 3개)."""
    answered = {m["reply_to"]: m for m in messages if m["direction"] == "out" and m.get("reply_to")}
    out = []
    for m in messages:
        if m["direction"] != "in" or not QUESTION.search(m.get("text") or ""):
            continue
        rep = answered.get(m["id"])
        if rep is None or m.get("status") in ("received", "failed") or NOT_FOUND.search(rep.get("text") or ""):
            out.append(m["text"][:120])
    return out[-3:][::-1]


def next_steps(messages: list[dict[str, Any]]) -> list[str]:
    """마지막 답의 번호 목록 · '…해 보세요' 문장 = 고객이 해 볼 다음 할 일."""
    last = next((m for m in reversed(messages) if m["direction"] == "out"), None)
    if last is None:
        return []
    steps = [re.sub(r"\s*\[\d+(?:[,，]\s*\d+)*\]", "", s.group(1)).strip() for s in re.finditer(r"(?m)^\s*\d+[.)]\s*(.+)$", last["text"])]
    if not steps:
        steps = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", last["text"]) if re.search(r"(?:해|확인해|눌러|빼|열어|닫아) 보세요|하세요", s)
        ]
    return [s[:80] for s in steps[:4]]


def brief(messages: list[dict[str, Any]], mem: dict[str, Any], scenes: list[dict[str, Any]] | None = None,
          lcfg: llm.LLMConfig | None = None) -> dict[str, Any]:  # fmt: skip
    """넘김 요약 {summary, facts, product, codes, tried, open_questions, next_steps, channels, scene, verify}."""
    turns = _turns(messages)
    codes = list(dict.fromkeys([*(mem.get("codes") or []), *[s["code"] for s in scenes or [] if s.get("code")]]))
    first = next((t["text"] for t in turns if t["role"] == "customer"), "")
    rule = f"{mem.get('product_model') or '제품 미상'} · {', '.join(codes) or '코드 없음'} — {first[:60]}"
    summary, by, ver = rule, "rule", None
    if lcfg is not None and turns:
        log = voice_summary.transcript_text(turns[-16:])
        try:
            r = llm.chat(lcfg, SUMMARY_SYSTEM, f"사실:\n{conv_memory.facts_text(mem)}\n\n기록:\n{log}", 160, 0.0)
            cand = r["text"].strip().splitlines()[0][:200] if r["text"].strip() else ""
            if cand:
                ver = voice_summary.verify({"diagnosis": cand}, turns, min_support=0.3)
                # 요약이 기록과 맞지 않으면(지어낸 문장) 규칙 요약을 쓴다 — 넘김 요약이 틀리면 다음 채널에서 잘못 이어진다
                if ver["checks"] and all(c["ok"] for c in ver["checks"]):
                    summary, by = cand, "llm"
        except llm.LLMError:
            pass
    channels = list(dict.fromkeys(m["channel"] for m in messages))
    return {"summary": summary, "by": by, "facts": conv_memory.facts_text(mem), "product": mem.get("product_model") or "", "codes": codes,
            "tried": list(mem.get("tried") or [])[-5:], "open_questions": open_questions(messages), "next_steps": next_steps(messages),
            "channels": channels, "scene": (scenes or [None])[-1], "verify": ver}  # fmt: skip


def _ro(word: str) -> str:
    """'으로' · '로' — 받침이 있으면(ㄹ 받침 제외) '으로'. '웹 채팅로' 처럼 조사가 틀리면 첫 말부터 어색하다."""
    ch = word[-1:] if word else ""
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return "으로" if jong and jong != 8 else "로"
    return "로"


def greeting(b: dict[str, Any], to_channel: str) -> str:
    """새 채널의 첫 말 — 앞 채널 이름 · 아는 사실 · 미해결 질문(있으면)."""
    prev = [CHANNELS.get(c, {}).get("label", c) for c in b["channels"] if c != to_channel]
    where = f"앞서 {prev[-1]}{_ro(prev[-1])}" if prev else "앞서"
    facts = " ".join(x for x in [b["product"], " · ".join(b["codes"])] if x)
    s = f"{where} 말씀하신 {facts + ' ' if facts else ''}문제 이어서 도와드리겠습니다."
    if b["tried"]:
        s += f" '{b['tried'][-1][:30]}'까지 안내드렸습니다."
    if b["open_questions"]:
        s += f" 아직 답을 못 드린 질문: {b['open_questions'][0][:50]}"
    elif b["next_steps"]:
        s += f" 다음으로 '{b['next_steps'][0][:30]}' 해 보셨나요?"
    return s


def carried(b: dict[str, Any], must: list[str]) -> dict[str, Any]:
    """넘김 요약 · 첫 말에 꼭 넘어가야 할 사실(제품 · 코드 · 조치)이 들어 있나 — OM8 맥락 이어짐 채점."""
    hay = " ".join([b["summary"], b["facts"], greeting(b, "voice"), " ".join(b["codes"]), b["product"]])
    hit = [m for m in must if m and m in hay]
    return {"carried": len(hit), "of": len(must), "missing": [m for m in must if m not in hit]}
