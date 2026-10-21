"""MA5 분석 · 코딩 에이전트: 근거 속 수치를 파이썬 코드로 계산 · 검증하고 차트 데이터를 만든다.

LLM 에게 암산을 시키지 않는 이유: 작은 모델은 합계 · 비율 · 날짜 계산을 자주 틀리고, 틀린 숫자가 그럴듯한 문장에 섞이면 검증으로도
잡기 어렵다. 그래서 LLM 은 '계산하는 코드'만 쓰고, 계산은 샌드박스(상호운용 맵 IO2 — 네트워크 없는 컨테이너)가 한다.
코드는 근거 글 자체를 입력(SOURCES)으로 받고 결과를 JSON 한 줄로 출력해야 한다 — 숫자를 코드에 옮겨 적다 틀리는 일을 줄이려고.
"""

import json
import re
from typing import Any

from app.core import llm
from app.stages.interop import sandbox

NEEDS = re.compile(r"합계|총|평균|비율|퍼센트|%|계산|몇\s*(배|일|원|퍼)|차이|증가|감소|비교|추이|표|차트|그래프|최대|최소|순위|얼마")

CODE_SYSTEM = (
    "당신은 분석 코드를 쓰는 도구입니다. 입력 변수 SOURCES(근거 글 목록, list[str])에서 필요한 수치를 정규식 등으로 직접 뽑아 계산하는 파이썬 코드만 씁니다. "
    "숫자를 코드에 직접 적지 말고 SOURCES 에서 찾습니다. 표준 라이브러리만 씁니다. 마지막에 print(json.dumps({...}, ensure_ascii=False)) 한 번으로 "
    '{"result": 답에 쓸 값 · 설명, "chart": {"type": "bar|line", "labels": [...], "values": [...], "title": "..."} 또는 null} 을 출력합니다. '
    "코드 블록 하나만 출력합니다."
)


def needed(question: str) -> bool:
    return bool(NEEDS.search(question))


def _code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def run(question: str, sources: list[dict[str, Any]], lcfg: llm.LLMConfig, retries: int = 1) -> dict[str, Any]:
    texts = [(s.get("text") or "")[:2000] for s in sources[:6]]
    prelude = "import json, re, math, statistics\nSOURCES = " + json.dumps(texts, ensure_ascii=False) + "\n"
    feedback, attempts = "", []
    for _ in range(retries + 1):
        r = llm.chat(lcfg, CODE_SYSTEM, f"질문: {question}\n근거 글 {len(texts)}개가 SOURCES 에 들어 있습니다." + (f"\n\n앞선 시도 오류:\n{feedback}" if feedback else ""),
                     max_tokens=900, temperature=0.0)  # fmt: skip
        code = _code(r["text"])
        out = sandbox.run_python(prelude + code)
        line = next((ln for ln in reversed(out["stdout"].strip().splitlines()) if ln.strip().startswith("{")), "")
        try:
            parsed = json.loads(line) if line else None
        except ValueError:
            parsed = None
        attempts.append(
            {
                "code": code,
                "stdout": out["stdout"][-2000:],
                "stderr": out["stderr"][-1500:],
                "exit_code": out["exit_code"],
                "isolation": out["isolation"],
            }
        )
        if parsed is not None and out["exit_code"] == 0:
            chart = parsed.get("chart") if isinstance(parsed, dict) else None
            ok_chart = (
                isinstance(chart, dict)
                and isinstance(chart.get("labels"), list)
                and isinstance(chart.get("values"), list)
                and len(chart["labels"]) == len(chart["values"])
            )
            return {
                "ok": True,
                "result": parsed.get("result") if isinstance(parsed, dict) else parsed,
                "chart": chart if ok_chart else None,
                "attempts": attempts,
            }
        feedback = (out["stderr"] or "JSON 한 줄 출력이 없습니다")[-800:]
    return {"ok": False, "result": None, "chart": None, "attempts": attempts}
