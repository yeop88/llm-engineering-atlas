"""RS3 여러 번 풀고 고르기 · RS4 검증기 · 과정 보상.

여러 번 풀기는 저장소의 풀이 N 개로 n = 1 … N 의 곡선을 한 번에 만든다(앞 n 개만 쓰기 — 새로 부르지 않음):
- 다수결(자기 일관성): 정규화한 최종 답의 최빈값, 같으면 먼저 나온 답
- 검증기 고르기(Best-of-n): 검증기 점수가 가장 높은 풀이
- pass@n: n 개 중 하나라도 맞음 — 고르기 방법이 얻을 수 있는 상한

검증기는 정답을 모르는 채로 풀이를 채점한다(정답을 알면 검증기가 필요 없다):
- format: '정답:' 줄이 있나(가장 약한 기준선)
- grounded: 답이 자료 · 도구 결과에 그대로 있나 — 조문 번호 · 제목은 근거 글에, 수는 그래프 집계 결과에(계산은 집계의 합과)
- process: 생각의 각 문장에 나온 조문 번호 · 수가 자료 · 질문에 있거나 그 수들의 합인가(과정 보상의 규칙판 — 단계마다 채점해 평균)
- llm: LLM 판정(생각 없이, 0~1) — 판정 자체가 틀리므로 정확도를 따로 잰다
검증기 정확도는 맞은 풀이 · 틀린 풀이를 얼마나 잘 가르는지(AUROC)와 그 검증기로 골랐을 때의 정답률로 본다.
"""

import json
import re
from collections import Counter
from itertools import combinations
from typing import Any

from app.core import llm
from app.stages.reasoning.solve import norm_final
from app.stages.rlvr import tasks as tk

NUM = re.compile(r"(?<![0-9])\d{1,6}(?![0-9])")


def evidence_text(obs: dict[str, Any]) -> str:
    return (
        "\n".join(d.get("text") or "" for d in obs.get("docs") or []) + "\n" + json.dumps(obs.get("graph_count") or {}, ensure_ascii=False)
    )


def graph_numbers(obs: dict[str, Any]) -> set[int]:
    nums = {int(x) for x in NUM.findall(json.dumps(obs.get("graph_count") or {}))}
    return nums | {a + b for a, b in combinations(sorted(nums), 2)}  # 계산 과제: 두 집계의 합


def v_format(task: dict[str, Any], s: dict[str, Any], obs: dict[str, Any]) -> float:
    return 1.0 if tk.final_of(s["text"]) is not None else 0.0


def v_grounded(task: dict[str, Any], s: dict[str, Any], obs: dict[str, Any]) -> float:
    ans = norm_final(task, tk.final_of(s["text"]))
    if ans is None:
        return 0.0
    if task["kind"] == "number":
        return 1.0 if int(ans) in graph_numbers(obs) else 0.0
    ev = tk._norm_text(evidence_text(obs))
    return 1.0 if tk._norm_text(ans) in ev else 0.0


def v_process(task: dict[str, Any], s: dict[str, Any], obs: dict[str, Any]) -> float:
    """생각(없으면 답 글)의 문장마다: 조문 번호 · 수가 자료 · 질문에서 왔나. 주장이 없는 문장은 세지 않는다."""
    text = s.get("thinking") or s["text"]
    ev = evidence_text(obs) + "\n" + task["q"]
    ev_arts = {m.group(0).replace(" ", "") for m in tk.ARTICLE.finditer(ev)}
    ev_nums = {int(x) for x in NUM.findall(ev)} | graph_numbers(obs)
    scores = []
    for sent in re.split(r"(?<=[.!?。\n])\s*", text):
        arts = {m.group(0).replace(" ", "") for m in tk.ARTICLE.finditer(sent)}
        nums = {int(x) for x in NUM.findall(re.sub(r"제\s*\d+\s*조(의\s*\d+)?", "", sent))}
        claims = len(arts) + len(nums)
        if claims:
            ok = len(arts & ev_arts) + sum(1 for n in nums if n in ev_nums or n <= 3)  # 1 · 2 · 3 같은 순서 수는 주장이 아니다
            scores.append(ok / claims)
    return round(sum(scores) / len(scores), 3) if scores else 0.5


