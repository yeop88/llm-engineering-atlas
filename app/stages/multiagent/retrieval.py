"""MA4 검색 전문가 에이전트(Self-RAG) · MA2 멀티모달 리랭킹.

검색 → 충분성 판단 → 부족하면 질의를 고쳐 다시 찾기(상한 3번). 충분성은 규칙으로 먼저 본다: 질문의 핵심 낱말이 근거에 얼마나
나오나(덮음) · 1위 점수. LLM 판정은 규칙이 애매할 때만 — 판정 자체가 LLM 한 번이라 매 질문에 부르면 검색보다 비싸다.
질의 고치기는 검색 향상(4)의 재작성을 쓴다. 그림 후보가 있으면 비전 LLM 이 질문과 그림을 함께 보고 0~3점을 매겨 다시 줄 세운다(MA2).
"""

import re
from collections.abc import Callable
from typing import Any

from app.core import llm, media_store
from app.stages.search_lab import enhance

SearchFn = Callable[[str], list[dict[str, Any]]]
STOP = {"무엇", "어떻게", "언제", "어디", "있나요", "인가요", "하나요", "되나요", "알려", "주세요", "대해", "관련", "경우", "그리고"}


def keywords(q: str) -> list[str]:
    # 불용어는 조사를 떼기 전 낱말로도 본다 — 떼고 나서만 보면 '주세요 → 주세' · '있나요 → 있나' 처럼 '요'로 끝나는 불용어가
    # 빠지지 않고 핵심 낱말로 남아, 근거와 상관없이 덮음이 낮아진다(멀쩡한 검색이 '부족'으로 판정돼 재검색 비용이 든다).
    raw = [t for t in re.findall(r"[가-힣A-Za-z0-9-]{2,}", q) if t not in STOP]
    toks = [re.sub(r"(은|는|이|가|을|를|에|에서|의|도|로|으로|와|과|요)$", "", t) for t in raw]
    return [t for t in dict.fromkeys(toks) if len(t) >= 2 and t not in STOP]


def coverage(question: str, results: list[dict[str, Any]]) -> float:
    kw = keywords(question)
    if not kw:
        return 1.0
    text = " ".join((r.get("text") or "") + " " + (r.get("heading") or "") for r in results)
    return round(sum(1 for k in kw if k in text) / len(kw), 3)


JUDGE = '검색된 자료로 질문에 답할 수 있으면 {"enough": true}, 아니면 {"enough": false, "missing": "부족한 것 한 구절"} 만 JSON 으로 출력합니다.'


def sufficient(question: str, results: list[dict[str, Any]], lcfg: llm.LLMConfig | None, min_cov: float = 0.6) -> dict[str, Any]:
    cov = coverage(question, results)
    if not results:
        return {"enough": False, "coverage": 0.0, "by": "rule", "missing": "검색 결과 없음"}
    if cov >= 0.85 or lcfg is None:  # 확실히 덮었거나 판정할 LLM 이 없으면 규칙으로 끝
        return {"enough": cov >= min_cov, "coverage": cov, "by": "rule"}
    if cov < 0.3:
        return {"enough": False, "coverage": cov, "by": "rule", "missing": "핵심 낱말이 근거에 거의 없음"}
    ctx = "\n".join(f"[{i + 1}] {(r.get('text') or '')[:300]}" for i, r in enumerate(results[:5]))
    try:
        data, _ = llm.chat_json(lcfg, JUDGE, f"질문: {question}\n\n자료:\n{ctx}", max_tokens=120, temperature=0.0)
        return {"enough": bool(data.get("enough")), "coverage": cov, "by": "llm", "missing": data.get("missing", "")}
    except llm.LLMError, ValueError, AttributeError:
        return {"enough": cov >= min_cov, "coverage": cov, "by": "rule"}


def self_rag(question: str, search: SearchFn, lcfg: llm.LLMConfig | None, rounds: int = 3, k: int = 6) -> dict[str, Any]:
    log, pool, seen = [], [], set()
    query = question
    for r in range(rounds):
        res = search(query)[:k]
        for x in res:
            if x["chunk_id"] not in seen:
                seen.add(x["chunk_id"])
                pool.append(x | {"query": query, "round": r + 1})
        judge = sufficient(question, pool, lcfg)
        log.append({"round": r + 1, "query": query, "found": len(res), "pool": len(pool)} | judge)
        if judge["enough"] or lcfg is None or r == rounds - 1:
            break
        try:  # 부족하면 질의를 고친다 — 부족한 것을 덧붙여 재작성
            v = enhance.generate("rewrite", f"{question} {judge.get('missing', '')}".strip(), lcfg, n=1)
            nq = ((v.get("variants") or [{}])[0]).get("text")
        except llm.LLMError, ValueError:
            nq = None
        if not nq or nq == query:
            break
        query = nq
    return {"sources": pool[: k * 2], "rounds": log, "enough": log[-1]["enough"] if log else False}


VISION = '질문과 그림이 얼마나 관련 있는지 0(무관)~3(바로 답이 보임) 정수만 JSON 으로: {"score": n}'


def vision_rerank(question: str, sources: list[dict[str, Any]], lcfg: llm.LLMConfig | None, limit: int = 4) -> list[dict[str, Any]]:
    """그림 청크만 비전 LLM 이 다시 점수를 매겨 앞으로 — 글 임베딩이 그림 속 정보(표 · 도면)를 놓치는 경우를 보완.
    비전 모델이 아니거나 오류면 원래 순서 그대로(점수 없음)."""
    if lcfg is None:
        return sources
    imgs = [s for s in sources if s.get("media")][:limit]
    for s in imgs:
        try:
            rel = s.get("media_rel")
            data = media_store.resolve(rel).read_bytes() if rel else None
            if not data:
                continue
            d, _ = llm.chat_json(lcfg, VISION, f"질문: {question}", max_tokens=30, temperature=0.0, images=[data])
            s["vision_score"] = int(d.get("score", 0))
        except llm.LLMError, ValueError, AttributeError, OSError, media_store.MediaError:
            continue
    scored = [s for s in sources if "vision_score" in s]
    if not scored:
        return sources
    return sorted(sources, key=lambda s: (-(s.get("vision_score", -1)), sources.index(s)))
