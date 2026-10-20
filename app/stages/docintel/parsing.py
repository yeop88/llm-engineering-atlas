"""D2 파싱 점검 · OCR: 파싱이 놓친 쪽을 찾고, 글자가 없는 쪽(스캔 PDF)은 비전 LLM 으로 읽어 채운다.

파싱에서 빠진 글은 검색 · 답변 어디서도 되살릴 수 없다. 그래서 문서마다 쪽별 글자 수 · 빈 쪽 · 깨진 글자 비율을 먼저 본다.
OCR 엔진으로 비전 LLM(로컬 Gemma 4 + mmproj)을 쓰는 이유: 이 PC 에 이미 있고 한국어를 읽는다(별도 OCR 엔진 · 모델 설치 없음).
대신 느리고(쪽당 수십 초) 글자를 고쳐 쓸 위험이 있어, 원본에 글자가 있는 쪽으로 정확도를 재 둔다(docs 의 실측).
"""

import io
import re
import time
from typing import Any

from PIL import Image

from app.core import llm, media_store
from app.core.db import Document
from app.stages.docintel.incremental import touch

EMPTY_CHARS = 20  # 이보다 짧은 쪽은 '빈 쪽'(쪽 번호 · 머리말만 남은 경우 포함)
_BROKEN = re.compile(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]|(?<![가-힣ㄱ-ㅎㅏ-ㅣ])[ㄱ-ㅎㅏ-ㅣ]{3,}")
OCR_SYSTEM = "당신은 문서 사진의 글자를 그대로 옮겨 적는 OCR 도구입니다. 설명 · 요약 · 번역을 하지 않습니다."
OCR_PROMPT = ("이 이미지는 문서의 한 쪽입니다. 보이는 글자를 위에서 아래로, 왼쪽에서 오른쪽 순서로 그대로 옮겨 적으세요. "
              "고치거나 빠뜨리지 말고, 표는 한 줄에 한 행씩 칸을 ' | ' 로 나누세요. 글자가 없으면 '(글자 없음)' 이라고만 쓰세요.")  # fmt: skip


def broken_ratio(text: str) -> float:
    """깨진 글자(대체 문자 · 제어 문자 · 자모만 이어진 것) 비율 — 인코딩 · 파싱 오류의 흔적."""
    if not text:
        return 0.0
    return round(sum(len(m.group(0)) for m in _BROKEN.finditer(text)) / len(text), 4)


def report(doc: Document) -> dict[str, Any]:
    pages = doc.pages or []
    chars = [len(p.strip()) for p in pages]
    meta = doc.meta or {}
    empty = [i + 1 for i, c in enumerate(chars) if c < EMPTY_CHARS]
    text = "\n".join(pages)
    issues = []
    if meta.get("warning"):
        issues.append(meta["warning"])
    if pages and len(empty) == len(pages) and not meta.get("media_items"):
        issues.append("모든 쪽에 글자가 없습니다 — OCR 이 필요합니다.")
    elif empty and meta.get("page_kind") == "page":
        issues.append(f"빈 쪽 {len(empty)}개 — 스캔된 쪽이면 OCR 로 채우세요.")
    if (br := broken_ratio(text)) > 0.01:
        issues.append(f"깨진 글자 {br:.1%} — 인코딩 · 파서 문제일 수 있습니다.")
    return {
        "document_id": doc.id, "filename": doc.filename, "mime": doc.mime, "page_kind": meta.get("page_kind"), "n_pages": len(pages),
        "n_chars": doc.n_chars, "chars_per_page": chars, "empty_pages": empty, "broken_ratio": broken_ratio(text),
        "has_original": bool(meta.get("original")), "ocr": meta.get("ocr"), "layout": meta.get("layout"), "issues": issues,
        "ocr_possible": bool(meta.get("original")) and doc.filename.lower().endswith(".pdf") and bool(empty),
        "preview": [p[:300] for p in pages[:3]],
    }  # fmt: skip


