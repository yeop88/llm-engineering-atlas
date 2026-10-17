"""검색 결과로 LLM 답변 만들기 (근거 번호 인용) 와 근거 검증.

검증은 두 단계다.
- 글자 기반(항상): 답변 문장마다 인용한 근거와의 글자 3-gram 포함률. 숫자·고유명사가 근거에 없으면 낮게 나온다.
- LLM 판정(선택): 문장마다 근거로 뒷받침되는지 LLM 에 물어 본다. 작은 모델은 판정이 흔들릴 수 있어 참고용.
"""

import re
from typing import Any

from app.core import llm
from app.core.korean import split_sentences
from app.stages.rag.evaluation import coverage, grams

NOT_FOUND = "근거에서 찾을 수 없습니다"
SYSTEM = (
    "당신은 주어진 근거 문서만으로 답하는 한국어 상담원입니다.\n"
    "규칙:\n"
    "1. 근거에 있는 내용만 사용하고, 추측하거나 근거에 없는 사실을 덧붙이지 마세요.\n"
    "2. 문장마다 그 문장의 근거 번호를 [1], [2] 처럼 문장 끝에 붙이세요.\n"
    f"3. 근거에 답이 없으면 '{NOT_FOUND}.' 라고만 답하세요.\n"
    "4. 간결하게 답하세요. 숫자·날짜·금액·조문 번호는 근거 표현 그대로 쓰세요."
)
SUPPORT_OK = 0.5  # 문장의 글자 3-gram 중 이 비율 이상이 인용 근거에 있으면 '근거 있음'
SUPPORT_WEAK = 0.25
_CITE = re.compile(r"\[(\d{1,2}(?:\s*[,，]\s*\d{1,2})*)\]")


def build_context(results: list[dict[str, Any]], max_chars: int = 6000) -> tuple[str, list[dict[str, Any]]]:
    """검색 결과 → 번호 붙인 근거 문자열. 길이 한도를 넘는 결과는 뺀다."""
    parts, used, total = [], [], 0
    for r in results:
        head = r.get("filename") or ""
        if r.get("page"):
            head += f" p.{r['page']}"
        if r.get("heading"):
            head += f" · {r['heading']}"
        block = f"[{len(used) + 1}] ({head})\n{r['text'].strip()}"
        if used and total + len(block) > max_chars:
            break
        parts.append(block)
        used.append(r)
        total += len(block)
    return "\n\n".join(parts), used


def user_prompt(question: str, context: str) -> str:
    return f"근거:\n{context}\n\n질문: {question}"


def citations(text: str) -> list[int]:
    out: list[int] = []
    for m in _CITE.finditer(text):
        for n in re.split(r"[,，]", m.group(1)):
            k = int(n)
            if k not in out:
                out.append(k)
    return out


