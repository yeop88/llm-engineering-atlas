"""KC1 토큰 단위 압축 · KC2 질문을 아는 압축 — 작은 공개 LM 으로 토큰 · 문장의 정보량을 재 지운다.

KC1: 근거를 작은 LM 에 통째로 넣어 토큰마다 놀람(-log p)을 잰다. 놀람이 낮은 토큰(앞 문맥으로 쉽게 맞히는 조사 · 반복)은 큰 모델도
알고 있는 정보라 지워도 덜 잃는다 — 놀람이 높은 순으로 목표 비율만큼 남긴다. 숫자 · 조문 번호(제n조) · 모델 코드 · 오류 코드 토큰은
놀람과 상관없이 남긴다(하나만 빠져도 답이 틀린다). 지운 뒤에는 남은 토큰을 원래 순서로 이어 붙인다.

KC2: 문장마다 '질문을 앞에 붙였을 때 놀람이 얼마나 줄었나'(대조 점수 = 질문 없을 때 평균 놀람 − 질문 있을 때)를 재, 질문과 관계 깊은
문장부터 남긴다(문장 단계). 남긴 문장 안에서는 질문을 붙인 채 KC1 처럼 토큰을 줄인다(토큰 단계). 질문을 모르는 압축은 질문에 필요한
흔한 정보를 '쉽다'며 지울 수 있다 — 같은 비율로 비교한다.

비교 기준선(LM 없음): 질문과 글자가 겹치는 문장만 남기기(lexical), 무작위 토큰 지우기(random) — 작은 LM 이 들인 비용만큼 나은지 보려고.
"""

import random
import re
from typing import Any

import torch

from app.stages.rag import evaluation

