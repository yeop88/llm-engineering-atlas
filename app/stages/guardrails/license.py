"""G6 데이터 · 모델 라이선스 점검: 서비스 설정(컬렉션 · 임베딩 · 리랭커 · LLM)이 쓰는 자료와 모델의 라이선스를 모아 상업 사용 문제를 알린다.

자료 라이선스는 수집할 때 문서 meta(source.license 또는 license)에 남긴 것을 쓴다(공개 자료 가져오기가 문서마다 남긴다).
라이선스가 없는 문서는 '확인 필요'로 센다 — 직접 올린 사내 문서는 대개 문제없지만, 출처를 모르면 서비스에 넣기 전에 확인해야 한다.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Document, EmbeddingModel

NC = re.compile(r"(?i)\bNC\b|-NC-|non[- ]?commercial|비상업|research[- ]only|연구\s*목적")
GATED = re.compile(r"(?i)gemma|llama|custom|terms|동의")


def _level(lic: str, tags: list[str] | None = None) -> str:
    if NC.search(lic or "") or "non-commercial" in (tags or []):
        return "block"  # 상업 서비스에 쓸 수 없음
    if not lic:
        return "unknown"
    if GATED.search(lic):
        return "warn"  # 별도 약관 · 동의 필요
    return "ok"


def doc_license(meta: dict[str, Any] | None) -> str:
    m = meta or {}
    return str((m.get("source") or {}).get("license") or m.get("license") or "")


def check(
    db: Session, collection_id: int | None = None, model_ids: list[int] | None = None, llm_models: list[str] | None = None
) -> dict[str, Any]:
    """→ {"items": [{kind, name, license, level}], "summary": {level: n}, "ok"}. level: ok · warn(약관 확인) · unknown(출처 모름) · block(비상업)."""
    items: list[dict[str, Any]] = []
    if collection_id:
        by_lic: dict[str, list[str]] = {}
        for d in db.scalars(select(Document).where(Document.collection_id == collection_id)):
            by_lic.setdefault(doc_license(d.meta), []).append(d.filename)
        for lic, names in sorted(by_lic.items(), key=lambda x: -len(x[1])):
            items.append(
                {
                    "kind": "자료",
                    "name": f"문서 {len(names)}개 (예: {names[0]})",
                    "license": lic or "(기록 없음)",
                    "level": _level(lic),
                    "n": len(names),
                }
            )
    for mid in model_ids or []:
        m = db.get(EmbeddingModel, mid)
        if m:
            items.append({"kind": "리랭커" if m.kind == "reranker" else "임베딩 모델", "name": m.hf_id, "license": m.license or "(기록 없음)",
                          "level": _level(m.license, m.tags)})  # fmt: skip
    for name in llm_models or []:
        # 로컬 LLM 은 GGUF 파일 이름만 알 수 있어 이름으로 계열을 추정한다(Gemma · Llama 는 별도 약관)
        items.append({"kind": "LLM", "name": name, "license": "모델 카드 확인", "level": "warn" if GATED.search(name) else "unknown"})
    summary: dict[str, int] = {}
    for it in items:
        summary[it["level"]] = summary.get(it["level"], 0) + 1
    return {"items": items, "summary": summary, "ok": not summary.get("block")}
