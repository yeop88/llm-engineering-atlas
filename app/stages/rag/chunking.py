"""청킹 전략. 길이 단위는 글자 수(한국어는 대략 1~1.5글자 ≈ 1토큰).

- fixed     : 고정 길이 + 겹침, 공백에서 끊음
- recursive : 문단 → 줄 → 문장 → 단어 순으로 큰 구분자부터 잘라 길이에 맞춤 (범용 기본값)
- sentence  : Kiwi 문장 분리 후 문장 단위로 묶음, 겹침은 문장 수
- legal     : 법령 조문(제N조), 항(①②), 판결문 구획(【주문】【이유】 등) 경계로 나누고 소속 조문 제목을 붙임
- page      : 페이지(또는 HWP 구역) 단위, 너무 길면 recursive 로 다시 나눔
"""

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from app.core.korean import split_sentences

STRATEGIES = {
    "recursive": "재귀 분할 (문단→줄→문장→단어, 범용)",
    "fixed": "고정 길이 + 겹침",
    "sentence": "문장 단위 묶음 (Kiwi 문장 분리)",
    "legal": "법률 구조 (조문·항·판결문 구획)",
    "page": "페이지/구역 단위",
}
DEFAULTS: dict[str, Any] = {
    "method": "recursive",
    "size": 800,
    "overlap": 100,
    "overlap_sentences": 1,
    "min_chars": 20,
    "include_title": True,
    "merge_below": 0,  # 이보다 짧은 청크는 이웃과 합침 (0 = 끔)
}


@dataclass
class ChunkSpec:
    text: str
    page: int | None
    start: int
    end: int
    meta: dict[str, Any] = field(default_factory=dict)