# 지키는 표시: 조문 번호 · 모델 · 오류 코드 · 숫자 — 보존률(preserved)과 같은 규칙. 원문에서 글자 범위로 찾는다
MARKS = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?|\b[A-Za-z]{1,3}-?\d{1,4}\b|\d+(?:\.\d+)?")
SENT = re.compile(r"(?<=[.!?。다요])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s for s in (x.strip() for x in SENT.split(text or "")) if s]


@torch.no_grad()
def surprisal(model: Any, tok: Any, text: str, prefix: str = "", max_tokens: int = 2048) -> tuple[list[int], list[float]]:
    """text 의 토큰과 토큰마다 -log p(앞 문맥 + prefix 조건). 첫 토큰은 앞 문맥이 없어 놀람을 크게 둔다(지우지 않게)."""
    pre = tok(prefix, add_special_tokens=False)["input_ids"] if prefix else []
    ids = tok(text, add_special_tokens=False)["input_ids"][:max_tokens]
    if not ids:
        return [], []
    x = torch.tensor([pre + ids], device=model.device)
    logp = torch.log_softmax(model(x).logits[0].float(), -1)
    out = []
    for i, t in enumerate(ids):
        pos = len(pre) + i
        out.append(99.0 if pos == 0 else float(-logp[pos - 1, t]))
    return ids, out


def _offsets(tok: Any, text: str, ids: list[int]) -> list[tuple[int, int]]:
    """토큰마다 원문 글자 범위. 빠른 토크나이저는 offset_mapping, 없으면 한 토큰씩 풀어 길이를 누적한다(바이트 단위 토큰이 글자를
    가르면 조금 어긋날 수 있다 — 그래도 보호 범위가 넓어지는 쪽이라, 지킬 것을 지우는 것보다 낫다)."""
    try:
        om = tok(text, add_special_tokens=False, return_offsets_mapping=True).get("offset_mapping")
    except TypeError:
        om = None
    if om and len(om) >= len(ids):
        return [tuple(x) for x in om[: len(ids)]]
    out, pos = [], 0
    for i in ids:
        n = len(tok.decode([i]))
        out.append((pos, pos + max(1, n)))
        pos += n
    return out


def _protected(tok: Any, text: str, ids: list[int]) -> list[bool]:
    """보호 표시에 걸치는 토큰. 토큰 하나씩 보면 'E4' 가 'E' · '4' 로 나뉠 때 'E' 를 지워 코드가 깨졌다 — 원문에서 표시의 글자 범위를
    먼저 찾고, 그 범위에 조금이라도 걸치는 토큰을 모두 지킨다."""
    spans = [m.span() for m in MARKS.finditer(text)]
    if not spans:
        return [False] * len(ids)
    return [any(a < e and s < b for s, e in spans) for a, b in _offsets(tok, text, ids)]


def token_compress(model: Any, tok: Any, text: str, ratio: float, prefix: str = "") -> dict[str, Any]:
    """남길 비율 ratio(0~1) 만큼 놀람이 높은 토큰 + 보호 토큰을 남긴다."""
    ids, s = surprisal(model, tok, text, prefix)
    if not ids:
        return {"text": "", "kept": 0, "total": 0}
    prot = _protected(tok, text, ids)
    budget = max(sum(prot), int(round(len(ids) * ratio)))
    order = sorted(range(len(ids)), key=lambda i: (not prot[i], -s[i]))  # 보호 토큰 먼저, 그다음 놀람이 높은 순
    keep = sorted(order[:budget])
    return {"text": tok.decode([ids[i] for i in keep]).strip(), "kept": len(keep), "total": len(ids), "protected": sum(prot)}


def query_compress(model: Any, tok: Any, text: str, question: str, ratio: float, sent_mult: float = 2.0) -> dict[str, Any]:
    """문장 단계(대조 점수로 고름, 목표의 sent_mult 배까지 남김) → 토큰 단계(질문 조건으로 목표 비율까지)."""
    ss = sentences(text)
    if not ss:
        return {"text": "", "kept": 0, "total": 0, "sentences": []}
    scored = []
    for sent in ss:
        _, a = surprisal(model, tok, sent)
        _, b = surprisal(model, tok, sent, prefix=f"질문: {question}\n근거: ")
        a, b = [x for x in a if x < 99] or [0.0], [x for x in b if x < 99] or [0.0]
        scored.append({"text": sent, "score": round(sum(a) / len(a) - sum(b) / len(b), 4), "chars": len(sent)})
    total_chars = sum(x["chars"] for x in scored)
    target = total_chars * min(1.0, ratio * sent_mult)
    keep_s, n = [], 0
    for x in sorted(scored, key=lambda x: -x["score"]):
        if n >= target and keep_s:
            break
        keep_s.append(x)
        n += x["chars"]
    kept_text = " ".join(x["text"] for x in scored if x in keep_s)  # 원래 순서로
    inner = min(1.0, ratio * total_chars / max(1, n))
    tc = token_compress(model, tok, kept_text, inner, prefix=f"질문: {question}\n근거: ")
    total = len(tok(text, add_special_tokens=False)["input_ids"])
    return {"text": tc["text"], "kept": tc["kept"], "total": total, "sentences": [{**x, "kept": x in keep_s} for x in scored]}


def lexical_compress(text: str, question: str, ratio: float) -> dict[str, Any]:
    qg = evaluation.grams(question)
    ss = sentences(text)
    ranked = sorted(ss, key=lambda s: -len(qg & evaluation.grams(s)) / max(1, len(evaluation.grams(s))) ** 0.5)
    target, keep, n = len(text) * ratio, [], 0
    for s in ranked:
        if n >= target and keep:
            break
        keep.append(s)
        n += len(s)
    return {"text": " ".join(s for s in ss if s in keep), "kept": n, "total": len(text)}


def random_compress(tok: Any, text: str, ratio: float, seed: int = 7) -> dict[str, Any]:
    ids = tok(text, add_special_tokens=False)["input_ids"]
    rnd = random.Random(seed)
    keep = sorted(rnd.sample(range(len(ids)), int(round(len(ids) * ratio)))) if ids else []
    return {"text": tok.decode([ids[i] for i in keep]).strip(), "kept": len(keep), "total": len(ids)}


def preserved(original: str, compressed: str) -> float | None:
    """원문 근거의 숫자 · 조문 번호 · 코드가 압축 뒤에도 남은 비율 — 하나만 빠져도 답이 틀린다."""
    marks = set(MARKS.findall(original or ""))
    if not marks:
        return None
    c = (compressed or "").replace(" ", "")
    return round(sum(1 for m in marks if m.replace(" ", "") in c) / len(marks), 4)
