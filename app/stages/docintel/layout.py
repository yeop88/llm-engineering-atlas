"""D3 레이아웃 · 표 · 그림 추출: PDF 에서 표는 행 · 열 구조로, 그림 영역은 이미지 청크로 남긴다.

표를 글로 펴면 행 · 열 관계가 사라져 '3분기 매출' 같은 질문에 답할 수 없다(법령 표의 행 반복 문제도 표 구조를 모르고 처리해서 생겼다).
pdfplumber 로 표 영역을 찾아: 표 밖 글은 그대로, 표는 마크다운 표(머리 행 + 행마다 한 줄)로 바꿔 그 쪽 글 뒤에 붙인다 —
청킹 · 검색 · LLM 이 모두 글만 다루므로 구조를 글 안에 보존하는 편이 가장 덜 바꾸고 가장 많이 쓰인다.
그림(이미지 객체)은 잘라 문서의 그림 항목(meta.figure_items)으로 저장한다 — 청크 세트가 글 청크 뒤에 그림 청크로 넣고,
멀티모달 모델 인덱스면 그림으로 색인된다(멀티모달 RAG 와 같은 경로).
"""

import io
from typing import Any

from app.core import media_store
from app.core.db import Document
from app.stages.docintel.incremental import touch

MIN_FIG_AREA = 0.02  # 쪽 넓이 대비 — 이보다 작은 그림(로고 · 아이콘)은 뺀다


def _cell(v: Any) -> str:
    return " ".join(str(v or "").split()).replace("|", "/")


def table_markdown(rows: list[list[Any]]) -> str:
    rows = [r for r in rows if r and any(c not in (None, "") for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    head = "| " + " | ".join(_cell(c) for c in rows[0]) + " |"
    sep = "|" + "---|" * width
    body = ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join([head, sep, *body])


def _inside(obj: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def extract(data: bytes, figures: bool = True) -> dict[str, Any]:
    """→ {"pages": [{"text", "tables": [rows], "figures": [PIL]}]}."""
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            body = page.filter(lambda o, boxes=boxes: not (o.get("object_type") == "char" and any(_inside(o, b) for b in boxes)))
            text = (body.extract_text() or "").strip()
            rows = [t.extract() for t in tables]
            figs = []
            if figures:
                area = float(page.width * page.height) or 1.0
                for img in page.images:
                    w, h = float(img["x1"] - img["x0"]), float(img["bottom"] - img["top"])
                    if w * h / area < MIN_FIG_AREA:
                        continue
                    bbox = (max(0, img["x0"]), max(0, img["top"]), min(page.width, img["x1"]), min(page.height, img["bottom"]))
                    try:
                        figs.append(page.crop(bbox).to_image(resolution=150).original.convert("RGB"))
                    except Exception:  # noqa: BLE001 — 그림 하나를 못 그려도 나머지는 계속
                        continue
            out.append({"text": text, "tables": rows, "figures": figs})
    return {"pages": out}


def apply(doc: Document, figures: bool = True) -> dict[str, Any]:
    """문서 글을 '표 밖 글 + 마크다운 표'로 다시 만들고 그림을 그림 항목으로 저장한다(원본 PDF 필요)."""
    if not doc.filename.lower().endswith(".pdf"):
        raise ValueError("표 · 그림 추출은 PDF 문서만 됩니다.")
    data = media_store.read_original((doc.meta or {}).get("original") or "")
    res = extract(data, figures)
    new_pages, tables_meta, fig_items = [], [], []
    folder = media_store.doc_dir(doc.id)
    # OCR 로 채운 쪽(원본 PDF 에 글자가 없는 쪽)은 원본에서 다시 뽑으면 빈 글이 된다 — 그 쪽은 OCR 글을 그대로 둔다(OCR 결과를 잃지 않게)
    old_pages = list(doc.pages or [])
    ocr_pages = {r["page"] for r in ((doc.meta or {}).get("ocr") or {}).get("pages", []) if not r.get("measured_only")}
    for pi, p in enumerate(res["pages"], start=1):
        text = p["text"] or (old_pages[pi - 1] if pi in ocr_pages and pi <= len(old_pages) else "")
        parts = [text] if text else []
        for ti, rows in enumerate(p["tables"], start=1):
            md = table_markdown(rows)
            if md:
                parts.append(f"[표 {pi}-{ti}]\n{md}")
                tables_meta.append({"page": pi, "n": ti, "rows": len(rows), "cols": max((len(r) for r in rows), default=0)})
        for fi, im in enumerate(p["figures"], start=1):
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"fig-{pi}-{fi}.jpg"
            im.save(path, "JPEG", quality=88)
            fig_items.append({"label": f"{doc.title or doc.filename} p.{pi} 그림 {fi}", "path": media_store.rel(path), "page": pi})
        new_pages.append("\n\n".join(parts))
    before = doc.n_chars
    doc.pages = new_pages
    doc.n_chars = sum(len(x) for x in new_pages)
    layout = {
        "tables": len(tables_meta),
        "figures": len(fig_items),
        "table_list": tables_meta[:50],
        "chars_before": before,
        "chars_after": doc.n_chars,
    }
    touch(doc, layout=layout, figure_items=fig_items)
    return layout
