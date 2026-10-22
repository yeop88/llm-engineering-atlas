"""OM7 채널별 응답 형식: 같은 답을 채널의 제약(길이 · 버튼 · 마크다운 · 링크)과 개인정보 정책에 맞게 바꾼다.

채팅용 번호 목록을 그대로 읽어 주거나 문자에 표 · 링크를 넣으면 쓸 수 없다. 내용은 하나(검색 · 검증을 거친 답)이고 모양만 채널마다 바꾼다 —
채널마다 답을 따로 만들면 같은 질문에 채널마다 다른 내용을 답하는 일관성 문제가 생긴다(OM8 이 잰다).
- 음성: 문장 두 개까지, 읽는 글(VC4 — 숫자 · 코드 · 모델 번호 읽기), 근거 번호 · 마크다운 없음. 나머지는 '문자로 보내 드릴까요?'
- 문자: 한 통 70자 안(한글 단문 기준), 링크 · 마크다운 · 근거 번호 없음, 넘치면 핵심 첫 문장 + '자세한 안내는 채팅에서'
- 메신저 · 카톡형: 단계는 줄로, 400자 안, 다음 할 일은 빠른 답장 버튼(3개, 14자 안)
- 이메일: 전부, 인사 · 맺음말, 근거는 각주로
- 웹 채팅: 마크다운 그대로
개인정보는 채널마다 다르게 가린다 — 본인 확인이 된 채널(이메일 · 웹 채팅 로그인)은 고객 자신의 연락처를 보여 줘도 되지만, 문자 · 메신저 ·
음성(스피커폰 · 알림 미리 보기로 남이 볼 수 있음)은 전화번호 · 이메일까지 가린다. 주민번호 · 카드 · 계좌는 어느 채널이든 가린다.
"""

import re
from typing import Any

from app.stages.guardrails import pii
from app.stages.voice import speech

ALWAYS = {"rrn", "frn", "card", "account", "passport", "driver"}
RULES: dict[str, dict[str, Any]] = {
    "voice": {"max_chars": 160, "max_sentences": 2, "markdown": False, "links": False, "cite": False, "buttons": 0,
              "pii": ALWAYS | {"phone", "email", "address"}},
    "sms": {"max_chars": 70, "max_sentences": 2, "markdown": False, "links": False, "cite": False, "buttons": 0,
            "pii": ALWAYS | {"phone", "email", "address", "name"}},
    "messenger": {"max_chars": 400, "markdown": False, "links": True, "cite": False, "buttons": 3, "pii": ALWAYS | {"phone", "email"}},
    "kakao": {"max_chars": 400, "markdown": False, "links": True, "cite": False, "buttons": 3, "pii": ALWAYS | {"phone", "email"}},
    "email": {"max_chars": 4000, "markdown": False, "links": True, "cite": True, "buttons": 0, "pii": ALWAYS},
    "web_chat": {"max_chars": 2000, "markdown": True, "links": True, "cite": True, "buttons": 3, "pii": ALWAYS},
    "video": {"max_chars": 160, "max_sentences": 2, "markdown": False, "links": False, "cite": False, "buttons": 0,
              "pii": ALWAYS | {"phone", "email", "address"}},
}  # fmt: skip
CITE = re.compile(r"\s*\[\d{1,2}(?:\s*[,，]\s*\d{1,2})*\]")
LINK = re.compile(r"https?://\S+|www\.\S+")
MD = re.compile(r"\*\*|__|`|^#{1,6}\s*|^>\s*|^\s*[-*]\s+(?=\S)", re.M)
STEP = re.compile(r"(?m)^\s*(\d+)[.)]\s*(.+)$")
SENT = re.compile(r"(?<=[^\d\s][.!?])\s+|\n+")  # '1. ' 같은 번호 뒤 점은 문장 끝이 아니다


