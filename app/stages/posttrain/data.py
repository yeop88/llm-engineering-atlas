"""P1 합성 데이터 · P2 선별 · 누수 방지: 학습 데이터(대화형 JSONL)를 모으고, 좋은 것만 남기고, 평가와 섞이지 않게 한다.

모으는 곳: LLM 증류 데이터(7a — 교사 답 중 검증을 통과한 것), 플라이휠 학습 데이터(FW4 — 사람이 고친 답), 합성 거절 예시(평가 세트의
'답 없는 질문'과 그 검색 근거 → '근거에서 찾을 수 없습니다'). 거절 예시를 넣는 이유: 답 있는 예시만 학습하면 모델이 근거가 없어도
그럴듯하게 답하는 쪽으로 기운다(법률 실측에서 답 없는 질문 거절은 13개 중 1개).

선별은 단계별로 남은 건수를 남긴다: 형식 오류 → 거의 같은 예시(질문 글자 바이그램 겹침 0.9 이상) → 평가 세트 누수(평가 질문과 0.8 이상
비슷하거나 같은 질문). 어느 단계에서 얼마나 빠졌는지 모르면 데이터가 왜 줄었는지 설명할 수 없다.
"""

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, EvalSet, PreferencePair
from app.stages.distill import llm_data
from app.stages.flywheel import review as fw_review
from app.stages.rag import answer, evaluation

DUP, LEAK = 0.9, 0.8


def root() -> Path:
    d = get_settings().data_dir / "posttrain"
    (d / "datasets").mkdir(parents=True, exist_ok=True)
    (d / "models").mkdir(parents=True, exist_ok=True)
    return d


def question_of(row: dict[str, Any]) -> str:
    user = next((m["content"] for m in row.get("messages") or row.get("prompt") or [] if m.get("role") == "user"), "")
    # 마지막 '질문:' 뒤 — 근거(FAQ 문서 등)에 '질문:' 글이 있으면 첫 번째에서 자르면 근거까지 질문으로 읽혀 중복 · 누수 검사가 틀린다
    return (user.rsplit("질문:", 1)[1] if "질문:" in user else user).strip()


def from_distill(names: list[str]) -> list[dict[str, Any]]:
    out = []
    for n in names:
        for ln in llm_data.file_path(n).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(json.loads(ln) | {"_src": f"distill:{n}"})
    return out


def _doc_context(db: Session, doc_ids: list[int], max_chars: int = 1500) -> str:
    texts = []
    for did in doc_ids[:3]:
        c = db.scalar(
            select(Chunk)
            .join(ChunkSet, ChunkSet.id == Chunk.chunk_set_id)
            .where(Chunk.document_id == did)
            .order_by(Chunk.id.desc(), Chunk.idx)
        )
        if c:
            texts.append(f"[{len(texts) + 1}] {c.text[:max_chars]}")
    return "\n\n".join(texts)


def from_flywheel(db: Session) -> list[dict[str, Any]]:
    out = []
    for r in fw_review.train_rows():
        if r.get("label") == "wrong" and not r.get("answer"):
            continue
        ctx = _doc_context(db, r.get("positive_doc_ids") or [])
        if not ctx:  # 근거 없는 학습 예시는 '근거 없이 답하기'를 가르친다 — 뺀다
            continue
        out.append(llm_data.sample(r["question"], ctx, r["answer"]) | {"_src": "flywheel"})
    return out


def synth_refusals(db: Session, eval_set_ids: list[int], search_fn: Any, limit: int = 50) -> list[dict[str, Any]]:
    """평가 세트의 답 없는 질문 → 실제 검색 근거와 함께 거절 예시. search_fn(collection_id, q) → 결과(연결 계층이 넘김)."""
    out = []
    for sid in eval_set_ids:
        s = db.get(EvalSet, sid)
        for it in (s.items if s else [])[:500]:
            if evaluation.answerable(it) or len(out) >= limit:
                continue
            ctx, _ = answer.build_context(search_fn(s.collection_id, it["query"])[:4], 3000)
            out.append(llm_data.sample(it["query"], ctx, f"{answer.NOT_FOUND}.") | {"_src": f"refusal:{sid}"})
    return out


def from_preferences(db: Session, collection_id: int | None = None) -> list[dict[str, Any]]:
    q = select(PreferencePair)
    if collection_id:
        q = q.where(PreferencePair.collection_id == collection_id)
    out = []
    for p in db.scalars(q):
        prompt = [{"role": "system", "content": answer.SYSTEM}, {"role": "user", "content": answer.user_prompt(p.question, p.context)}]
        out.append({"prompt": prompt, "chosen": [{"role": "assistant", "content": p.chosen}], "rejected": [{"role": "assistant", "content": p.rejected}],
                    "_src": f"pref:{p.source}"})  # fmt: skip
    return out


def select_rows(db: Session, rows: list[dict[str, Any]], exclude_sets: list[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report: dict[str, Any] = {"in": len(rows)}
    ok = [r for r in rows if question_of(r) and (r.get("messages") or (r.get("chosen") and r.get("rejected")))]
    report["format_ok"] = len(ok)
    kept: list[dict[str, Any]] = []
    for r in ok:
        q = question_of(r)
        if not any(fw_review.similar(q, question_of(k)) >= DUP for k in kept):
            kept.append(r)
    report["dedup"] = len(kept)
    evq = [it.get("query", "") for sid in exclude_sets if (s := db.get(EvalSet, sid)) for it in s.items or []]
    final, leaked = [], []
    for r in kept:
        q = question_of(r)
        hit = next((e for e in evq if fw_review.similar(q, e) >= LEAK), None)
        (leaked if hit else final).append(r)
    report["no_leak"] = len(final)
    report["leaked_examples"] = [question_of(r) for r in leaked[:10]]
    by: dict[str, int] = {}
    for r in final:
        k = r.get("_src", "?").split(":")[0]
        by[k] = by.get(k, 0) + 1
    report["by_source"] = by
    return final, report


def save(name: str, rows: list[dict[str, Any]], report: dict[str, Any], kind: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("데이터 이름은 영문 · 숫자 · _ · - 만")
    p = root() / "datasets" / f"{name}.jsonl"
    p.write_text(
        "".join(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    meta = {"name": name, "kind": kind, "n": len(rows), "report": report}
    (root() / "datasets" / f"{name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def datasets() -> list[dict[str, Any]]:
    out = []
    for m in sorted((root() / "datasets").glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append(json.loads(m.read_text(encoding="utf-8")))
    return out


def load(name: str) -> list[dict[str, Any]]:
    p = root() / "datasets" / f"{name}.jsonl"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name) or not p.exists():
        raise ValueError(f"데이터가 없습니다: {name}")
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
