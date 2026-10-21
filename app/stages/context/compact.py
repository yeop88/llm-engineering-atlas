"""CX3 도구 결과 · 기록 압축 · CX5 외부 메모리(노트).

긴 작업을 흉내 낸 기록: 에이전트가 여러 하위 질문을 검색한 도구 결과가 쌓이고, 마지막에 처음 단계에서 본 사실을 묻는다. 정답 근거는
기록의 앞쪽(앞에서 gold_at 번째 단계)에 있다 — 압축 방법이 오래된 결과를 어떻게 다루는지가 그대로 정답률에 나타나게.

방법:
- keep_all: 그대로(한도를 넘으면 뒤에서부터 잘림 — build_context 규칙)
- drop_old: 마지막 keep 단계의 결과만 남기고 나머지는 지움(도구 결과 지우기)
- summarize: 오래된 단계는 LLM 이 2문장으로 요약(요약 호출 비용도 함께)
- notes: 오래된 단계는 노트(그 단계 질문과 가장 겹치는 문장 2개, 규칙 — LLM 없음)만 남김 — 외부 메모리(CX5)의 쓰기 규칙과 같다
채점은 같은 질문 · 같은 evaluate_one. 맥락 글자 수 · 시간을 함께 본다.
"""

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import answer, evaluation

STRATEGIES = ("keep_all", "drop_old", "summarize", "notes")
LABEL = {"keep_all": "그대로", "drop_old": "오래된 결과 지움", "summarize": "LLM 요약", "notes": "노트만"}
SUMMARY = "도구 결과를 나중에 다시 쓸 수 있게 사실 위주 2문장으로 줄입니다. 숫자 · 조항 · 이름은 그대로 둡니다."


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。다요])\s+|\n+", text or "") if len(s.strip()) >= 8]


def note_of(query: str, text: str, k: int = 2) -> str:
    """단계 질문과 글자 3-gram 이 가장 겹치는 문장 k 개 — 노트에 적을 '이 단계에서 알게 된 것'."""
    qg = evaluation.grams(query)
    ss = sentences(text)
    ss.sort(key=lambda s: -len(qg & evaluation.grams(s)) / (len(evaluation.grams(s)) or 1) ** 0.5)
    return " ".join(ss[:k])


def transcript(
    item: dict[str, Any], gold_results: list[dict[str, Any]], distract: list[tuple[str, list[dict[str, Any]]]], gold_at: int
) -> list[dict[str, Any]]:
    """단계 = {query, results}. 정답 단계(질문 그대로의 검색 결과)를 앞에서 gold_at 번째에 넣는다."""
    steps = [{"query": q, "results": rs} for q, rs in distract]
    steps.insert(min(gold_at, len(steps)), {"query": item["query"], "results": gold_results, "gold": True})
    return steps


def compact(steps: list[dict[str, Any]], how: str, keep: int, cfg: llm.LLMConfig | None) -> tuple[list[dict[str, Any]], float]:
    """→ (맥락에 넣을 근거 목록, 압축에 쓴 LLM 시간)."""
    spent = 0.0
    out: list[dict[str, Any]] = []
    old, recent = steps[:-keep] if keep else steps, steps[-keep:] if keep else []
    if how == "keep_all":
        return [r for s in steps for r in s["results"]], 0.0
    for s in old:
        text = "\n".join(r.get("text") or "" for r in s["results"])
        if how == "drop_old":
            continue
        if how == "summarize" and cfg is not None:
            t = time.perf_counter()
            try:
                summ = llm.chat(cfg, SUMMARY, f"단계 질문: {s['query']}\n\n도구 결과:\n{text[:3000]}", 160, 0.0)["text"]
            except llm.LLMError:
                summ = note_of(s["query"], text)
            spent += time.perf_counter() - t
        else:
            summ = note_of(s["query"], text)
        out.append(
            {
                "document_id": (s["results"][0] if s["results"] else {}).get("document_id"),
                "filename": f"(이전 단계 요약: {s['query'][:30]})",
                "text": summ,
            }
        )
    out += [r for s in recent for r in s["results"]]
    return out, spent


def run(cfg, items, gold_ctx, distract_of, strategies, keep, gold_at, max_chars, max_tokens, progress=lambda f, m: None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    total = max(1, len(strategies) * len(items))
    for si, how in enumerate(strategies):
        rows, chars, spent = [], [], 0.0
        for i, (it, gctx) in enumerate(zip(items, gold_ctx, strict=True)):
            progress((si * len(items) + i) / total, f"{LABEL[how]} {i + 1}/{len(items)}")
            steps = transcript(it, gctx, distract_of(it), gold_at)
            ctx, s = compact(steps, how, keep, cfg)
            spent += s
            chars.append(sum(len(r.get("text") or "") for r in ctx))
            rows.append(answer.evaluate_one(cfg, it, ctx, max_chars, max_tokens, no_cache=True))
        q = [r["quality"] for r in rows]
        out[how] = {"label": LABEL[how], "n": len(rows), "quality": round(sum(q) / len(q), 4) if q else None,
                    "context_chars": round(sum(chars) / len(chars)) if chars else None, "seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2) if rows else None,
                    "compact_seconds": round(spent / len(rows), 2) if rows else None}  # fmt: skip
    return out


# ── CX5 외부 메모리(노트 저장소) ─────────────────────────────────────────────
def _notes_path(session: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session):
        raise ValueError("세션 이름은 영문 · 숫자 · _ · - 만")
    d = get_settings().data_dir / "context" / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session}.json"


def notes(session: str) -> list[dict[str, Any]]:
    p = _notes_path(session)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def write_note(session: str, text: str, tags: list[str] | None = None, source: str = "") -> dict[str, Any]:
    """노트 한 줄 — 출처 · 시각을 함께 남긴다(나중에 낡은 노트를 가려내고 맥락 오염을 막으려고, CX6)."""
    ns = notes(session)
    n = {
        "id": len(ns) + 1,
        "text": text.strip()[:1000],
        "tags": tags or [],
        "source": source,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    ns.append(n)
    _notes_path(session).write_text(json.dumps(ns, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def read_notes(session: str, query: str = "", k: int = 5) -> list[dict[str, Any]]:
    """질문과 겹치는 노트 k 개(질문이 없으면 최근 k 개) — 노트를 모두 맥락에 넣으면 노트를 둔 의미가 없다."""
    ns = notes(session)
    if not query:
        return ns[-k:]
    qg = evaluation.grams(query)
    return sorted(ns, key=lambda n: -len(qg & evaluation.grams(n["text"])))[:k]


def delete_notes(session: str) -> None:
    _notes_path(session).unlink(missing_ok=True)