def _plain(text: str, keep_cite: bool, keep_links: bool) -> str:
    t = text if keep_cite else CITE.sub("", text)
    t = MD.sub("", t)
    if not keep_links:
        t = LINK.sub("", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _cut(text: str, n: int) -> str:
    """n 자 안에서 문장 · 낱말 경계로 자른다(끝을 '…' 로)."""
    if len(text) <= n:
        return text
    cut = text[: n - 1]
    for sep in (". ", "다.", "요.", " "):
        i = cut.rfind(sep)
        if i > n * 0.5:
            return cut[: i + len(sep.rstrip())].rstrip() + ("" if sep.strip().endswith(".") else "…")
    return cut + "…"


def buttons(steps: list[str], n: int) -> list[str]:
    """다음 할 일 → 빠른 답장 버튼(14자 안). 마지막은 늘 '상담원 연결' — 버튼만으로 막다른 길에 가두지 않게.
    단계 글을 줄여 버튼 이름을 만들면 '배수 필터를 여' 처럼 어미가 잘린 말이 나왔다 — 'N단계 했어요' 로 단계 번호만 가리킨다."""
    if not n:
        return []
    return [f"{i + 1}단계 했어요" for i in range(min(len(steps), n - 1))] + ["상담원 연결"]


def render(text: str, channel: str, sources: list[dict[str, Any]] | None = None, steps: list[str] | None = None) -> dict[str, Any]:
    """→ {text, buttons, footnotes, spoken, chars, truncated, masked, rule}."""
    rule = RULES.get(channel, RULES["web_chat"])
    masked_text, hits = pii.mask(text or "", rule["pii"])
    body = masked_text if rule["markdown"] else _plain(masked_text, rule["cite"], rule["links"])
    if steps is None:
        steps = [CITE.sub("", m.group(2)).strip() for m in STEP.finditer(text or "")]
    truncated = False
    out: dict[str, Any] = {"rule": channel}
    if channel in ("voice", "video"):
        # 줄(번호 목록의 한 단계)과 문장을 같은 단위로 — 두 단위까지만 말하고 나머지는 문자로 보내겠다고 묻는다(음성은 길면 끝까지 못 듣는다)
        sents = [s.strip() for s in SENT.split(body) if s.strip()]
        keep = sents[: rule["max_sentences"]]
        truncated = len(sents) > len(keep)
        if truncated:
            keep = [*keep, "나머지 단계는 문자로 보내 드릴까요?"]
        out["spoken"] = " ".join(speech.spoken(k) for k in keep)
        said = " ".join(keep)
        body = _cut(said, rule["max_chars"] + 40) if truncated else _cut(said, rule["max_chars"])
    elif channel == "sms":
        flat = re.sub(r"\s*\n+\s*", " ", body)
        if len(flat) > rule["max_chars"]:
            first = SENT.split(flat)[0]
            tail = " 자세한 안내는 채팅에서"
            body = _cut(first, rule["max_chars"] - len(tail)) + tail
            truncated = True
        else:
            body = flat
    elif channel == "email":
        foot = [f"[{i + 1}] {s.get('title') or s.get('doc_title') or s.get('source') or ''}".strip() for i, s in enumerate(sources or [])][
            :6
        ]
        body = f"안녕하세요, 고객님.\n\n{body}\n\n더 궁금한 점은 이 메일에 회신해 주세요.\n감사합니다."
        out["footnotes"] = foot
        if foot:
            body += "\n\n근거\n" + "\n".join(foot)
    else:
        if len(body) > rule["max_chars"]:
            body, truncated = _cut(body, rule["max_chars"]), True
    out |= {"text": body, "buttons": buttons(steps, rule["buttons"]), "chars": len(body), "truncated": truncated,
            "masked": pii.counts(hits)}  # fmt: skip
    return out


def check(rendered: dict[str, Any], channel: str) -> list[str]:
    """형식 위반 — OM8 형식 준수 채점. 빈 목록이면 통과."""
    rule = RULES.get(channel, RULES["web_chat"])
    t = rendered.get("text", "")
    bad = []
    limit = rule["max_chars"] + (40 if channel in ("voice", "video") and rendered.get("truncated") else 0)
    if len(t) > limit:
        bad.append(f"길이 {len(t)} > {limit}")
    if not rule["markdown"] and MD.search(t):
        bad.append("마크다운")
    if not rule["links"] and LINK.search(t):
        bad.append("링크")
    if not rule["cite"] and CITE.search(t):
        bad.append("근거 번호")
    if len(rendered.get("buttons") or []) > rule["buttons"]:
        bad.append("버튼 수")
    if any(len(b) > 14 for b in rendered.get("buttons") or []):
        bad.append("버튼 길이")
    left = {h["type"] for h in pii.scan(t, rule["pii"])}
    if left:
        bad.append("개인정보: " + ", ".join(sorted(left)))
    if channel in ("voice", "video") and (CITE.search(rendered.get("spoken", "")) or MD.search(rendered.get("spoken", ""))):
        bad.append("읽는 글에 기호")
    return bad
