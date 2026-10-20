"""문서 → 텍스트 추출. PDF · DOCX · HWP(5.x) · HWPX · TXT/MD/CSV/JSON · HTML.

결과는 페이지(또는 절) 단위 텍스트 목록이다. 청킹 전략을 바꿔 다시 나눌 수 있도록 원문을 보관한다.
"""

import io
import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePath
from typing import Any
from xml.etree import ElementTree as ET


class ParseError(ValueError):
    pass


@dataclass
class ParsedDocument:
    title: str
    pages: list[str]
    page_kind: str  # page(PDF 쪽) | section(HWP 구역 등) | none(나누지 않음)
    mime: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


SUPPORTED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/hwp+zip",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".html": "text/html",
    ".htm": "text/html",
}


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t 　]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _guess_title(pages: list[str], filename: str) -> str:
    for page in pages:
        for line in page.splitlines():
            line = line.strip()
            if 2 <= len(line) <= 100:
                return line
    return PurePath(filename).stem


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ── PDF ────────────────────────────────────────────────────────────────────
def parse_pdf(data: bytes) -> tuple[list[str], dict[str, Any]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("암호가 걸린 PDF 입니다.")
        pages = [_clean(p.extract_text() or "") for p in reader.pages]
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"PDF 를 읽을 수 없습니다: {exc}") from exc
    meta: dict[str, Any] = {"n_pages": len(pages)}
    if reader.metadata and reader.metadata.title:
        meta["pdf_title"] = str(reader.metadata.title)
    if pages and not any(pages):
        meta["warning"] = "텍스트가 없는 PDF 입니다(스캔 이미지일 수 있음). OCR 이 필요합니다."
    return pages, meta


# ── DOCX ───────────────────────────────────────────────────────────────────
def parse_docx(data: bytes) -> tuple[list[str], dict[str, Any]]:
    from docx import Document as Docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = Docx(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"DOCX 를 읽을 수 없습니다: {exc}") from exc
    parts: list[str] = []
    for child in doc.element.body.iterchildren():  # 문단과 표를 본문 순서대로
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                parts.append(" | ".join(dict.fromkeys(c for c in cells if c)))  # 병합 셀 중복 제거
    meta: dict[str, Any] = {}
    if doc.core_properties.title:
        meta["doc_title"] = doc.core_properties.title
    return [_clean("\n".join(parts))], meta


# ── HWP 5.x (바이너리) ─────────────────────────────────────────────────────
HWPTAG_PARA_TEXT = 67  # HWPTAG_BEGIN(16) + 51
_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}  # 1 글자 크기 제어문자


def _hwp_para_text(payload: bytes) -> str:
    out: list[str] = []
    n = len(payload) // 2
    codes = struct.unpack(f"<{n}H", payload[: n * 2])
    i = 0
    while i < n:
        c = codes[i]
        if c >= 32:
            out.append(chr(c))
            i += 1
        elif c in _CHAR_CTRL:
            if c in (10, 13):
                out.append("\n")
            i += 1
        else:  # 인라인/확장 제어문자는 8 글자(16바이트)를 차지한다 (표·각주·탭 등)
            if c == 9:
                out.append("\t")
            i += 8
    return "".join(out)


