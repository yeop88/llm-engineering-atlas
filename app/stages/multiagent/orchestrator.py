"""MA3 오케스트레이터: 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화.

라우터(6)는 '어느 한 경로로 보낼까'를 정하지만, 오케스트레이터는 '어떤 전문가가 어떤 순서로'를 정한다. 계획은 규칙이 먼저다:
검색은 늘, 분석은 계산 · 비교 · 표를 묻는 질문에만(분석 에이전트의 needed), 작성 다음엔 늘 검증. LLM 계획은 쓰지 않는다 —
에이전트가 다섯뿐이고 순서가 거의 정해져 있어, LLM 에게 맡기면 비용만 들고 '검증 빼기' 같은 실수가 생긴다(맵 원칙 · 에이전트 실측).
에이전트끼리는 칠판(board)에 결과를 쌓아 주고받고, 모든 주고받음을 시간과 함께 남겨 화면이 흐름을 그대로 보인다.
"""

import time
from collections.abc import Callable
from typing import Any

from app.core import llm
from app.stages.multiagent import analysis, critic, output, retrieval, writer


def plan(question: str, analyze: str = "auto") -> list[dict[str, Any]]:
    tasks = [{"agent": "retrieval", "goal": "근거 찾기(부족하면 질의를 고쳐 다시)"}]
    if analyze == "on" or (analyze == "auto" and analysis.needed(question)):
        tasks.append({"agent": "analysis", "goal": "근거 속 수치를 코드로 계산 · 차트 데이터"})
    tasks += [{"agent": "writer", "goal": "근거 · 분석 결과로 답 쓰기(난이도별 모델)"}, {"agent": "critic", "goal": "근거 일치 · 정책 · 숫자 검사 → 통과 · 수정 · 반려"},
              {"agent": "output", "goal": "글 + 차트 + 그림 + 음성"}]  # fmt: skip
    return tasks


def run(question: str, search: retrieval.SearchFn, lcfg: llm.LLMConfig, *, analyze: str = "auto", rounds: int = 3, revisions: int = 2,
        vision: bool = True, tts: bool = False, domain: str = "general", on_event: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:  # fmt: skip
    t0 = time.perf_counter()
    board: dict[str, Any] = {"question": question}
    events: list[dict[str, Any]] = []
    tokens = {"input_tokens": 0, "output_tokens": 0}

    def emit(agent: str, kind: str, **kw: Any) -> None:
        e = {"t": round(time.perf_counter() - t0, 2), "agent": agent, "kind": kind} | kw
        events.append(e)
        if on_event:
            on_event(e)

    def add_usage(u: dict[str, Any] | None) -> None:
        for k in tokens:
            tokens[k] += int((u or {}).get(k) or 0)

    tasks = plan(question, analyze)
    emit("orchestrator", "plan", tasks=tasks)
    # 검색 전문가
    r = retrieval.self_rag(question, search, lcfg, rounds=rounds)
    sources = retrieval.vision_rerank(question, r["sources"], lcfg) if vision else r["sources"]
    board["sources"] = sources
    emit(
        "retrieval",
        "result",
        rounds=r["rounds"],
        n=len(sources),
        enough=r["enough"],
        vision=[s.get("vision_score") for s in sources if "vision_score" in s],
    )
    # 분석 전문가
    an = None
    if any(t["agent"] == "analysis" for t in tasks) and sources:
        try:
            an = analysis.run(question, sources, lcfg)
        except llm.LLMError as exc:
            an = {"ok": False, "error": str(exc)[:300], "attempts": []}
        board["analysis"] = an
        emit("analysis", "result", ok=an.get("ok"), result=an.get("result"), chart=an.get("chart"), attempts=an.get("attempts"))
    # 작성 ↔ 검증 루프
    draft = writer.write(question, sources, an, lcfg)
    add_usage(draft.get("usage"))
    emit("writer", "draft", text=draft["text"], level=draft["level"], why=draft["why"], model=draft["model"])
    verdict = critic.review(question, draft["text"], draft["used"], an, domain)
    emit("critic", verdict["decision"], issues=verdict["issues"], supported=verdict["verify"].get("supported_ratio"))
    n = 0
    while verdict["decision"] == "revise" and n < revisions:
        n += 1
        draft = writer.write(question, sources, an, lcfg, feedback="\n".join(verdict["issues"]), previous=draft["text"])
        add_usage(draft.get("usage"))
        emit("writer", "revision", n=n, text=draft["text"], model=draft["model"])
        verdict = critic.review(question, draft["text"], draft["used"], an, domain)
        emit("critic", verdict["decision"], issues=verdict["issues"], supported=verdict["verify"].get("supported_ratio"), n=n)
    if verdict["decision"] == "reject":
        final = "규정에 맞지 않아 답하지 않았습니다. 상담원에게 연결합니다."
    elif verdict["decision"] == "revise":  # 고쳐 쓰기 상한 — 그대로 내보내되 검토 필요 표시
        final = draft["text"] + "\n\n※ 일부 문장의 근거를 확인하지 못했습니다. 사람의 검토가 필요할 수 있습니다."
    else:
        final = draft["text"]
    out = output.compose(final, an, draft["used"], tts)
    emit("output", "result", chart=bool(out["chart"]), images=len(out["images"]), audio=bool(out["audio"] and out["audio"].get("url")))
    return {"question": question, "tasks": tasks, "events": events, "answer": final, "decision": verdict["decision"], "revisions": n,
            "verify": {k: verdict["verify"].get(k) for k in ("supported_ratio", "relevant_ratio", "refused", "invalid_citations")},
            "sources": [{k: s.get(k) for k in ("chunk_id", "document_id", "filename", "heading", "text", "media", "round", "query", "vision_score")} for s in draft["used"]],
            "analysis": an, "output": out, "usage": tokens, "seconds": round(time.perf_counter() - t0, 1), "writer_model": draft["model"], "level": draft["level"]}  # fmt: skip