def normalize(strategy: dict[str, Any] | None) -> dict[str, Any]:
    s = DEFAULTS | (strategy or {})
    if s["method"] not in STRATEGIES:
        raise ValueError(f"알 수 없는 청킹 방법: {s['method']}")
    s["size"] = max(100, min(int(s["size"]), 8000))
    s["overlap"] = max(0, min(int(s["overlap"]), s["size"] // 2))
    s["overlap_sentences"] = max(0, min(int(s["overlap_sentences"]), 5))
    s["min_chars"] = max(0, int(s["min_chars"]))
    s["include_title"] = bool(s["include_title"])
    s["merge_below"] = max(0, min(int(s.get("merge_below") or 0), s["size"]))
    return s


def _merge_short(page: str, items: list[tuple[int, int, str, str]], below: int, size: int) -> list[tuple[int, int, str, str]]:
    """짧은 청크를 바로 뒤(또는 앞) 청크와 합친다 — 크기 한도 안에서.

    법률 구조 청킹은 짧은 조문 · 판결문의 짧은 구획(참조조문 등)을 그대로 한 청크로 둬, 실측에서 100자 이하 청크가
    35% 였다. 짧은 청크는 문맥이 모자라 임베딩이 불안정하고 검색 결과 자리만 차지한다. 이웃 조문 · 구획은 내용이 이어지는
    경우가 많아 합쳐도 주제가 크게 섞이지 않는다. 합친 글은 원문 구간(page[시작:끝])으로 다시 잘라 겹침이 중복되지 않게 한다.
    """
    out: list[tuple[int, int, str, str]] = []
    for a, b, c, h in items:
        if out:
            pa, pb, pc, ph = out[-1]
            if (len(pc) < below or len(c) < below) and (b - pa) <= size and a >= pa:
                # 제목은 첫 청크 것에 '외'를 한 번만 붙인다(세 개 이상 합쳐도 '외 외'가 되지 않게)
                heading = ph if not h or h == ph or ph.endswith(" 외") else (f"{ph} 외" if ph else h)
                out[-1] = (pa, b, page[pa:b].strip(), heading)
                continue
        out.append((a, b, c, h))
    return out


# ── 기본 분할기 ─────────────────────────────────────────────────────────────
def _fixed(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    spans, start, n = [], 0, len(text)
    while start < n:
        end = min(n, start + size)
        if end < n:  # 끝을 공백·줄바꿈 근처로 당겨 단어가 잘리지 않게
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if cut > start:
                end = cut
        spans.append((start, end))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return spans


_SEPARATORS = ["\n\n", "\n", ". ", "다. ", "? ", "! ", " "]


def _split_recursive(text: str, size: int, seps: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            parts = text.split(sep)
            pieces = [p + sep for p in parts[:-1]] + [parts[-1]]
            out: list[str] = []
            for p in pieces:
                out.extend(_split_recursive(p, size, seps[i + 1 :]) if len(p) > size else [p])
            return out
    return [text[i : i + size] for i in range(0, len(text), size)]


def _merge(pieces: list[str], size: int, overlap: int) -> list[str]:
    """작은 조각을 size 이하로 이어 붙이고, 앞 청크의 끝 일부(overlap 글자)를 다음 청크 앞에 겹친다."""
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in pieces:
        if cur and cur_len + len(p) > size:
            chunks.append("".join(cur))
            keep: list[str] = []
            kept = 0
            for q in reversed(cur):
                # 겹침 + 다음 조각이 size 를 넘지 않는 만큼만 가져온다 (청크가 size 를 넘지 않게)
                if kept + len(q) > overlap or kept + len(q) + len(p) > size:
                    break
                keep.insert(0, q)
                kept += len(q)
            cur, cur_len = keep, kept
        cur.append(p)
        cur_len += len(p)
    if cur:
        chunks.append("".join(cur))
    return chunks


def _locate(text: str, chunks: list[str]) -> list[tuple[int, int, str]]:
    """청크 원문 위치(start, end) 찾기 — 겹침 때문에 앞 청크 시작 이후부터 검색."""
    out, pos = [], 0
    for c in chunks:
        stripped = c.strip()
        if not stripped:
            continue
        i = text.find(stripped, pos)
        if i < 0:
            i = text.find(stripped)
        i = max(i, 0)
        out.append((i, i + len(stripped), stripped))
        pos = i + 1
    return out


def _recursive(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    return _locate(text, _merge(_split_recursive(text, size, _SEPARATORS), size, overlap))


def _sentence(text: str, size: int, overlap_sents: int) -> list[tuple[int, int, str]]:
    sents = split_sentences(text)
    chunks: list[str] = []
    cur: list[str] = []

    def length(xs: list[str]) -> int:
        return sum(len(x) + 1 for x in xs)

    for s in sents:
        if len(s) > size:  # 아주 긴 문장은 앞 묶음을 내보낸 뒤 재귀 분할
            if cur:
                chunks.append(" ".join(cur))
                cur = []
            chunks.extend(c for _, _, c in _recursive(s, size, 0))
            continue
        if cur and length(cur) + len(s) > size:
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sents:] if overlap_sents else []
            while cur and length(cur) + len(s) > size:  # 겹칠 문장이 길면 줄여서 size 를 지킨다
                cur.pop(0)
        cur.append(s)
    if cur:
        chunks.append(" ".join(cur))
    return _locate(text, chunks)


# ── 법률 구조 ───────────────────────────────────────────────────────────────
_ARTICLE = re.compile(r"(?m)^[ \t]*(제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^)\n]{1,60}\))?)")
_JUDGMENT = re.compile(
    r"(?m)^[ \t]*(【[^】\n]{1,20}】|(?:주\s*문|이\s*유|판\s*시\s*사\s*항|판\s*결\s*요\s*지|참\s*조\s*조\s*문|참\s*조\s*판\s*례|청\s*구\s*취\s*지|사\s*건)\s*$)"
)
_CLAUSE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")


def _legal(text: str, size: int, overlap: int) -> list[tuple[int, int, str, str]]:
    """(start, end, text, heading). 조문/판결문 구획 단위로 자르고, 길면 항(①..) → 재귀 분할."""
    marks = sorted({m.start(1): m.group(1).strip() for m in list(_ARTICLE.finditer(text)) + list(_JUDGMENT.finditer(text))}.items())
    if not marks:
        return [(s, e, c, "") for s, e, c in _recursive(text, size, overlap)]
    units: list[tuple[int, int, str]] = []
    if marks[0][0] > 0:
        units.append((0, marks[0][0], ""))  # 첫 조문 앞 머리말
    for i, (pos, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        units.append((pos, end, re.sub(r"\s+", " ", heading)))
    out: list[tuple[int, int, str, str]] = []
    for start, end, heading in units:
        body = text[start:end]
        if not body.strip():
            continue
        if len(body) <= size:
            out.append((start, start + len(body.rstrip()), body.strip(), heading))
            continue
        clauses = [c for c in _CLAUSE.split(body) if c.strip()]
        pieces = clauses if len(clauses) > 1 else _split_recursive(body, size, _SEPARATORS)
        for s, e, c in _locate(body, _merge([p for piece in pieces for p in _split_recursive(piece, size, _SEPARATORS)], size, overlap)):
            out.append((start + s, start + e, c, heading))
    return out


# ── 진입점 ─────────────────────────────────────────────────────────────────
def chunk_pages(pages: list[str], strategy: dict[str, Any], paged: bool = True) -> list[ChunkSpec]:
    """문서 하나의 페이지 목록을 청크로. paged=False 면 page 번호를 기록하지 않는다."""
    s = normalize(strategy)
    size, overlap, method = s["size"], s["overlap"], s["method"]
    out: list[ChunkSpec] = []
    for pno, page in enumerate(pages, start=1):
        if not page.strip():
            continue
        page_no = pno if paged else None
        if method == "fixed":
            items = [(a, b, page[a:b].strip(), "") for a, b in _fixed(page, size, overlap)]
        elif method == "recursive":
            items = [(a, b, c, "") for a, b, c in _recursive(page, size, overlap)]
        elif method == "sentence":
            items = [(a, b, c, "") for a, b, c in _sentence(page, size, s["overlap_sentences"])]
        elif method == "legal":
            items = _legal(page, size, overlap)
        else:  # page
            items = (
                [(0, len(page), page.strip(), "")]
                if len(page) <= size * 2
                else [(a, b, c, "") for a, b, c in _recursive(page, size, overlap)]
            )
        if s["merge_below"]:
            items = _merge_short(page, items, s["merge_below"], size)
        for a, b, c, heading in items:
            if len(c) < s["min_chars"]:
                continue
            out.append(ChunkSpec(text=c, page=page_no, start=a, end=b, meta={"heading": heading} if heading else {}))
    return out


def media_chunks(items: list[dict[str, Any]]) -> list[ChunkSpec]:
    """미디어 문서(이미지 · 영상 프레임)는 텍스트 청킹 전략과 상관없이 항목 하나가 청크 하나다.

    그림은 잘라 붙일 수 없으므로 크기 · 겹침 설정이 의미가 없다. 청크 글은 라벨(파일 이름 · 시각)이고,
    meta["media"] 의 경로로 인덱스가 실제 이미지를 인코딩한다(멀티모달 모델일 때).
    """
    return [
        ChunkSpec(text=it["label"], page=None, start=0, end=len(it["label"]), meta={"media": it["path"], "t": it.get("t")}) for it in items
    ]


def embed_text(chunk_text: str, title: str, heading: str, strategy: dict[str, Any]) -> str:
    """인덱싱할 때 실제로 임베딩하는 텍스트 (문서 제목·조문 제목으로 맥락 보강)."""
    prefix = []
    if strategy.get("include_title", True) and title:
        prefix.append(title)
    if heading and not chunk_text.startswith(heading):
        prefix.append(heading)
    return (" · ".join(prefix) + "\n" + chunk_text) if prefix else chunk_text


def stats(lengths: list[int]) -> dict[str, Any]:
    if not lengths:
        return {"count": 0}
    s = sorted(lengths)
    buckets = [100, 200, 400, 600, 800, 1000, 1500, 2000, 4000, 8000, 10**9]
    hist = {}
    lo = 0
    for b in buckets:
        n = sum(1 for x in s if lo < x <= b)
        if n:
            hist[f"{lo + 1}-{b if b < 10**9 else '∞'}"] = n
        lo = b
    return {
        "count": len(s),
        "avg": round(sum(s) / len(s), 1),
        "median": median(s),
        "p95": s[min(len(s) - 1, int(len(s) * 0.95))],
        "min": s[0],
        "max": s[-1],
        "hist": hist,
    }
