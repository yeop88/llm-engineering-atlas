"""다단계 RAG 에이전트 (ReAct 형식): 생각 → 도구 호출 → 관찰을 반복하다 근거를 인용해 답한다.

설계 이유
- 도구 호출 형식은 JSON 한 객체({"thought", "action", "input"})로 받는다. 작은 로컬 LLM 은 제공자별 함수 호출(tool calling)
  지원이 고르지 않고, JSON 은 이미 평가 질문 생성 등에서 안정적으로 쓰고 있다. 형식이 틀리면 한 번 고쳐 달라고 하고,
  또 틀리면 지금까지 모은 근거로 답하게 한다(무한 반복 방지).
- 도구는 셋으로 작게 둔다: search(질의를 바꿔 다시 검색), read(찾은 지문의 앞뒤 청크 읽기 — 표 · 조문이 청크 경계에서
  잘린 경우), calc(금액 · 날짜 계산). 도구가 많을수록 작은 모델이 잘못 고른다.
- 찾은 지문은 모두 [S번호]로 모아, 마지막 답은 그 번호를 인용하게 한다. 그래서 RAG 답변과 같은 문장별 근거 검증을 그대로 쓴다.
- 법률 자료가 있으면 lookup(조문 · 사건번호로 바로 찾기)을 더한다. 번호로 묻는 질문은 검색보다 정확하고, 답변의 번호가
  컬렉션에 실제로 있는지(지어낸 번호인지) 인용 검사도 같은 함수로 한다(rag/legal.py).
- 첫 검색 결과를 받아 시작할 수 있다(연결 실행에서 이미 검색했으면 같은 검색을 다시 하지 않게).
- 단계 수 상한(max_steps): 에이전트의 비용은 단계 수에 비례하므로 상한과 단계별 시간을 기록해 RAG 와 비용을 비교한다.
"""

import ast
import operator
import time
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.db import Chunk
from app.stages.rag import answer, legal

SYSTEM = """당신은 문서 검색 도구를 쓰는 조사 도우미입니다. 질문에 답하려면 필요한 근거를 도구로 모은 뒤 답하세요.
도구:
- search: 문서 검색. input = 검색할 질의 (원래 질문과 다른 표현 · 하위 질문으로)
- read: 찾은 지문의 앞뒤 내용 읽기. input = 근거 번호 (예: "S2")
- calc: 계산. input = 산술식 (예: "20000000 * 0.1")
{lookup}- finish: 답하기. input = 최종 답변. 문장마다 근거 번호를 [S1] 처럼 인용하고, 근거에 없으면 "근거에서 찾을 수 없습니다"라고 답하세요.
매번 {{"thought": "지금 판단", "action": "{actions}", "input": "..."}} 형식의 JSON 하나만 출력하세요."""
LOOKUP_TOOL = '- lookup: 법령 조문 · 판례를 번호로 바로 찾기. input = "근로기준법 제23조" 또는 사건번호 "2019다12345"\n'


def system_prompt(with_lookup: bool) -> str:
    return SYSTEM.format(
        lookup=LOOKUP_TOOL if with_lookup else "", actions="search|read|calc|" + ("lookup|" if with_lookup else "") + "finish"
    )


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}  # fmt: skip


def calc(expr: str) -> str:
    """산술식만 계산(eval 을 쓰지 않음 — LLM 이 만든 문자열을 실행하면 임의 코드가 돌 수 있다)."""

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, int | float):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100:
                raise ValueError("지수가 너무 큽니다")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("숫자와 + - * / ** % // 괄호만 쓸 수 있습니다")

    try:
        v = ev(ast.parse(expr.replace(",", ""), mode="eval").body)
        return str(int(v)) if float(v).is_integer() else f"{v:.6g}"
    except (ValueError, SyntaxError, ZeroDivisionError) as exc:
        return f"계산 오류: {exc}"


