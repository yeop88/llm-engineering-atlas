"""법률 도메인 도구: 조문 · 판례 번호 찾기와 답변의 인용 형식 검사.

왜 따로 두나
- 법률 질문은 "근로기준법 제23조", "대법원 2019다12345" 처럼 **정확한 번호**로 묻고 답한다. 임베딩 · BM25 검색은 번호를
  잘 못 맞춘다(제23조와 제24조는 글이 비슷하고, 숫자는 형태소 분석에서 의미가 약하다). 번호를 알면 바로 찾는 편이 정확하고 싸다.
- LLM 은 그럴듯한 조문 번호 · 사건번호를 지어낸다. 문장별 근거 검증(글자 · 의미)은 "제23조"를 "제32조"로 바꾼 것을
  거의 못 잡는다(나머지 글이 같으므로). 그래서 답변에 나온 번호를 뽑아 ① 인용한 근거에 실제로 있는지 ② 컬렉션에 있는 조문 · 판례인지 따로 본다.

문서 이름 규칙(공개 자료 가져오기 `labor_lease_law` 와 같은 형식): 법령은 `<법령명>.txt`(본문에 `제N조(제목)` 줄),
판례는 `판례 <사건번호> <사건명>.txt`(메타 `source.case_no`). 직접 올린 문서도 같은 형식이면 그대로 쓴다.
"""

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Chunk, Document

# 제23조, 제23조의2, 제23조 제1항 — '23조'처럼 '제'를 빼고 써도 잡는다(답변에서 흔함)
ARTICLE = re.compile(r"제?\s?(\d{1,4})\s?조(?:\s?의\s?(\d{1,2}))?(?:\s?제?\s?(\d{1,2})\s?항)?")
# 법령명: '…법' · '…법률' 뒤에 ' 시행령' · ' 시행규칙'이 붙을 수 있다 + 조문. 시행령을 따로 두면 '주택임대차보호법 시행령 제28조'의
# 법령명이 '시행령'만 남아 엉뚱한 시행령에서 찾았다(조문 번호 세트를 만들다 발견). 법령명만으로 된 대통령령(…령 · …규칙)도 잡는다.
STATUTE = re.compile(r"([가-힣·]{2,40}?(?:법률|법)(?:\s?(?:시행령|시행규칙))?|[가-힣·]{2,40}?(?:령|규칙))\s?" + ARTICLE.pattern)
# 사건번호: 2019다12345, 2020도1234, 2018두56789, 2017헌마123 …
CASE_NO = re.compile(r"((?:19|20)\d{2})\s?(다|도|두|누|나|가합|가단|가소|므|스|마|카|후|허|헌마|헌바|헌가|추|재다|재두)\s?(\d{1,6})")


def norm_article(num: str, sub: str | None = None, para: str | None = None) -> str:
    return f"제{int(num)}조" + (f"의{int(sub)}" if sub else "") + (f" 제{int(para)}항" if para else "")


def parse_refs(text: str) -> list[dict[str, Any]]:
    """글에서 법령 조문 · 판례 번호를 뽑아 정규화. 같은 것은 한 번만."""
    out: dict[str, dict[str, Any]] = {}
    for m in STATUTE.finditer(text):
        law, num, sub, para = m.group(1), m.group(2), m.group(3), m.group(4)
        art = norm_article(num, sub)
        key = f"{law} {art}"
        out.setdefault(key, {"kind": "statute", "law": law, "article": art, "paragraph": int(para) if para else None,
                             "ref": key + (f" 제{int(para)}항" if para else ""), "span": m.group(0)})  # fmt: skip
    for m in CASE_NO.finditer(text):
        case = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        out.setdefault(case, {"kind": "precedent", "case_no": case, "ref": case, "span": m.group(0)})
    return list(out.values())


def _law_docs(db: Session, collection_id: int, law: str) -> list[Document]:
    docs = db.scalars(select(Document).where(Document.collection_id == collection_id)).all()
    # 띄어쓰기는 빼고 비교한다('주택임대차보호법시행령' · '주택임대차보호법 시행령' 모두 같은 문서)
    stem = lambda d: re.sub(r"\s+", "", d.filename.rsplit(".", 1)[0])  # noqa: E731
    law = re.sub(r"\s+", "", law)
    exact = [d for d in docs if stem(d) == law]
    # '근로기준법' 질문에 '근로기준법 시행령'까지 섞이지 않게 정확히 같은 이름 우선, 없으면 포함 관계
    return exact or [d for d in docs if not d.filename.startswith("판례") and (law in stem(d) or stem(d) in law)]


def chunk_set_of(db: Session, config: dict[str, Any]) -> int | None:
    """검색 설정에서 청크 세트 찾기(BM25 는 chunk_set_id, 의미 검색은 인덱스의 청크 세트)."""
    if config.get("chunk_set_id"):
        return int(config["chunk_set_id"])
    if config.get("index_id"):
        from app.core.db import VectorIndex

        idx = db.get(VectorIndex, int(config["index_id"]))
        return idx.chunk_set_id if idx else None
    return None


