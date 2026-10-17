"""파인튜닝 학습 데이터: 컬렉션 청크로 (질문, 정답 지문) 쌍을 만든다.

- llm: LLM 이 지문마다 질문을 만든다 (평가 세트 생성과 같은 프롬프트). 실제 질문과 가장 비슷하다.
- ict: Inverse Cloze Task — 지문의 한 문장을 질문으로, 그 문장을 뺀 나머지를 정답 지문으로 쓴다. LLM 이 필요 없다.

평가 세트의 근거 문장이 들어 있는 지문은 학습에서 뺀다(누수 방지). 빼지 않으면 시험 문제로 공부한 셈이라
학습 후 평가 점수가 실제보다 높게 나온다.
"""

import random
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm
from app.core.jobs import Job
from app.core.korean import split_sentences
from app.stages.rag import evaluation


def leak_filter(passages: list[dict[str, Any]], evidences: list[str]) -> tuple[list[dict[str, Any]], int]:
    if not evidences:
        return passages, 0
    ev = [evaluation.grams(e) for e in evidences if e.strip()]
    keep = []
    for p in passages:
        g = evaluation.grams(p["text"])
        if any(evaluation.coverage(e, g) >= evaluation.EVIDENCE_HIT for e in ev):
            continue
        keep.append(p)
    return keep, len(passages) - len(keep)


def ict_pairs(passages: list[dict[str, Any]], seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for p in passages:
        sents = split_sentences(p["text"])
        good = [s for s in sents if evaluation.sentence_quality(s) == 2] or [s for s in sents if evaluation.sentence_quality(s) == 1]
        if not good or len(sents) < 2:
            continue
        q = rng.choice(good)
        rest = " ".join(s for s in sents if s != q).strip()
        if len(rest) < 20:
            continue
        out.append({"anchor": q, "positive": rest, "source_chunk_id": p["chunk_id"], "document_id": p["document_id"], "type": "ict"})
    return out


def llm_pairs(
    cfg: llm.LLMConfig, passages: list[dict[str, Any]], styles: list[str], job: Job | None, concurrency: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items, stats = evaluation.from_llm(cfg, passages, styles, job, concurrency)
    text_of = {p["chunk_id"]: p["text"] for p in passages}
    pairs = [
        {
            "anchor": it["query"],
            "positive": text_of[it["source_chunk_id"]],
            "source_chunk_id": it["source_chunk_id"],
            "document_id": it["doc_ids"][0],
            "type": it["type"],
        }
        for it in items
        if it["source_chunk_id"] in text_of
    ]
    return pairs, stats


def build_pairs(
    db: Session,
    chunk_set_id: int,
    method: str,
    n_passages: int,
    evidences: list[str],
    cfg: llm.LLMConfig | None = None,
    styles: list[str] | None = None,
    min_chars: int = 200,
    seed: int = 0,
    job: Job | None = None,
    concurrency: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # 누수로 빠질 지문을 감안해 넉넉히 뽑은 뒤 거른다
    pool = evaluation.sample_passages(db, chunk_set_id, n_passages * 2, min_chars, seed)
    pool, leaked = leak_filter(pool, evidences)
    passages = pool[:n_passages]
    stats: dict[str, Any] = {"passages": len(passages), "excluded_for_eval": leaked, "method": method}
    if method == "llm":
        if cfg is None:
            raise ValueError("LLM 설정이 필요합니다.")
        pairs, gen = llm_pairs(cfg, passages, styles or ["fact", "paraphrase", "situation"], job, concurrency)
        stats["generation"] = {k: gen[k] for k in ("calls", "failed", "empty", "input_tokens", "output_tokens", "errors")}
    else:
        pairs = ict_pairs(passages, seed)
    # 같은 질문 제거
    seen, uniq = set(), []
    for p in pairs:
        k = p["anchor"].strip().lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(p)
    stats |= {
        "pairs": len(uniq),
        "documents": len({p["document_id"] for p in uniq}),
        "by_type": {t: sum(1 for p in uniq if p["type"] == t) for t in sorted({p["type"] for p in uniq})},
        "examples": [{"anchor": p["anchor"], "positive": p["positive"][:200]} for p in uniq[:5]],
    }
    return uniq, stats