class Sources:
    """에이전트가 본 지문 모음. 같은 청크는 한 번만 번호를 붙인다(같은 근거를 다른 번호로 인용하지 않게)."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.by_chunk: dict[int, int] = {}

    def add(self, r: dict[str, Any]) -> int:
        cid = r.get("chunk_id")
        if cid in self.by_chunk:
            return self.by_chunk[cid]
        self.items.append(r)
        n = len(self.items)
        if cid is not None:
            self.by_chunk[cid] = n
        return n

    def show(self, results: list[dict[str, Any]], max_chars: int) -> str:
        lines = []
        for r in results:
            n = self.add(r)
            where = r.get("filename", "") + (f" p.{r['page']}" if r.get("page") else "")
            lines.append(f"[S{n}] ({where}) {' '.join(r['text'].split())[:max_chars]}")
        return "\n".join(lines) or "결과 없음"


def read_around(db: Session, chunk_id: int, width: int = 1) -> list[dict[str, Any]]:
    """청크의 앞뒤 청크(같은 문서 · 같은 청크 세트). 표 · 조문이 청크 경계에서 잘렸을 때 이어 읽으려고."""
    c = db.get(Chunk, chunk_id)
    if c is None:
        return []
    rows = db.scalars(
        select(Chunk).where(Chunk.chunk_set_id == c.chunk_set_id, Chunk.document_id == c.document_id, Chunk.idx.between(c.idx - width, c.idx + width))
        .order_by(Chunk.idx)
    ).all()  # fmt: skip
    return [{"chunk_id": x.id, "document_id": x.document_id, "page": x.page, "text": x.text, "filename": ""} for x in rows if x.id != c.id]


def run(cfg: llm.LLMConfig, question: str, search_fn: Callable[[str], list[dict[str, Any]]], db: Session | None = None,
        first_results: list[dict[str, Any]] | None = None, max_steps: int = 5, top_k: int = 4, max_chars: int = 500,
        max_tokens: int = 600, no_cache: bool = False,
        lookup_fn: Callable[[str], list[dict[str, Any]]] | None = None) -> Iterator[dict[str, Any]]:  # fmt: skip
    """lookup_fn 이 있으면 번호 조회 도구와 답변의 조문 · 판례 번호 검사를 켠다. 단계마다 {"type": "step", ...} 를 내보내고, 마지막에 {"type": "final", answer, sources, verify, steps, seconds}."""
    started = time.perf_counter()
    src = Sources()
    history: list[str] = []
    steps: list[dict[str, Any]] = []
    if first_results is not None:
        obs = src.show(first_results[:top_k], max_chars)
        history.append(f"[관찰 0 · 첫 검색: {question}]\n{obs}")
        steps.append({"n": 0, "action": "search", "input": question, "observation": obs[:400], "ms": 0.0, "given": True})
    final_text, bad_json = None, 0
    for n in range(1, max_steps + 1):
        t = time.perf_counter()
        user = (
            f"질문: {question}\n\n"
            + ("\n\n".join(history) if history else "(아직 모은 근거 없음)")
            + f"\n\n남은 단계: {max_steps - n + 1}. 다음 행동 JSON:"
        )
        try:
            obj, _ = llm.chat_json(
                cfg, system_prompt(lookup_fn is not None), user, max_tokens=max_tokens, temperature=0.1, no_cache=no_cache
            )
        except llm.LLMError as exc:
            bad_json += 1
            history.append(f"[오류] 형식이 잘못됐습니다({str(exc)[:80]}). JSON 하나만 출력하세요.")
            steps.append(
                {"n": n, "action": "error", "input": "", "observation": str(exc)[:200], "ms": round((time.perf_counter() - t) * 1000, 1)}
            )
            yield {"type": "step"} | steps[-1]
            if bad_json >= 2:
                break
            continue
        action = str(obj.get("action", "")).strip().lower() if isinstance(obj, dict) else ""
        arg = str(obj.get("input", "")).strip() if isinstance(obj, dict) else ""
        thought = str(obj.get("thought", ""))[:300] if isinstance(obj, dict) else ""
        if action == "finish":
            final_text = arg
            obs = ""
        elif action == "search" and arg:
            obs = src.show(search_fn(arg)[:top_k], max_chars)
        elif action == "read" and arg:
            k = int("".join(ch for ch in arg if ch.isdigit()) or 0)
            if db is not None and 1 <= k <= len(src.items) and src.items[k - 1].get("chunk_id"):
                around = read_around(db, src.items[k - 1]["chunk_id"])
                for a in around:
                    a["filename"] = src.items[k - 1].get("filename", "")
                obs = src.show(around, max_chars * 2) if around else "앞뒤 내용이 없습니다"
            else:
                obs = f"S{k} 를 찾을 수 없습니다"
        elif action == "calc":
            obs = calc(arg)
        elif action == "lookup" and arg and lookup_fn is not None:
            found = lookup_fn(arg)
            obs = src.show(found[:top_k], max_chars * 2) if found else f"'{arg}' 에 해당하는 조문 · 판례가 자료에 없습니다"
        else:
            obs = "알 수 없는 행동입니다. search · read · calc · " + ("lookup · " if lookup_fn else "") + "finish 중 하나를 쓰세요."
        ms = round((time.perf_counter() - t) * 1000, 1)
        steps.append({"n": n, "thought": thought, "action": action, "input": arg[:300], "observation": obs[:400], "ms": ms})
        yield {"type": "step"} | steps[-1]
        if final_text is not None:
            break
        history.append(f"[생각 {n}] {thought}\n[행동 {n}] {action}: {arg}\n[관찰 {n}]\n{obs}")
    if final_text is None:
        # 단계를 다 쓰거나 형식 오류가 반복되면, 모은 근거로 RAG 처럼 한 번에 답하게 한다(빈손으로 끝나지 않게)
        context, _ = answer.build_context(src.items, 8000)
        res = llm.chat(cfg, answer.SYSTEM, answer.user_prompt(question, context), max_tokens=max_tokens, temperature=0.1, no_cache=no_cache)
        final_text = res["text"]
        steps.append(
            {
                "n": len(steps),
                "action": "forced_finish",
                "input": "",
                "observation": "단계 상한 · 형식 오류로 모은 근거로 답함",
                "ms": round(res["seconds"] * 1000, 1),
            }
        )
    # 인용 형식을 RAG 답변과 같은 [n] 으로 통일([S3] → [3]) — 화면 · 검증 · 평가가 같은 번호 체계를 쓰게
    final_text = final_text.replace("[S", "[")
    check = answer.verify(final_text, src.items)
    cites = legal.check_citations(final_text, src.items, lookup_fn) if lookup_fn is not None else None
    yield {"type": "final", "answer": final_text, "sources": src.items, "verify": check, "citations": cites, "steps": steps,
           "n_steps": sum(1 for s in steps if not s.get("given")), "seconds": round(time.perf_counter() - started, 2)}  # fmt: skip


def run_to_end(*args: Any, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ev in run(*args, **kw):
        if ev["type"] == "final":
            out = ev
    return out