def verify_lexical(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """문장별 근거 포함률. 인용 번호가 범위를 벗어나면 '잘못된 인용'."""
    src_grams = [grams(s["text"], 3) for s in sources]
    sentences = []
    invalid: set[int] = set()
    refused = NOT_FOUND.replace(" ", "") in answer.replace(" ", "")
    for sent in split_sentences(answer):
        cited = citations(sent)
        bad = [c for c in cited if not 1 <= c <= len(sources)]
        invalid |= set(bad)
        body = _CITE.sub("", sent).strip()
        g = grams(body, 3)
        valid = [c for c in cited if c not in bad]
        cited_cov = coverage(g, set().union(*(src_grams[c - 1] for c in valid))) if valid and g else 0.0
        best_cov, best = max(((coverage(g, sg), i + 1) for i, sg in enumerate(src_grams)), default=(0.0, None)) if g else (0.0, None)
        if NOT_FOUND.replace(" ", "") in body.replace(" ", ""):
            status = "refusal"
        elif not cited:
            status = "uncited"
        elif cited_cov >= SUPPORT_OK:
            status = "supported"
        elif cited_cov >= SUPPORT_WEAK:
            status = "weak"
        else:
            status = "unsupported"
        sentences.append({
            "text": sent, "citations": cited, "status": status,
            "support": round(cited_cov, 3), "best_source": best, "best_support": round(best_cov, 3),
        })  # fmt: skip
    claims = [s for s in sentences if s["status"] != "refusal"]
    supported = sum(1 for s in claims if s["status"] == "supported")
    return {
        "sentences": sentences,
        "invalid_citations": sorted(invalid),
        "refused": refused,
        "supported_ratio": round(supported / len(claims), 3) if claims else None,
        "cited_sources": sorted({c for s in sentences for c in s["citations"] if 1 <= c <= len(sources)}),
    }


JUDGE_SYSTEM = "당신은 답변이 근거 문서로 뒷받침되는지 엄격하게 판정하는 검토자입니다. 반드시 JSON 만 출력합니다."


def verify_llm(cfg: llm.LLMConfig, question: str, context: str, sentences: list[str]) -> dict[str, Any]:
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    user = (
        f"근거:\n{context}\n\n질문: {question}\n\n답변 문장:\n{numbered}\n\n"
        "답변 문장마다 근거만으로 뒷받침되는지 판정하세요. 근거에 없는 숫자·사실이 하나라도 있으면 false 입니다.\n"
        '출력 형식: {"judgements": [{"n": 1, "supported": true, "reason": "짧은 이유"}]}'
    )
    obj, res = llm.chat_json(cfg, JUDGE_SYSTEM, user, max_tokens=800, temperature=0.0)
    items = obj.get("judgements", []) if isinstance(obj, dict) else obj if isinstance(obj, list) else []
    by_n = {int(j.get("n", 0)): j for j in items if isinstance(j, dict) and str(j.get("n", "")).isdigit()}
    out = [
        {"supported": bool(by_n[i + 1].get("supported")), "reason": str(by_n[i + 1].get("reason", ""))[:200]} if i + 1 in by_n else None
        for i in range(len(sentences))
    ]
    judged = [o for o in out if o]
    return {
        "judgements": out,
        "supported_ratio": round(sum(o["supported"] for o in judged) / len(judged), 3) if judged else None,
        "seconds": res["seconds"],
        "usage": res["usage"],
    }


# ── 평가 세트로 답변 일괄 평가 ──────────────────────────────────────────────
def evaluate_one(
    cfg: llm.LLMConfig, question: str, results: list[dict[str, Any]], evidence: str, max_chars: int, max_tokens: int
) -> dict[str, Any]:
    from app.stages.rag.evaluation import contains_evidence

    context, sources = build_context(results, max_chars)
    res = llm.chat(cfg, SYSTEM, user_prompt(question, context), max_tokens=max_tokens, temperature=0.1)
    check = verify_lexical(res["text"], sources)
    with_ev = [i + 1 for i, s in enumerate(sources) if evidence and contains_evidence(s["text"], evidence)]
    return {
        "query": question,
        "answer": res["text"],
        "refused": check["refused"],
        "supported_ratio": check["supported_ratio"],
        "invalid_citations": check["invalid_citations"],
        "evidence_sources": with_ev,  # 근거 문장을 담은 근거 번호
        "evidence_retrieved": bool(with_ev) if evidence else None,
        "evidence_cited": bool(set(with_ev) & set(check["cited_sources"])) if evidence else None,
        "cited": check["cited_sources"],
        "seconds": res["seconds"],
        "output_tokens": res["usage"].get("output_tokens"),
    }


def summarize_eval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(bool(v) for v in vals) / len(vals), 3) if vals else None

    sup = [r["supported_ratio"] for r in rows if r["supported_ratio"] is not None]
    retrieved = [r for r in rows if r.get("evidence_retrieved")]
    return {
        "n": len(rows),
        "answer_rate": round(sum(not r["refused"] for r in rows) / len(rows), 3) if rows else None,
        "evidence_retrieved": rate("evidence_retrieved"),
        "evidence_cited": rate("evidence_cited"),
        # 근거가 검색됐을 때 LLM 이 그것을 인용한 비율 (검색 실패와 LLM 실패를 나눠 본다)
        "cited_given_retrieved": round(sum(bool(r["evidence_cited"]) for r in retrieved) / len(retrieved), 3) if retrieved else None,
        # 근거가 검색됐는데도 '찾을 수 없다'고 한 비율 (지나친 거절)
        "false_refusal": round(sum(r["refused"] for r in retrieved) / len(retrieved), 3) if retrieved else None,
        "sentence_support": round(sum(sup) / len(sup), 3) if sup else None,
        "invalid_citation_rate": round(sum(bool(r["invalid_citations"]) for r in rows) / len(rows), 3) if rows else None,
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1) if rows else None,
    }
