"""공개 한국어 벤치마크 가져오기: Hugging Face Hub 의 MTEB 형식(parquet) 데이터를 내려받아 이 앱의 데이터셋(JSON)으로 바꾼다.

- 검색: corpus(_id, title, text) · queries(_id, text) · qrels(query-id, corpus-id, score)
- STS: sentence1, sentence2, score(0~5)
코퍼스가 크면 질문을 표본으로 뽑고, 그 질문들의 정답 문서 + 무작위 방해 문서로 코퍼스를 줄인다(CPU 에서도 돌릴 수 있게).
"""

import random
from collections import defaultdict
from typing import Any

from app.core.jobs import Job
from app.stages.embedding import benchmark

CATALOG: list[dict[str, Any]] = [
    {
        "key": "autorag_ko", "type": "retrieval", "repo": "mteb/AutoRAGRetrieval", "split": "test", "prefix": "",
        "title": "AutoRAG 한국어 문서 검색", "license": "MIT",
        "description": "금융·공공·의료·법률·커머스 PDF 문서에서 뽑은 문단과 실제 업무형 질문 (질문 114 · 문서 720). RAG 평가에 가장 가까운 공개 세트.",
    },
    {
        "key": "ko_strategyqa", "type": "retrieval", "repo": "mteb/Ko-StrategyQA", "split": "dev", "prefix": "",
        "title": "Ko-StrategyQA", "license": "StrategyQA 원본 MIT (번역본 별도 표기 없음)",
        "description": "여러 문서를 이어 추론해야 하는 상식 질문의 한국어 번역 (질문 592 · 위키 문단 9,251). 질문 하나에 정답 문단이 여러 개.",
    },
    {
        "key": "publichealth_ko", "type": "retrieval", "repo": "mteb/PublicHealthQA", "split": "test", "prefix": "korean-",
        "title": "PublicHealthQA 한국어", "license": "CC BY-NC-SA 3.0 (비상업)",
        "description": "보건 기관의 코로나19 등 공중보건 FAQ 질문 → 답변 검색.",
    },
    {
        "key": "xpqa_ko", "type": "retrieval", "repo": "mteb/XPQARetrieval", "split": "test", "prefix": "kor-kor-",
        "title": "xPQA 한국어 상품 질문", "license": "CDLA-Sharing 1.0",
        "description": "쇼핑몰 상품 질문 → 상품 정보·리뷰 문장 검색 (실제 사용자 질문, 짧고 구어체).",
    },
    {
        "key": "korsts", "type": "sts", "repo": "mteb/KorSTS", "split": "test", "file": "data/test-00000-of-00001.parquet",
        "title": "KorSTS (test)", "license": "CC BY-SA 4.0",
        "description": "STS-B 의 한국어 번역. 문장쌍 1,376개, 0~5점.",
    },
    {
        "key": "klue_sts", "type": "sts", "repo": "mteb/KLUE-STS", "split": "validation", "file": "data/validation-00000-of-00001.parquet",
        "title": "KLUE-STS (validation)", "license": "CC BY-SA 4.0",
        "description": "한국어로 처음부터 만든 STS. 에어비앤비 리뷰·정책 브리핑·구어 문장쌍 519개, 0~5점.",
    },
]  # fmt: skip
BY_KEY = {c["key"]: c for c in CATALOG}


class ImportError_(ValueError):
    pass


def _read(repo: str, filename: str) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(repo, filename, repo_type="dataset")  # HF 캐시에 저장 (다시 가져올 때는 내려받지 않음)
    return pq.read_table(path).to_pylist()


def _retrieval_files(c: dict[str, Any]) -> dict[str, str]:
    return {part: f"{c['prefix']}{part}/{c['split']}-00000-of-00001.parquet" for part in ("corpus", "queries", "qrels")}


