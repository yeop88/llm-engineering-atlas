"""D4 정제 · 중복 · 판(버전): 머리말 · 쪽 번호 같은 반복 잡음을 걷고, 거의 같은 문서와 개정판을 묶어 최신판만 검색되게 한다.

잡음 · 중복은 검색 상위를 차지해 정답을 밀어내고, 개정판이 섞이면 옛 조항으로 답한다.
- 반복 줄: 한 문서의 여러 쪽(절반 이상, 최소 3쪽)에 같은 모양(숫자를 # 로 바꿔 비교)으로 나오는 줄 = 머리말 · 꼬리말 · 쪽 번호
- 거의 같은 문서: 글자 5-gram 집합의 자카드 유사도 — 임베딩 없이 바로 계산되고, '표현만 조금 바뀐 같은 문서'를 잘 잡는다
- 판 묶음: 파일 이름에서 확장자 · 날짜 · '개정' · 'v2' · '(최종)' 같은 표기를 지운 이름이 같은 문서 → 날짜(meta.date) · 올린 순서가 늦은 것이 최신
  (문서 제목 · 글이 비슷한 것으로는 묶지 않는다 — 판례처럼 같은 서식의 다른 문서가 한 묶음이 됐다)
"""

import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Document
from app.stages.docintel.incremental import touch

_PAGE_NO = re.compile(
    r"^\s*[-–—]?\s*(\d{1,4}|[ivxlc]{1,6})\s*(/\s*\d{1,4})?\s*[-–—]?\s*$|^\s*(page|쪽|페이지)\s*\d+(\s*/\s*\d+)?\s*$", re.I
)
_VERSION_MARK = re.compile(
    r"(\d{4}[.\-_년]\s*\d{1,2}[.\-_월]?\s*(\d{1,2}일?)?)|(\(?(개정판|개정|수정본|수정|최종본|최종|최신본|최신|확정본|확정|초안|사본|복사본|draft|final|copy)\)?)|(v\s?\d+(\.\d+)*)|(\(\d+\))|(_\d+$)",
    re.I,
)