JUDGE = '자료와 도구 결과만 보고, 풀이의 최종 답이 맞으면 높게, 틀렸거나 근거가 없으면 낮게 {"score": 0~1 사이 수} 만 JSON 으로 답합니다.'


def make_llm_verifier(cfg: llm.LLMConfig):
    def v_llm(task: dict[str, Any], s: dict[str, Any], obs: dict[str, Any]) -> float:
        docs = "\n".join(f"- {(d.get('text') or '')[:400]}" for d in obs.get("docs") or [])
        tool = json.dumps(obs.get("graph_count") or {}, ensure_ascii=False)
        try:
            data, _ = llm.chat_json(
                cfg,
                JUDGE,
                f"[자료]\n{docs}\n[도구 결과] {tool}\n\n[질문] {task['q']}\n\n[풀이]\n{s['text'][-800:]}",
                max_tokens=40,
                temperature=0.0,
            )
            return max(0.0, min(1.0, float(data.get("score", 0))))
        except llm.LLMError, ValueError, TypeError, AttributeError:
            return 0.5

    return v_llm


RULES = {"format": v_format, "grounded": v_grounded, "process": v_process}


def auroc(pos: list[float], neg: list[float]) -> float | None:
    """맞은 풀이 점수가 틀린 풀이보다 높을 확률(같으면 반)."""
    if not pos or not neg:
        return None
    win = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(win / (len(pos) * len(neg)), 4)


def majority(task: dict[str, Any], sols: list[dict[str, Any]]) -> dict[str, Any] | None:
    keys = [norm_final(task, s["final"]) for s in sols]
    c = Counter(k for k in keys if k is not None)
    if not c:
        return sols[0] if sols else None
    top = max(c.values())
    winner = next(k for k in keys if k is not None and c[k] == top)
    return sols[keys.index(winner)]


def curves(
    items: list[dict[str, Any]],
    bank: dict[str, list[dict[str, Any]]],
    obs_of,
    verifiers: dict[str, Any],
    n_max: int,
    progress=lambda f, m: None,
) -> dict[str, Any]:
    """→ {"curve": [{"n", "majority", "pass", "best:<검증기>"…}], "verifiers": {이름: {auroc, acc_at_half}}, "by_type"}."""
    tasks = [t for t in items if bank.get(t["id"])]
    scored: dict[str, list[dict[str, float]]] = {}
    for k, t in enumerate(tasks):
        progress(k / max(1, len(tasks)), f"검증기 채점 {t['id']}")
        obs = obs_of(t)
        scored[t["id"]] = [{name: f(t, s, obs) for name, f in verifiers.items()} for s in bank[t["id"]][:n_max]]
    curve = []
    for n in range(1, n_max + 1):
        row: dict[str, Any] = {"n": n}
        mj, ps, best = [], [], {name: [] for name in verifiers}
        for t in tasks:
            sols = bank[t["id"]][:n]
            if len(sols) < n:
                continue
            mj.append(bool(majority(t, sols)["correct"]))
            ps.append(any(s["correct"] for s in sols))
            for name in verifiers:
                sc = [scored[t["id"]][i][name] for i in range(n)]
                best[name].append(bool(sols[max(range(n), key=lambda i: (sc[i], -i))]["correct"]))
        if not mj:
            break
        row |= {"tasks": len(mj), "majority": round(sum(mj) / len(mj), 4), "pass": round(sum(ps) / len(ps), 4)}
        row |= {f"best:{name}": round(sum(v) / len(v), 4) for name, v in best.items()}
        curve.append(row)
    vstats = {}
    for name in verifiers:
        pos = [scored[t["id"]][i][name] for t in tasks for i, s in enumerate(bank[t["id"]][:n_max]) if s["correct"]]
        neg = [scored[t["id"]][i][name] for t in tasks for i, s in enumerate(bank[t["id"]][:n_max]) if not s["correct"]]
        hits = [
            (sc >= 0.5) == bool(s["correct"])
            for t in tasks
            for sc, s in zip((x[name] for x in scored[t["id"]]), bank[t["id"]][:n_max], strict=False)
        ]
        vstats[name] = {
            "auroc": auroc(pos, neg),
            "acc_at_half": round(sum(hits) / len(hits), 4) if hits else None,
            "n_pos": len(pos),
            "n_neg": len(neg),
        }
    return {"curve": curve, "verifiers": vstats, "n_tasks": len(tasks)}