def build_retrieval(
    corpus: list[dict[str, Any]], queries: list[dict[str, Any]], qrels: list[dict[str, Any]],
    max_queries: int | None, max_corpus: int | None, seed: int = 0, max_chars: int = 4000,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:  # fmt: skip
    def rid(r: dict[str, Any]) -> str:  # MTEB 데이터마다 _id 또는 id
        return str(r["_id"] if "_id" in r else r["id"])

    corpus = [d | {"_id": rid(d)} for d in corpus]
    queries = [q | {"_id": rid(q)} for q in queries]
    rel: dict[str, set[str]] = defaultdict(set)
    for r in qrels:
        if float(r.get("score") or 0) > 0:
            rel[str(r["query-id"])].add(str(r["corpus-id"]))
    docs = {str(d["_id"]): d for d in corpus}
    qs = [q for q in queries if rel.get(str(q["_id"])) and rel[str(q["_id"])] & docs.keys()]
    rng = random.Random(seed)
    sampled = bool((max_queries and len(qs) > max_queries) or (max_corpus and len(docs) > max_corpus))
    if max_queries and len(qs) > max_queries:
        qs = rng.sample(qs, max_queries)
    needed = {d for q in qs for d in rel[str(q["_id"])] if d in docs}
    keep = set(needed)
    if max_corpus and len(docs) > max_corpus:
        others = [d for d in docs if d not in needed]
        keep |= set(rng.sample(others, max(0, min(len(others), max_corpus - len(needed)))))
    else:
        keep = set(docs)
    out_corpus = [
        {"id": i, "title": (docs[i].get("title") or "").strip(), "text": (docs[i].get("text") or "")[:max_chars]}
        for i in sorted(keep)
        if (docs[i].get("text") or "").strip()
    ]
    valid = {d["id"] for d in out_corpus}
    out_queries = [
        {"id": str(q["_id"]), "text": q["text"], "relevant": sorted(rel[str(q["_id"])] & valid)} for q in qs if rel[str(q["_id"])] & valid
    ]
    info = {
        "queries_total": len([q for q in queries if rel.get(str(q["_id"]))]),
        "corpus_total": len(docs),
        "sampled": sampled,
    }
    return out_corpus, out_queries, info


def import_benchmark(job: Job, key: str, max_queries: int | None = 300, max_corpus: int | None = 3000, seed: int = 0) -> dict[str, Any]:
    c = BY_KEY.get(key)
    if c is None:
        raise ImportError_(f"알 수 없는 공개 벤치마크: {key}")
    name = f"pub_{key}"
    if c["type"] == "sts":
        job.update(0.1, f"{c['repo']} 내려받는 중")
        rows = _read(c["repo"], c["file"])
        pairs = [
            {"s1": r["sentence1"], "s2": r["sentence2"], "score": float(r["score"])}
            for r in rows
            if r.get("sentence1") and r.get("sentence2")
        ]
        if max_queries and len(pairs) > max_queries:
            pairs = random.Random(seed).sample(pairs, max_queries)
        info = {"pairs_total": len(rows), "sampled": len(pairs) < len(rows)}
        data = {"name": name, "type": "sts", "pairs": pairs}
    else:
        files = _retrieval_files(c)
        parts = {}
        for n, (part, f) in enumerate(files.items()):
            job.update(0.1 + 0.25 * n, f"{c['repo']} {part} 내려받는 중")
            parts[part] = _read(c["repo"], f)
        job.update(0.85, "변환 중")
        corpus, queries, info = build_retrieval(parts["corpus"], parts["queries"], parts["qrels"], max_queries, max_corpus, seed)
        if not queries:
            raise ImportError_("정답이 있는 질문이 없습니다.")
        data = {"name": name, "type": "retrieval", "corpus": corpus, "queries": queries}
    size = f"질문 {len(data['queries'])} · 문서 {len(data['corpus'])}" if c["type"] == "retrieval" else f"문장쌍 {len(data['pairs'])}"
    data |= {
        "title": f"{c['title']}{' (표본)' if info['sampled'] else ''}",
        "description": f"{c['description']} — 출처 huggingface.co/datasets/{c['repo']} ({c['split']}), 라이선스 {c['license']}. 가져온 크기: {size}"
        + (
            f" (원본 질문 {info.get('queries_total')} · 문서 {info.get('corpus_total')} 에서 seed={seed} 표본)"
            if info["sampled"] and c["type"] == "retrieval"
            else ""
        ),
        "source": {
            "repo": c["repo"],
            "split": c["split"],
            "license": c["license"],
            "max_queries": max_queries,
            "max_corpus": max_corpus,
            "seed": seed,
        },
    }
    benchmark.validate_dataset(data)
    benchmark.save_user_dataset(data)
    return {"name": name, "title": data["title"], "size": size, **info}
