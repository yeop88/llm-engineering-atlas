"""CD2 작업 계획 · CD3 패치 · CD4 테스트 주도 고치기 — 한 걸음에 도구 하나(ReAct, JSON).

흐름: 이슈(실패한 테스트 출력) → 계획(바꿀 파일 · 함수 후보 · 확인할 테스트) → 걸음마다 {search · read · replace · test · done} 중 하나 →
replace 뒤에는 바로 그 테스트를 돌려 결과를 다음 걸음에 준다(실패 출력이 가장 정확한 피드백). 테스트 파일은 고치지 못하게 막는다 —
테스트를 고쳐 통과시키는 것은 해결이 아니다. 걸음 상한 · 토큰을 함께 센다.
"""

import json
import time
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.coding import workspace as wsp
from app.stages.coding.index import CodeIndex, test_calls

PLAN_SYSTEM = (
    "코드 수정 계획을 세웁니다. 실패한 테스트 출력과 코드 검색 결과로, 고칠 파일 · 함수 후보와 이유를 짧게 적습니다. "
    '반드시 JSON 만: {"candidates": [{"file": 경로, "function": 이름, "why": 이유}], "test": 확인할 테스트 경로}'
)
STEP_SYSTEM = (
    "당신은 저장소의 버그를 고치는 개발자입니다. 한 번에 도구 하나를 JSON 으로만 고릅니다.\n"
    '- {"tool": "search", "query": 찾을 말}\n- {"tool": "read", "file": 경로, "start": 줄, "end": 줄}\n'
    '- {"tool": "replace", "file": 경로, "old": 파일에 정확히 한 번 있는 글(앞뒤 줄 포함), "new": 바꿀 글}\n'
    '- {"tool": "test"}\n- {"tool": "done", "summary": 무엇을 고쳤는지}\n'
    "tests/ 의 파일은 고치지 않습니다. 고친 뒤에는 테스트 결과를 보고 판단합니다. 생각(thought) 칸에 한 줄 이유를 함께 씁니다."
)


def plan(cfg: llm.LLMConfig, issue: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    ctx = "\n".join(f"- {h['file']}:{h['start']} {h['name']}" for h in hits[:8])
    try:
        data, _ = llm.chat_json(cfg, PLAN_SYSTEM, f"[이슈]\n{issue[-2000:]}\n\n[코드 검색 상위]\n{ctx}", max_tokens=300, temperature=0.0)
        return data if isinstance(data, dict) else {}
    except llm.LLMError, ValueError:
        return {}


def run(cfg: llm.LLMConfig, ws: Path, task: dict[str, Any], max_steps: int = 12, on_step=lambda s: None) -> dict[str, Any]:
    t0 = time.perf_counter()
    idx = CodeIndex(ws)
    seeds = test_calls((ws / task["test"]).read_text(encoding="utf-8"))
    hits = idx.search(task["issue"], 8, "graph", seeds)
    p = plan(cfg, task["issue"], hits)
    on_step({"n": 0, "tool": "plan", "plan": p, "hits": hits[:5]})
    history = [f"[이슈]\n{task['issue'][-2500:]}", f"[계획]\n{json.dumps(p, ensure_ascii=False)}",
               "[코드 검색 상위]\n" + "\n".join(f"- {h['file']}:{h['start']}-{h['end']} {h['name']}" for h in hits[:6])]  # fmt: skip
    steps, tokens, passed, edits = [], 0, False, 0
    for n in range(1, max_steps + 1):
        try:
            r = llm.chat(cfg, STEP_SYSTEM, "\n\n".join(history[-14:]), 700, 0.0, json_mode=True)
        except llm.LLMError as exc:
            steps.append({"n": n, "tool": "error", "observation": str(exc)})
            break
        tokens += r["usage"].get("output_tokens") or 0
        try:
            act = json.loads(r["text"][r["text"].find("{") : r["text"].rfind("}") + 1])
        except ValueError, json.JSONDecodeError:
            act = {"tool": "invalid"}
        tool = act.get("tool")
        obs: Any
        if tool == "search":
            obs = "\n".join(
                f"{h['file']}:{h['start']}-{h['end']} {h['name']} ({h['score']})"
                for h in idx.search(str(act.get("query", "")), 6, "graph", seeds)
            )
        elif tool == "read":
            try:
                obs = wsp.read(ws, str(act.get("file", "")), int(act.get("start") or 1), int(act["end"]) if act.get("end") else None)
            except (ValueError, OSError) as exc:
                obs = f"읽기 실패: {exc}"
        elif tool == "replace":
            f = str(act.get("file", ""))
            if f.startswith("tests/"):
                obs = "tests/ 는 고칠 수 없습니다 — app/ 의 코드를 고치세요"
            else:
                try:
                    res = wsp.replace(ws, f, str(act.get("old", "")), str(act.get("new", "")))
                except (ValueError, OSError) as exc:
                    res = {"ok": False, "error": str(exc)}
                if res["ok"]:
                    edits += 1
                    t = wsp.run_tests(ws, [task["test"]])
                    passed = t["passed"]
                    obs = f"바꿈. 테스트 {'통과' if passed else '실패'}:\n{t['output'][-1200:]}"
                else:
                    obs = res["error"]
        elif tool == "test":
            t = wsp.run_tests(ws, [task["test"]])
            passed = t["passed"]
            obs = f"테스트 {'통과' if passed else '실패'}:\n{t['output'][-1200:]}"
        elif tool == "done":
            steps.append({"n": n, "tool": "done", "thought": act.get("thought"), "observation": act.get("summary", "")})
            on_step(steps[-1])
            break
        else:
            obs = "도구 JSON 형식이 아닙니다 — search · read · replace · test · done 중 하나"
        step = {
            "n": n,
            "tool": tool,
            "thought": act.get("thought"),
            "input": {k: v for k, v in act.items() if k not in ("tool", "thought")},
            "observation": str(obs)[-1500:],
        }
        steps.append(step)
        on_step(step)
        history.append(f"[{n}번째 도구 {json.dumps(step['input'], ensure_ascii=False)[:600]}]\n{step['observation']}")
    final = wsp.run_tests(ws, [task["test"]])
    d = wsp.diff(ws)
    touched_tests = "+++ b/tests/" in d
    return {"task": task["id"], "resolved": final["passed"] and not touched_tests, "passed": final["passed"], "touched_tests": touched_tests, "steps": steps,
            "n_steps": len(steps), "edits": edits, "tokens": tokens, "diff": d, "diff_lines": sum(1 for x in d.splitlines() if x[:1] in "+-" and x[:3] not in ("+++", "---")),
            "found_file": task["file"] in d, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
