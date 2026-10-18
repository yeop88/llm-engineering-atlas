"""검색 결과로 LLM 답변 만들기 (근거 번호 인용) 와 근거 검증.

검증은 두 단계다.
- 글자 기반(항상): 답변 문장마다 인용한 근거와의 글자 3-gram 포함률. 숫자·고유명사가 근거에 없으면 낮게 나온다.
- LLM 판정(선택): 문장마다 근거로 뒷받침되는지 LLM 에 물어 본다. 작은 모델은 판정이 흔들릴 수 있어 참고용.
"""

import re
from typing import Any

from app.core import llm
from app.core.korean import split_sentences, tokenize
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


def compress(results: list[dict[str, Any]], question: str, keep: int = 3, min_chars: int = 200) -> list[dict[str, Any]]:
    """근거 압축: 청크마다 질문과 형태소가 많이 겹치는 문장 keep 개만 원래 순서로 남긴다(사이가 빠지면 '…').

    왜: 로컬 LLM 의 질문당 시간 중 대부분(25~31초)이 근거 약 2,000토큰을 읽는 데 들었다. 근거 수를 줄이면 정답 청크를
    통째로 잃지만, 청크 안에서 관련 문장만 남기면 근거 수(=검색 재현율)는 그대로 두고 읽을 글만 줄일 수 있다.
    점수는 형태소 겹침(Kiwi)이라 모델 호출이 없다 — 압축 자체가 느리면 의미가 없으므로.
    위험: 질문과 단어가 겹치지 않는 근거 문장(바꿔 말한 질문)을 버릴 수 있다 — 평가에서 '근거 유지율'로 확인한다.
    짧은 청크(min_chars 미만)는 그대로 둔다(줄일 것이 없고 문맥이 깨진다).
    """
    q = set(tokenize(question))
    out = []
    for r in results:
        text = r["text"]
        sents = split_sentences(text) if len(text) >= min_chars else []
        if len(sents) <= keep:
            out.append(r)
            continue
        scored = [(len(q & set(tokenize(s))) / (len(set(tokenize(s))) ** 0.5 or 1), i) for i, s in enumerate(sents)]
        chosen = sorted(i for _, i in sorted(scored, reverse=True)[:keep])
        parts, prev = [], -1
        for i in chosen:
            if prev >= 0 and i != prev + 1:
                parts.append("…")
            parts.append(sents[i])
            prev = i
        out.append(r | {"text": " ".join(parts), "compressed_from": len(text)})
    return out


def user_prompt(question: str, context: str, image_note: str = "") -> str:
    return f"근거:\n{context}\n\n{image_note}질문: {question}"


IMAGE_MAX_SIDE = 768  # 긴 변 기준 축소 — 비전 모델은 그림을 수백 토큰으로 바꾸므로 원본 크기를 보내면 읽기 시간만 는다


def attach_images(db: Any, sources: list[dict[str, Any]], max_images: int = 3) -> tuple[list[bytes], str]:
    """근거 중 이미지 · 영상 장면 청크를 그림으로 첨부한다. → (JPEG 바이트들, 프롬프트에 붙일 안내).

    왜: 이미지 청크의 글은 파일 이름 · 장면 시각 정도라, 글만 넘기면 LLM 은 그림 내용을 모른 채 답한다(=근거 없이 지어냄).
    비전 모델(Gemma 4 + mmproj 등)에 그림 자체를 주고, 그림 근거도 [n] 으로 인용하게 해 같은 인용 표시를 쓴다.
    그림 수는 상한을 둔다(그림 한 장이 근거 글 수백 자만큼 읽기 시간을 쓴다).
    한계: 문장별 근거 검증(글자 · 의미)은 그림 내용을 모르므로 그림을 인용한 문장은 '근거 약함'으로 나올 수 있다 — LLM 판정을 함께 본다.
    """
    import io

    from app.core import media
    from app.core.db import Chunk

    images, notes = [], []
    for n, s in enumerate(sources, 1):
        if len(images) >= max_images or not s.get("media") or not s.get("chunk_id"):
            continue
        c = db.get(Chunk, s["chunk_id"])
        path = (c.meta or {}).get("media") if c else None
        if not path:
            continue
        try:
            im = media.open_image(path)
        except OSError:
            continue  # 파일이 지워졌으면 글 근거로만 쓴다
        im.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        images.append(buf.getvalue())
        notes.append(f"[{n}] = 첨부 그림 {len(images)}")
    if not notes:
        return images, ""
    return images, "그림 근거: " + ", ".join(notes) + ". 그림에서 본 내용도 그 번호로 인용하고, 그림에 보이지 않는 것은 쓰지 마세요.\n\n"


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