def lookup_fn_for(db: Session, chunk_set_id: int | None) -> Callable[[str], list[dict[str, Any]]] | None:
    """청크 세트가 정해진 경우에만 조회 함수를 만든다(에이전트 도구 · 인용 검사가 같은 함수를 쓰게)."""
    return (lambda ref: lookup(db, chunk_set_id, ref)) if chunk_set_id else None


def lookup(db: Session, chunk_set_id: int, ref: str, limit: int = 3) -> list[dict[str, Any]]:
    """'근로기준법 제23조' · '2019다12345' 같은 번호로 청크를 바로 찾는다. 검색 결과와 같은 모양(dict)으로 돌려준다."""
    from app.core.db import ChunkSet

    cs = db.get(ChunkSet, chunk_set_id)
    if cs is None:
        return []
    refs = parse_refs(ref)
    if not refs:  # 법령명 없이 '제23조'만 준 경우 — 컬렉션의 모든 법령에서
        m = ARTICLE.search(ref)
        refs = [{"kind": "statute", "law": "", "article": norm_article(m.group(1), m.group(2))}] if m else []
    out: list[dict[str, Any]] = []
    for r in refs:
        if r["kind"] == "statute":
            docs = _law_docs(db, cs.collection_id, r["law"]) if r["law"] else [
                d for d in db.scalars(select(Document).where(Document.collection_id == cs.collection_id)) if not d.filename.startswith("판례")]  # fmt: skip
            # 조문 머리('제23조(' 또는 줄 맨 앞 '제23조 ')로 시작하는 곳만 — 본문 속 '제23조에 따른' 같은 언급은 빼려고
            head = re.compile(rf"(^|\n)\s*{re.escape(r['article'])}(\(|\s)")
            for d in docs:
                rows = db.scalars(
                    select(Chunk).where(Chunk.chunk_set_id == chunk_set_id, Chunk.document_id == d.id).order_by(Chunk.idx)
                ).all()
                hits = [c for c in rows if head.search(c.text) or str((c.meta or {}).get("heading", "")).startswith(r["article"])]
                out += [_row(c, d, r["ref"]) for c in hits[:limit]]
        else:
            for d in db.scalars(select(Document).where(Document.collection_id == cs.collection_id)):
                case = str(((d.meta or {}).get("source") or {}).get("case_no", "")).replace(" ", "")
                if case == r["case_no"] or r["case_no"] in d.filename.replace(" ", ""):
                    rows = db.scalars(
                        select(Chunk).where(Chunk.chunk_set_id == chunk_set_id, Chunk.document_id == d.id).order_by(Chunk.idx).limit(limit)
                    ).all()
                    out += [_row(c, d, r["ref"]) for c in rows]
    return out


def _row(c: Chunk, d: Document, ref: str) -> dict[str, Any]:
    return {"chunk_id": c.id, "document_id": d.id, "filename": d.filename, "page": c.page, "text": c.text, "score": 1.0, "lookup": ref}


def _mentions(text: str, ref: dict[str, Any]) -> bool:
    flat = re.sub(r"\s+", "", text)
    if ref["kind"] == "precedent":
        return ref["case_no"] in flat
    # 조문: 근거 글 안에 같은 조문 번호가 있어야 한다(법령 문서 근거면 법령명은 파일 이름에 있으므로 번호만 본다)
    return re.sub(r"\s+", "", ref["article"]) in flat


def check_citations(answer_text: str, sources: list[dict[str, Any]],
                    lookup_fn: Callable[[str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:  # fmt: skip
    """답변에 나온 조문 · 판례 번호 검사.
    - in_sources: 답변이 인용한 근거 글(또는 그 근거의 파일 이름)에 그 번호가 있다 → 정상
    - in_collection: 근거에는 없지만 컬렉션에는 있다 → 근거 밖 지식으로 답함(맞을 수도 있지만 확인 필요)
    - not_found: 컬렉션 어디에도 없다 → 지어낸 번호일 가능성이 크다
    """
    refs = parse_refs(answer_text)
    rows = []
    for r in refs:
        hit = next((i + 1 for i, s in enumerate(sources) if _mentions(s.get("text", "") + " " + s.get("filename", ""), r)), None)
        status = "in_sources" if hit else None
        if not hit and lookup_fn is not None:
            status = "in_collection" if lookup_fn(r["ref"]) else "not_found"
        rows.append({"ref": r["ref"], "kind": r["kind"], "status": status or "unchecked", "source": hit})
    bad = [x for x in rows if x["status"] == "not_found"]
    return {"refs": rows, "n": len(rows), "n_in_sources": sum(x["status"] == "in_sources" for x in rows),
            "n_not_found": len(bad), "ok": not bad}  # fmt: skip
