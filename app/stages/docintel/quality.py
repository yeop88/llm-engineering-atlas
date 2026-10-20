"""D5 청킹 지표 · D7 데이터 품질 점검.

D5 근거 보존율: 평가 세트의 근거 문장이 청크 하나에 온전히(글자 n-gram 60% 이상) 들어 있는 비율. 청크 경계가 근거를 자르면
어떤 청크를 찾아도 정답 근거 전체를 LLM 에 줄 수 없다 — 법률 자료에서 일부 근거가 경계에 걸쳐 어느 청크에도 온전히 없었다.
'온전히 있음' 판정은 2 RAG 평가와 같은 함수(evaluation.contains_evidence)를 쓴다.

D7 품질 보고: 청크 세트마다 길이 분포 · 짧은 청크 · 똑같은 청크 · 반복 줄 · 깨진 글자 · 청크가 없는 문서를 한눈에 — 통계만 보면 못 찾고
(법령 반복 행은 실제 글을 열어 발견했다) 기록이 없으면 같은 실수를 반복하므로, 문제 예시 글을 함께 보여 준다.
"""

import hashlib
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Chunk, ChunkSet, Document, EvalSet
from app.stages.docintel.parsing import broken_ratio
from app.stages.rag import chunking, evaluation

SHORT = 50


def evidence_preservation(db: Session, cs: ChunkSet, s: EvalSet, limit_examples: int = 15) -> dict[str, Any]:
    by_doc: dict[int, list[str]] = defaultdict(list)
    for did, text in db.execute(select(Chunk.document_id, Chunk.text).where(Chunk.chunk_set_id == cs.id)):
        by_doc[did].append(text)
    all_texts = [t for ts in by_doc.values() for t in ts]
    n = kept = 0
    broken = []
    for it in s.items:
        for ev in evaluation.evidences_of(it):
            n += 1
            pool = [t for d in it.get("doc_ids") or [] for t in by_doc.get(d, [])] or all_texts
            if any(evaluation.contains_evidence(t, ev) for t in pool):
                kept += 1
                continue
            g = evaluation.grams(ev)
            best = max((evaluation.coverage(g, evaluation.grams(t)) for t in pool), default=0.0)
            if len(broken) < limit_examples:
                broken.append({"item_id": it.get("id"), "evidence": ev[:200], "best_coverage": round(best, 3)})
    return {"chunk_set_id": cs.id, "eval_set_id": s.id, "n_evidences": n, "preserved": kept, "rate": round(kept / n, 4) if n else None,
            "broken": broken}  # fmt: skip


def quality_report(db: Session, cs: ChunkSet) -> dict[str, Any]:
    rows = db.execute(select(Chunk.id, Chunk.document_id, Chunk.text, Chunk.meta).where(Chunk.chunk_set_id == cs.id)).all()
    texts = [r.text for r in rows if not (r.meta or {}).get("media")]
    lengths = [len(t) for t in texts]
    hashes = Counter(hashlib.md5(t.strip().encode()).hexdigest() for t in texts)
    dup = sum(n - 1 for n in hashes.values() if n > 1)
    lines = Counter(ln.strip() for t in texts for ln in t.splitlines() if len(ln.strip()) >= 8)
    repeated = [(ln, n) for ln, n in lines.most_common(10) if n >= 5]
    br = [(r.id, broken_ratio(r.text)) for r in rows if not (r.meta or {}).get("media")]
    bad_chars = [i for i, b in br if b > 0.02]
    docs = set(db.scalars(select(Document.id).where(Document.collection_id == cs.collection_id)))
    with_chunks = {r.document_id for r in rows}
    empty_docs = sorted(docs - with_chunks)
    short = [t for t in texts if len(t) < SHORT]
    issues = []
    if texts and len(short) / len(texts) > 0.1:
        issues.append(f"짧은 청크(<{SHORT}자)가 {len(short) / len(texts):.0%} — '짧은 청크 합치기'(merge_below)를 고려하세요.")
    if texts and dup / len(texts) > 0.02:
        issues.append(f"똑같은 청크 {dup}개 — 중복 문서 · 반복 머리말을 정리하세요(D4).")
    if repeated:
        issues.append(f"여러 청크에 반복되는 줄 {len(repeated)}종 — 머리말 · 꼬리말일 수 있습니다(D4 정제).")
    if bad_chars:
        issues.append(f"깨진 글자가 많은 청크 {len(bad_chars)}개 — 파싱 점검(D2).")
    if empty_docs:
        issues.append(f"청크가 하나도 없는 문서 {len(empty_docs)}개 — 글자 없는 PDF(OCR 필요)이거나 최소 글자 수에 걸렸습니다.")
    return {
        "chunk_set_id": cs.id, "name": cs.name, "strategy": cs.strategy, "n_chunks": len(rows), "n_text": len(texts),
        "n_media": len(rows) - len(texts), "length": chunking.stats(lengths) if lengths else {},
        "short": {"n": len(short), "rate": round(len(short) / len(texts), 4) if texts else 0, "examples": short[:5]},
        "duplicates": {"n": dup, "rate": round(dup / len(texts), 4) if texts else 0},
        "repeated_lines": [{"line": ln[:100], "n": n} for ln, n in repeated],
        "broken_chunks": len(bad_chars), "empty_docs": empty_docs[:50], "issues": issues,
    }  # fmt: skip
