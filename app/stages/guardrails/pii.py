"""G2 개인정보 탐지 · 가리기: 주민 · 외국인등록번호, 전화, 이메일, 카드, 계좌, 여권, 운전면허, 주소, 사람 이름.

규칙 기반인 이유: 형식이 정해진 번호는 규칙(+ 검증 숫자)이 개체명 모델보다 정확하고, 이 PC 에서 바로 돈다. 이름 · 주소처럼 형식이
느슨한 것은 문맥 단서('성명:', '○○ 씨', '시 · 구 · 로')로만 잡는다 — 모든 이름을 찾으려다 정상 글을 가리는 쪽이 더 해롭다고 봤다.
놓침 · 오탐은 표본 세트로 잰다(docs/stages/guardrails/g2-pii/).

어디서 쓰나: 색인 전(문서 글을 가린 사본으로 바꿈 — 한 번 벡터 DB 에 들어가면 어느 답변으로든 나올 수 있다), 답변 출력(스트리밍 중에도 문장 단위로).
"""

import re
from collections.abc import Iterator
from typing import Any

LABEL = {"rrn": "주민번호", "frn": "외국인등록번호", "phone": "전화번호", "email": "이메일", "card": "카드번호", "account": "계좌번호",
         "passport": "여권번호", "driver": "운전면허번호", "address": "주소", "name": "이름"}  # fmt: skip

_RRN = re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\s?-?\s?([1-8])(\d{6})(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:01[016789]|0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70))[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[- ]?){3}\d{4}(?!\d)")
_ACCOUNT = re.compile(r"(계좌|통장|입금|송금|은행)[^\d\n]{0,12}(\d{2,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?|\d{10,14})")
_PASSPORT = re.compile(r"(여권)[^\w\n]{0,6}(?:번호)?[^\w\n]{0,4}([MSRODG]\d{8})", re.I)
_DRIVER = re.compile(r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)")
_SIDO = r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|충청[남북]도|전라[남북]도|경상[남북]도|강원특별자치도|제주특별자치도)"
_ADDRESS = re.compile(
    _SIDO
    + r"(?:특별시|광역시|특별자치시|도)?\s+\S{1,10}?(?:시|군|구)\s+(?:\S{1,10}?(?:구|읍|면)\s+)?\S{1,15}?(?:로|길)\s?\d+(?:-\d+)?(?:\s?\d+동)?(?:\s?\d+호)?"
)
SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경봉사부황보"
)
_NAME_CTX = re.compile(
    r"(성명|이름|고객명|성함|환자|담당자|신청인|피해자|가해자|작성자|연락처\s*\(?이름)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])"
)
# 호칭 뒤에는 조사가 흔하다('박지성 씨가') — 조사는 허용하고 '씨앗' 같은 낱말만 뺀다
_NAME_SUFFIX = re.compile(r"(?<![가-힣])([가-힣]{2,4})\s?(씨|님|고객님|선생님)(?=[이가은는을를의께에도와과랑]|[^가-힣]|$)")
_NOT_NAME = {
    "고객",
    "회원",
    "사용",
    "관리",
    "담당",
    "기사",
    "상담",
    "선생",
    "여러분",
    "사장",
    "부장",
    "과장",
    "대리",
    "학생",
    "아버",
    "어머",
    "누구",
}


def _luhn(s: str) -> bool:
    ds = [int(c) for c in s if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return len(ds) in (15, 16) and total % 10 == 0


def scan(text: str, types: set[str] | None = None) -> list[dict[str, Any]]:
    """→ [{"type", "start", "end", "text"}] 시작 위치 순, 겹치면 앞 · 긴 것 하나만."""
    text = text or ""
    found: list[tuple[int, int, str]] = []

    def add(t: str, s: int, e: int) -> None:
        if types is None or t in types:
            found.append((s, e, t))

    # 주민 · 외국인등록번호는 생년월일(월 · 일 범위) + 성별 자리 형식으로만 본다. 2020년 10월 이후 번호는 뒷자리가 임의라
    # 검증 숫자 계산이 맞지 않는다 — 검증 숫자로 거르면 새 번호를 놓친다.
    for m in _RRN.finditer(text):
        add("frn" if m.group(4) in "5678" else "rrn", m.start(), m.end())
    for m in _CARD.finditer(text):
        if _luhn(m.group(0)):
            add("card", m.start(), m.end())
    for m in _PHONE.finditer(text):
        add("phone", m.start(), m.end())
    for m in _EMAIL.finditer(text):
        add("email", m.start(), m.end())
    for m in _ACCOUNT.finditer(text):
        add("account", m.start(2), m.end(2))
    for m in _PASSPORT.finditer(text):
        add("passport", m.start(2), m.end(2))
    for m in _DRIVER.finditer(text):
        add("driver", m.start(), m.end())
    for m in _ADDRESS.finditer(text):
        add("address", m.start(), m.end())
    for m in _NAME_CTX.finditer(text):
        name = m.group(2)
        if name[0] in SURNAMES and name[:2] not in _NOT_NAME:
            add("name", m.start(2), m.end(2))
    for m in _NAME_SUFFIX.finditer(text):
        name = m.group(1)
        if name[0] in SURNAMES and len(name) in (2, 3) and name[:2] not in _NOT_NAME:
            add("name", m.start(1), m.end(1))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, last_end = [], -1
    for s, e, t in found:
        if s >= last_end:
            out.append({"type": t, "start": s, "end": e, "text": text[s:e]})
            last_end = e
    return out


def mask(text: str, types: set[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """찾은 것을 [이름] · [전화번호] 처럼 바꾼 글과 찾은 목록."""
    hits = scan(text, types)
    out, pos = [], 0
    for h in hits:
        out.append(text[pos : h["start"]])
        out.append(f"[{LABEL[h['type']]}]")
        pos = h["end"]
    out.append(text[pos:])
    return "".join(out), hits


def counts(hits: list[dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for h in hits:
        c[h["type"]] = c.get(h["type"], 0) + 1
    return c


# 문장 경계: 마침표 · 물음표 · 느낌표 뒤 공백, 또는 줄바꿈. 이메일 · 소수점의 '.' 뒤에는 공백이 없어 끊기지 않는다.
_BOUNDARY = re.compile(r"(?<=[.!?。])\s|\n")


class StreamMasker:
    """스트리밍 답변을 문장 단위로 가린다 — 전화번호가 두 조각에 걸쳐 와도 문장이 끝난 뒤 가리므로 새지 않는다.
    대신 문장이 끝날 때까지 화면에 늦게 나온다(문장 하나만큼)."""

    def __init__(self, types: set[str] | None = None) -> None:
        self.buf = ""
        self.types = types
        self.hits: list[dict[str, Any]] = []

    def feed(self, delta: str) -> str:
        self.buf += delta
        last = None
        for m in _BOUNDARY.finditer(self.buf):
            last = m
        if last is None:
            return ""
        head, self.buf = self.buf[: last.end()], self.buf[last.end() :]
        masked, hits = mask(head, self.types)
        self.hits += hits
        return masked

    def flush(self) -> str:
        masked, hits = mask(self.buf, self.types)
        self.hits += hits
        self.buf = ""
        return masked


def stream(deltas: Iterator[str], types: set[str] | None = None) -> Iterator[str]:
    sm = StreamMasker(types)
    for d in deltas:
        if out := sm.feed(d):
            yield out
    if tail := sm.flush():
        yield tail
