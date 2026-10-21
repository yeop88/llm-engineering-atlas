"""VC4 스트리밍 음성 합성: 생성되는 글을 문장 단위로 끊어 바로 합성 · 숫자 · 코드 · 단위 읽기 규칙.

LLM 이 답을 다 쓰기 전에 앞 문장부터 소리로 바꾼다 — 첫 소리까지의 시간은 '첫 문장 생성 + 그 문장 합성'이 되어, 답 전체 길이와
상관없어진다. 너무 긴 문장은 쉼표에서 한 번 더 끊는다(합성 한 번이 길면 첫 소리가 늦다).

읽기 규칙이 필요한 이유: 합성기는 'E4' 를 '이 포' 나 '에 사' 로 읽고, 'WM-200' 을 '더블유엠 마이너스 이백'으로 읽는다. 고객이 코드를 잘못
알아들으면 안내 전체가 틀린다. 그래서 합성기에 넘기기 전에 글을 '읽는 대로' 바꾼다: 코드는 한 글자씩(이 사), 모델 번호는 자릿값(이백),
전화번호는 한 자리씩, 단위는 한국어로. 근거 번호 [1] · 마크다운 기호는 읽지 않는다.

합성은 TTS_URL(OpenAI 호환 /audio/speech)이 있으면 서버에서, 없으면 화면이 브라우저 음성(Web Speech, ko-KR)으로 같은 '읽는 글'을 읽는다.
"""

import hashlib
import re
from pathlib import Path

import httpx

from app.core.config import get_settings

LETTER_NAMES = {"A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지", "H": "에이치", "I": "아이", "J": "제이", "K": "케이",
                "L": "엘", "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알", "S": "에스", "T": "티", "U": "유", "V": "브이",
                "W": "더블유", "X": "엑스", "Y": "와이", "Z": "제트"}  # fmt: skip
DIG = "공일이삼사오육칠팔구"
UNIT_WORDS = {"℃": "도", "°C": "도", "kg": "킬로그램", "g": "그램", "cm": "센티미터", "mm": "밀리미터", "m": "미터", "L": "리터", "ml": "밀리리터",
              "mL": "밀리리터", "W": "와트", "kW": "킬로와트", "V": "볼트", "%": "퍼센트", "rpm": "알피엠"}  # fmt: skip


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out = ""
    for unit, name in ((100000000, "억"), (10000, "만")):
        q, n = divmod(n, unit)
        if q:
            out += sino(q) + name + " "
    for unit, name in ((1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else DIG[q]) + name
    return (out + (DIG[n] if n else "")).strip()


def _digits(s: str) -> str:
    return " ".join(DIG[int(d)] for d in s)


def spoken(text: str) -> str:
    """글 → 읽는 글."""
    t = re.sub(r"\[\d{1,2}(?:\s*[,，]\s*\d{1,2})*\]", "", text or "")  # 근거 번호
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"^\s*(\d+)[.)]\s*", lambda m: _ordinal(int(m.group(1))) + ", ", t, flags=re.M)  # 번호 목록 → '첫 번째, '(일 번째가 아님)
    t = re.sub(r"\b0\d{1,2}-\d{3,4}-\d{4}\b", lambda m: ", ".join(_digits(p) for p in m.group(0).split("-")), t)  # 전화번호
    # 모델 번호(WM-200 · DR300): 글자는 이름으로, 번호는 자릿값으로
    t = re.sub(
        r"\b([A-Z]{2,4})-?(\d{2,4})\b",
        lambda m: " ".join(LETTER_NAMES[c] for c in m.group(1)).replace(" ", "") + " " + sino(int(m.group(2))),
        t,
    )
    # 오류 코드(E4 · OE · d80): 한 글자씩
    t = re.sub(
        r"(?<![A-Za-z0-9])([A-Za-z]{1,2})(\d{1,2})(?![A-Za-z0-9])",
        lambda m: " ".join(LETTER_NAMES.get(c.upper(), c) for c in m.group(1)) + " " + _digits(m.group(2)),
        t,
    )
    t = re.sub(r"(?<![A-Za-z0-9])([A-Z]{2})(?![A-Za-z0-9])", lambda m: " ".join(LETTER_NAMES[c] for c in m.group(1)), t)
    # 숫자 + 단위
    units = "|".join(re.escape(u) for u in sorted(UNIT_WORDS, key=len, reverse=True))
    t = re.sub(rf"(\d+(?:\.\d+)?)\s*({units})(?![A-Za-z])", lambda m: _num(m.group(1)) + " " + UNIT_WORDS[m.group(2)], t)
    t = re.sub(r"\s+([.,!?])", r"\1", t)  # 근거 번호를 뺀 자리의 ' .'
    return re.sub(r"\s{2,}", " ", t).strip()


ORD = ["", "첫", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열"]


def _ordinal(n: int) -> str:
    return f"{ORD[n]} 번째" if 0 < n < len(ORD) else f"{sino(n)} 번"


def _num(s: str) -> str:
    if "." in s:
        a, b = s.split(".", 1)
        return sino(int(a)) + " 점 " + _digits(b)
    return sino(int(s))


# 마침표 없이 끝난 말(…해요 그리고)도 끊되, (1) 끝 글자 앞이 한글이어야 한다 — '물이 다 빠지면' 의 낱말 '다' 에서 끊으면
# '물이 다' 만 먼저 읽혔다. (2) 마침표는 먹지 않는다 — 예전 식(다요죠까 뒤 '\.?\s+')이 '입니다. ' 의 마침표까지 경계로 삼켜
# 문장 글에서 마침표가 빠졌다(첫 번째 갈래가 마침표 뒤를 이미 끊는다)
_END = re.compile(r"(?<=[.!?。])\s+|(?<=[가-힣][다요죠까])\s+(?=[가-힣A-Z0-9])|\n+")


def sentences(buf: str, final: bool = False, max_chars: int = 70) -> tuple[list[str], str]:
    """스트리밍 버퍼 → (완성된 문장들, 남은 조각). final 이면 남은 조각까지 문장으로."""
    parts = _END.split(buf)
    done, rest = parts[:-1], parts[-1]
    if final and rest.strip():
        done, rest = done + [rest], ""
    out = []
    for s in (p.strip() for p in done):
        if not s:
            continue
        while len(s) > max_chars and "," in s[20:max_chars]:  # 긴 문장은 쉼표에서 한 번 더
            i = s.index(",", 20) + 1
            out.append(s[:i].strip())
            s = s[i:].strip()
        out.append(s)
    if not final and len(rest) > max_chars * 1.5 and "," in rest[20:]:
        i = rest.rindex(",") + 1
        out.append(rest[:i].strip())
        rest = rest[i:]
    return out, rest


def tts_dir() -> Path:
    d = get_settings().data_dir / "voice" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def synth(text: str) -> str | None:
    """읽는 글 → mp3 파일 이름(같은 글은 다시 합성하지 않음). TTS_URL 이 없거나 실패하면 None(화면이 브라우저 음성으로)."""
    st = get_settings()
    if not st.tts_url or not text.strip():
        return None
    name = hashlib.sha256(f"{st.tts_model}|{st.tts_voice}|{text}".encode()).hexdigest()[:20] + ".mp3"
    p = tts_dir() / name
    if not p.exists():
        try:
            r = httpx.post(
                st.tts_url.rstrip("/") + "/audio/speech",
                json={"model": st.tts_model, "voice": st.tts_voice, "input": text, "response_format": "mp3"},
                timeout=60,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        p.write_bytes(r.content)
    return name