def _shape(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def boilerplate(pages: list[str], min_share: float = 0.5) -> set[str]:
    """여러 쪽에 반복되는 줄 모양."""
    if len(pages) < 3:
        return set()
    seen: Counter[str] = Counter()
    for p in pages:
        seen.update({_shape(ln) for ln in p.splitlines() if ln.strip()})
    need = max(3, int(len(pages) * min_share))
    return {s for s, n in seen.items() if n >= need and 0 < len(s) <= 120}


def clean_pages(pages: list[str]) -> tuple[list[str], dict[str, int]]:
    rep = boilerplate(pages)
    out, removed, page_nos = [], 0, 0
    for p in pages:
        keep = []
        for ln in p.splitlines():
            if _PAGE_NO.match(ln):
                page_nos += 1
                continue
            if ln.strip() and _shape(ln) in rep:
                removed += 1
                continue
            keep.append(ln)
        out.append("\n".join(keep).strip())
    return out, {"repeated_lines": removed, "page_numbers": page_nos, "patterns": len(rep)}


def apply_clean(doc: Document) -> dict[str, int]:
    if (doc.meta or {}).get("media_items"):
        return {"repeated_lines": 0, "page_numbers": 0, "patterns": 0}
    new, stats = clean_pages(doc.pages or [])
    if stats["repeated_lines"] or stats["page_numbers"]:
        doc.pages = new
        doc.n_chars = sum(len(p) for p in new)
        touch(doc, cleaned=stats)
    return stats


def shingles(text: str, n: int = 5, sample: int = 4) -> set[int]:
    """글자 n-gram 해시 집합. 해시의 1/sample 만 남겨(같은 규칙이라 두 문서에서 같은 것이 남음) 긴 문서도 빠르게 비교한다."""
    t = re.sub(r"\s+", "", text)
    return {h for i in range(max(0, len(t) - n + 1)) if (h := hash(t[i : i + n])) % sample == 0}


def jaccard(a: set[int], b: set[int]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def base_title(title: str) -> str:
    t = _VERSION_MARK.sub("", title or "")
    return re.sub(r"[\s_\-.()\[\]]+", "", t).lower()


def near_duplicates(docs: list[Document], threshold: float = 0.85) -> list[dict[str, Any]]:
    texts = [(d, shingles("\n".join(d.pages or []))) for d in docs if not (d.meta or {}).get("media_items")]
    pairs = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            s = jaccard(texts[i][1], texts[j][1])
            if s >= threshold:
                pairs.append(
                    {
                        "a": texts[i][0].id,
                        "b": texts[j][0].id,
                        "a_name": texts[i][0].filename,
                        "b_name": texts[j][0].filename,
                        "sim": round(s, 3),
                    }
                )
    return sorted(pairs, key=lambda p: -p["sim"])


def identity(d: Document) -> str:
    """판 묶음의 '같은 문서' 기준 이름 — 파일 이름(확장자 · 판 표기를 지운 것)에서 뽑는다.

    제목(d.title)을 쓰면 안 된다: 판례는 파서가 첫 줄의 '【전문】【원고,피상고인】' 같은 문서 종류 공통 머리를 제목으로 잡아,
    서로 다른 판례 수십 건이 한 문서의 판으로 묶이고 대부분 '새 판에 밀림'이 됐다(법률 컬렉션 실측).
    파일 이름에는 사건번호 · 법령 이름처럼 문서를 구별하는 글이 남으므로 그것을 기준으로 한다(확장자를 지워 hwp · pdf 같은 판도 한 묶음)."""
    stem = d.filename.rsplit(".", 1)[0] if "." in (d.filename or "") else (d.filename or "")
    return base_title(stem) or base_title(d.title or "")


def version_groups(docs: list[Document], dup_pairs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """판 묶음: 기준 이름(identity)이 같은 문서끼리.

    예전에는 '거의 같은 문서' 쌍도 합쳤지만 뺐다 — 같은 서식을 쓰는 다른 문서(판례 · 서식 문서)는 글이 많이 겹쳐도 판이 아니고,
    잘못 묶이면 멀쩡한 문서가 '최신판만' 검색에서 사라진다. 거의 같은 문서는 따로 보여 주고 사람이 판단한다(dup_pairs 는 호환용으로만 받음)."""
    by_id: dict[str, list[Document]] = {}
    for d in docs:
        if key := identity(d):
            by_id.setdefault(key, []).append(d)
    out = []
    for key, members in by_id.items():
        if len(members) < 2:
            continue
        # 최신: 문서 날짜(meta.date)가 있으면 그것, 없으면 올린 순서
        members.sort(key=lambda d: (str((d.meta or {}).get("date") or ""), d.created_at), reverse=True)
        out.append({"group": key, "latest": members[0].id,
                    "members": [{"id": d.id, "filename": d.filename, "date": (d.meta or {}).get("date"), "superseded": i > 0}
                                for i, d in enumerate(members)]})  # fmt: skip
    return out


def analyze(db: Session, collection_id: int, threshold: float = 0.85) -> dict[str, Any]:
    docs = list(db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)))
    dups = near_duplicates(docs, threshold)
    groups = version_groups(docs, dups)
    boiler = []
    for d in docs:
        rep = boilerplate(d.pages or [])
        pn = sum(1 for p in d.pages or [] for ln in p.splitlines() if _PAGE_NO.match(ln))
        if rep or pn:
            boiler.append(
                {
                    "id": d.id,
                    "filename": d.filename,
                    "patterns": sorted(rep)[:5],
                    "page_numbers": pn,
                    "cleaned": (d.meta or {}).get("cleaned"),
                }
            )
    return {"n_docs": len(docs), "near_duplicates": dups[:100], "version_groups": groups, "boilerplate": boiler}


def apply_versions(db: Session, groups: list[dict[str, Any]]) -> int:
    """판 묶음 결과를 문서 meta 에 적는다(version_group · superseded). '최신판만' 검색 필터가 이 표시를 본다."""
    n = 0
    for g in groups:
        for m in g["members"]:
            d = db.get(Document, m["id"])
            if d is None:
                continue
            meta = dict(d.meta or {}) | {"version_group": g["group"]}
            if m["superseded"]:
                meta["superseded"] = True
                n += 1
            else:
                meta.pop("superseded", None)
            d.meta = meta
    return n