def verify(answer: str, sources: list[dict[str, Any]], method: str | None = None) -> dict[str, Any]:
    """근거 검증의 단일 진입점. 설정(ANSWER_VERIFY_METHOD)의 방식으로 — 답변 화면 · 평가 · 연결 비교 · 보상이 같은 방식을 쓰게.
    의미 · 혼합 검증이 실패하면(검증 모델 없음 등) 글자 검증으로 돌아가고 그 사실을 남긴다(평가가 멈추지 않게)."""
    from app.core.config import get_settings
    from app.stages.rag import verify as vf

    check = verify_lexical(answer, sources)
    method = method or get_settings().answer_verify_method
    if method in ("semantic", "hybrid"):
        try:
            return vf.apply(check, sources, method)
        except Exception as exc:  # noqa: BLE001 — 검증 방식 문제로 답변 평가 전체를 멈추지 않는다
            return check | {"method": "lexical", "fallback": f"{method} 실패: {type(exc).__name__}: {str(exc)[:120]}"}
    return check | {"method": "lexical"}


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
    cfg: llm.LLMConfig, item: dict[str, Any], results: list[dict[str, Any]], max_chars: int, max_tokens: int, no_cache: bool = False
) -> dict[str, Any]:
    """질문 항목 하나에 답하고 채점. item 전체를 받는 이유: 여러 근거(모두 인용해야 정답) · 답 없는 질문(거절해야 정답)을
    다른 평가들과 같은 규칙(evaluation.evidence_in_sources · answer_quality)으로 채점하려고."""
    from app.stages.rag import evaluation

    context, sources = build_context(results, max_chars)
    res = llm.chat(cfg, SYSTEM, user_prompt(item["query"], context), max_tokens=max_tokens, temperature=0.1, no_cache=no_cache)
    check = verify(res["text"], sources)
    row = {
        "query": item["query"],
        "type": item.get("type"),
        "answer": res["text"],
        "refused": check["refused"],
        "supported_ratio": check["supported_ratio"],
        "invalid_citations": check["invalid_citations"],
        "cited": check["cited_sources"],
        "answerable": evaluation.answerable(item),
        "seconds": res["seconds"],
        "output_tokens": res["usage"].get("output_tokens"),
        "timings": {
            k: res["usage"].get(k)
            for k in ("prompt_tokens_evaluated", "prompt_ms", "prompt_per_second", "generation_ms", "generation_per_second")
        },
    } | evaluation.evidence_in_sources(sources, item, check["cited_sources"])
    row["quality"] = evaluation.answer_quality(row, item)
    return row


def summarize_eval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(bool(v) for v in vals) / len(vals), 3) if vals else None

    # 답 없는 질문(answerable=False)은 '거절했는가'로 따로 센다 — 답이 있는 질문과 섞으면 거절이 좋은지 나쁜지가 뒤섞인다
    unans = [r for r in rows if r.get("answerable") is False]
    rows = (
        [r for r in rows if r.get("answerable") is not False] or rows
        if not unans
        else [r for r in rows if r.get("answerable") is not False]
    )
    sup = [r["supported_ratio"] for r in rows if r["supported_ratio"] is not None]
    retrieved = [r for r in rows if r.get("evidence_retrieved")]
    q = [r["quality"] for r in rows + unans if r.get("quality") is not None]
    return {
        "n": len(rows) + len(unans),
        "n_unanswerable": len(unans),
        # 답 없는 질문을 '찾을 수 없다'고 한 비율 — 낮으면 근거 밖에서 지어낸다(환각)
        "correct_refusal": round(sum(bool(r["refused"]) for r in unans) / len(unans), 3) if unans else None,
        "quality": round(sum(q) / len(q), 3) if q else None,
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