def render_pdf_pages(data: bytes, page_numbers: list[int], scale: float = 2.0) -> list[Image.Image]:
    """PDF 쪽 → 이미지 (1부터 세는 쪽 번호). 비전 모델이 작은 글자를 읽도록 2배로 그린다."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return [pdf[n - 1].render(scale=scale).to_pil().convert("RGB") for n in page_numbers if 1 <= n <= len(pdf)]
    finally:
        pdf.close()


def _jpeg(im: Image.Image, max_side: int = 1600) -> bytes:
    im = im.copy()
    im.thumbnail((max_side, max_side))  # 긴 변 기준 — 비전 모델은 그림을 수백 토큰으로 바꾸므로 너무 크면 읽기만 느려진다
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def ocr_image(lcfg: llm.LLMConfig, im: Image.Image, max_tokens: int = 2048) -> dict[str, Any]:
    r = llm.chat(lcfg, OCR_SYSTEM, OCR_PROMPT, max_tokens, 0.0, images=[_jpeg(im)])
    text = r["text"].strip()
    if text.startswith("(글자 없음)"):
        text = ""
    return {"text": text, "seconds": r.get("seconds", 0.0), "usage": r.get("usage")}


def ocr_document(doc: Document, lcfg: llm.LLMConfig, pages: list[int] | None = None, job: Any = None) -> dict[str, Any]:
    """빈 쪽(또는 지정한 쪽)을 OCR 해 문서 글을 채운다 — 글을 바꿨으므로 증분 갱신 대상으로 표시."""
    if not doc.filename.lower().endswith(".pdf"):
        raise ValueError("OCR 은 PDF 문서만 됩니다(이미지 문서는 멀티모달 색인을 쓰세요).")
    data = media_store.read_original((doc.meta or {}).get("original") or "")
    targets = pages or report(doc)["empty_pages"]
    if not targets:
        return {"pages": [], "message": "빈 쪽이 없습니다."}
    started = time.perf_counter()
    new_pages = list(doc.pages or [])
    done = []
    for k, n in enumerate(targets):
        if job:
            job.update(k / len(targets), f"OCR {k + 1}/{len(targets)}쪽 (p.{n})")
        im = render_pdf_pages(data, [n])[0]
        r = ocr_image(lcfg, im)
        while len(new_pages) < n:
            new_pages.append("")
        before = new_pages[n - 1].strip()
        row: dict[str, Any] = {"page": n, "chars": len(r["text"]), "seconds": round(r["seconds"], 1)}
        if len(before) >= EMPTY_CHARS:
            # 파서가 이미 글을 뽑은 쪽은 '정답이 있는 쪽' — 덮어쓰지 않고 OCR 정확도만 잰다.
            # 파서 글이 OCR 보다 정확하므로 바꾸면 손해이고, 이 수치로 빈 쪽 OCR 결과를 얼마나 믿을지 정한다.
            row["accuracy"] = char_accuracy(before, r["text"])
            row["measured_only"] = True
        else:
            new_pages[n - 1] = r["text"]
        done.append(row)
    doc.pages = new_pages
    doc.n_chars = sum(len(p) for p in new_pages)
    accs = [d["accuracy"] for d in done if "accuracy" in d]
    acc = round(sum(accs) / len(accs), 4) if accs else None
    seconds = round(time.perf_counter() - started, 1)
    if any(not d.get("measured_only") for d in done):
        touch(doc, ocr={"pages": done, "engine": lcfg.model, "seconds": seconds, "accuracy": acc})
        if any(
            (p or "").strip() for p in new_pages
        ):  # 글이 생겼으면 업로드 때의 'OCR 필요' 표시를 지운다(화면 · 점검이 계속 경고하지 않게)
            doc.meta = {k: v for k, v in doc.meta.items() if k not in ("needs_ocr", "warning")}
    else:  # 재기만 했으면 글은 그대로 — 증분 갱신 대상으로 표시하지 않는다
        doc.meta = dict(doc.meta or {}) | {"ocr": {"pages": done, "engine": lcfg.model, "seconds": seconds, "accuracy": acc}}
    return {"pages": done, "n_chars": doc.n_chars, "seconds": seconds, "accuracy": acc}


def char_accuracy(truth: str, got: str) -> float:
    """OCR 글자 정확도(1 − 문자 오류율 근사): 공백을 뺀 두 글의 일치 비율(difflib)."""
    import difflib

    a, b = re.sub(r"\s+", "", truth), re.sub(r"\s+", "", got)
    if not a:
        return 1.0 if not b else 0.0
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)
