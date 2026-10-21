"""규제 자료(RC1 · RC7): 컬렉션의 법령 문서 → 조항 목록, 국가법령정보 API 의 현행 · 시행예정 판과 비교(개정 감시).

컬렉션에는 법령마다 한 판만 넣는다(출처에 시행일 · MST). 개정 전후 조항이 한 검색 결과에 섞이면 이미 바뀐 의무를 근거로 통제를 만들게
된다 — 그래서 새 판은 컬렉션에 바로 섞지 않고 '바뀐 조항 → 영향받는 통제'를 먼저 보인 뒤 사람이 다시 가져오게 한다.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Document
from app.stages.compliance import lawapi
from app.stages.kg.extract import ART_HEAD, article_key, law_name

_MARK = re.compile(r"<(개정|신설|전문개정|본조신설|타법개정)[^>]*>")


def statute_docs(db: Session, collection_id: int) -> list[Document]:
    docs = db.scalars(select(Document).where(Document.collection_id == collection_id)).all()
    return [d for d in docs if ((d.meta or {}).get("source") or {}).get("kind") == "statute"]


def split_articles(text: str) -> dict[str, dict[str, str]]:
    """법령 본문 → {'제37조의2': {title, text}}. 조문 머리 줄('제N조(제목)')이 경계."""
    heads = list(ART_HEAD.finditer(text))
    out: dict[str, dict[str, str]] = {}
    for i, m in enumerate(heads):
        no = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        body = text[m.start() : heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        out.setdefault(no, {"title": m.group(3) or "", "text": body})
    return out


def articles(db: Session, collection_id: int) -> dict[str, dict[str, Any]]:
    """컬렉션의 모든 조항 → {article_key: {law, no, title, text, document_id, enforced}}. 키는 지식 그래프와 같은 모양('개인정보 보호법 제37조의2')."""
    out: dict[str, dict[str, Any]] = {}
    for d in statute_docs(db, collection_id):
        src = (d.meta or {}).get("source") or {}
        law = law_name(src.get("law") or re.sub(r"\.(txt|md)$", "", d.filename))
        for no, a in split_articles("\n".join(d.pages or [])).items():
            num = re.match(r"제(\d+)조(?:의(\d+))?", no)
            key = article_key(law, num.group(1), num.group(2)) if num else f"{law} {no}"
            out[key] = {
                "law": law,
                "no": no,
                "title": a["title"],
                "text": a["text"],
                "document_id": d.id,
                "enforced": src.get("enforced", ""),
            }
    return out


def _norm(t: str) -> str:
    """비교용: 띄어쓰기 · 개정 표시(<개정 2026.3.10>)를 뺀다 — 표시만 붙고 내용이 같은 조항을 '바뀜'으로 세지 않게.
    표시를 지우면 정말 바뀐 조항도 표시가 없어지지만, 내용이 바뀐 조항은 본문이 달라 그대로 잡힌다."""
    return re.sub(r"\s+", "", _MARK.sub("", t))


def diff(old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """두 판의 조항 비교 → 새로 생김 · 없어짐 · 내용이 바뀜."""
    added = [{"no": n, "title": new[n]["title"]} for n in new if n not in old]
    removed = [{"no": n, "title": old[n]["title"]} for n in old if n not in new]
    changed = [{"no": n, "title": new[n]["title"]} for n in new if n in old and _norm(old[n]["text"]) != _norm(new[n]["text"])]
    return {"added": added, "removed": removed, "changed": changed}


def import_docs(laws: list[str], date: str | None = None) -> list[dict[str, Any]]:
    """API 로 각 법령의 판(날짜에 시행 중이던 것, 없으면 현행)을 받아 컬렉션 문서로."""
    docs = []
    for name in laws:
        v = lawapi.version_on(name, date)
        docs.append(lawapi.document(lawapi.fetch(v["mst"], v["enforced"])))
    return docs


def revisions(db: Session, collection_id: int) -> list[dict[str, Any]]:
    """컬렉션의 각 법령 판 ↔ API 의 현행 · 시행예정 판. 바뀐 조항 키를 함께 돌려 영향 질의(graph.impact)에 바로 넣는다."""
    out = []
    for d in statute_docs(db, collection_id):
        src = (d.meta or {}).get("source") or {}
        law, have = law_name(src.get("law") or d.filename.removesuffix(".txt")), src.get("enforced", "")
        row: dict[str, Any] = {"law": law, "document_id": d.id, "have": have, "source": "api" if src.get("api") else "dataset"}
        try:
            vs = lawapi.versions(src.get("law") or law)
        except lawapi.LawApiError as exc:
            out.append(row | {"error": str(exc)})
            continue
        cur = next((v for v in vs if v["status"] == "현행"), None)
        row["current"] = cur["enforced"] if cur else None
        row["upcoming"] = [v["enforced"] for v in vs if v["status"] == "시행예정"]
        mine = split_articles("\n".join(d.pages or []))
        targets = ([("current", cur)] if cur and cur["enforced"] != have else []) + [
            ("upcoming", v) for v in vs if v["status"] == "시행예정"
        ][:1]  # 가장 가까운 시행예정 판 하나 — 다가오는 개정도 미리 본다
        for tag, v in targets:
            new = lawapi.fetch(v["mst"], v["enforced"])
            dd = diff(mine, {a["no"]: {"title": a["title"], "text": a["text"]} for a in new["articles"]})
            keys = [_key(law, x["no"]) for x in dd["changed"] + dd["removed"] + dd["added"]]
            row[tag + "_diff"] = dd | {"enforced": v["enforced"], "keys": keys}
        row["outdated"] = bool(cur and cur["enforced"] > have)
        out.append(row)
    return out


def _key(law: str, no: str) -> str:
    m = re.match(r"제(\d+)조(?:의(\d+))?", no)
    return article_key(law, m.group(1), m.group(2)) if m else f"{law} {no}"