def _hwp_section_text(raw: bytes) -> str:
    texts: list[str] = []
    pos = 0
    while pos + 4 <= len(raw):
        (header,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", raw, pos)
            pos += 4
        if tag == HWPTAG_PARA_TEXT:
            texts.append(_hwp_para_text(raw[pos : pos + size]))
        pos += size
    return "\n".join(t.rstrip("\n") for t in texts)


def parse_hwp(data: bytes) -> tuple[list[str], dict[str, Any]]:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"HWP 파일이 아닙니다(HWP 5.x 만 지원): {exc}") from exc
    try:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise ParseError("HWP 문서 서명이 없습니다.")
        (props,) = struct.unpack_from("<I", header, 36)
        compressed, encrypted, distributed = bool(props & 1), bool(props & 2), bool(props & 4)
        if encrypted:
            raise ParseError("암호가 걸린 HWP 문서입니다.")
        if distributed:  # 배포용 문서는 본문이 암호화되어 있어 미리보기 텍스트만 읽을 수 있다
            if ole.exists("PrvText"):
                return [_clean(ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore"))], {
                    "warning": "배포용 문서라 미리보기 텍스트만 추출했습니다."
                }
            raise ParseError("배포용(보호) HWP 문서라 본문을 추출할 수 없습니다.")
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][len("Section") :] or 0),
        )
        pages = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            pages.append(_clean(_hwp_section_text(raw)))
        return pages, {"n_sections": len(pages)}
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"HWP 본문을 읽을 수 없습니다: {exc}") from exc
    finally:
        ole.close()


# ── HWPX (OWPML, zip) ──────────────────────────────────────────────────────
def parse_hwpx(data: bytes) -> tuple[list[str], dict[str, Any]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("HWPX(zip) 파일이 아닙니다.") from exc
    names = sorted(
        (n for n in zf.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[-1]).group()),
    )
    if not names:
        raise ParseError("HWPX 본문(Contents/section*.xml)이 없습니다.")
    pages = []
    for name in names:
        root = ET.fromstring(zf.read(name))
        paras = []
        for p in root.iter():
            if p.tag.rsplit("}", 1)[-1] != "p":
                continue
            # 문단의 직계 run 안 텍스트만 모은다 (표 안 문단은 자기 문단에서 따로 잡힘)
            runs = [t.text or "" for run in p if run.tag.rsplit("}", 1)[-1] == "run" for t in run if t.tag.rsplit("}", 1)[-1] == "t"]
            if any(runs):
                paras.append("".join(runs))
        pages.append(_clean("\n".join(paras)))
    return pages, {"n_sections": len(pages)}


# ── HTML ───────────────────────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def parse_html(data: bytes) -> tuple[list[str], dict[str, Any]]:
    p = _TextExtractor()
    p.feed(decode_text(data))
    meta = {"html_title": p.title.strip()} if p.title.strip() else {}
    return [_clean("".join(p.parts))], meta


def parse_plain(data: bytes, ext: str) -> tuple[list[str], dict[str, Any]]:
    text = decode_text(data)
    if ext == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except json.JSONDecodeError:
            pass
    return [_clean(text)], {}


# ── 진입점 ─────────────────────────────────────────────────────────────────
def parse(filename: str, data: bytes) -> ParsedDocument:
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ParseError(f"지원하지 않는 형식입니다: {ext or '(확장자 없음)'} — 지원: {', '.join(sorted(SUPPORTED))}")
    if not data:
        raise ParseError("빈 파일입니다.")
    if ext == ".pdf":
        pages, meta, kind = *parse_pdf(data), "page"
    elif ext == ".docx":
        pages, meta, kind = *parse_docx(data), "none"
    elif ext == ".hwp":
        pages, meta, kind = *parse_hwp(data), "section"
    elif ext == ".hwpx":
        pages, meta, kind = *parse_hwpx(data), "section"
    elif ext in (".html", ".htm"):
        pages, meta, kind = *parse_html(data), "none"
    else:
        pages, meta, kind = *parse_plain(data, ext), "none"
    if not any(p.strip() for p in pages):
        # 스캔 PDF 는 글 없이 받아 둔다 — 거절하면 OCR(문서 처리 D2)로 채울 문서 자체가 없다. 청크는 OCR 뒤에 생긴다
        if ext != ".pdf" or not pages:
            raise ParseError(meta.get("warning") or "추출된 텍스트가 없습니다.")
        meta["needs_ocr"] = True
    title = meta.get("pdf_title") or meta.get("doc_title") or meta.get("html_title") or _guess_title(pages, filename)
    return ParsedDocument(title=title[:300], pages=pages, page_kind=kind, mime=SUPPORTED[ext], meta=meta)
