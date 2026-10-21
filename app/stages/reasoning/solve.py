"""생각 예산 안에서 풀기 · 풀이 저장소.

예산 강제(budget forcing): 생각을 켜고 max_tokens = 예산 + 답 몫으로 부른다. 생각이 예산을 다 써서 답을 못 냈으면, 잘린 생각을
붙여 생각을 끈 채 '지금까지의 생각으로 답하라'고 한 번 더 부른다. 서버가 생각 예산 인자를 지원하지 않아도(llama-server) 같은 상한이
걸리고, 예산이 정확도에 주는 효과를 같은 방식으로 잴 수 있다. Claude API 는 확장 생각 예산(1024 이상)을 그대로 쓴다.

풀이 저장소: 과제 묶음 · 모델 · 예산 · 온도마다 풀이를 파일 하나에 쌓는다. 예산 곡선(RS1) · 라우팅(RS2) · 여러 번 풀기(RS3) ·
검증기(RS4) · 생각 검사(RS5) · 증류(RS6)가 같은 풀이를 다시 쓴다 — 이 PC 생성이 초당 13 토큰이라 같은 풀이를 다시 만들지 않으려는
것이고, 같은 풀이로 비교해야 검증기 · 라우터 차이가 생성의 우연이 아니라 방법의 차이가 된다.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

from app.core import llm
from app.core.config import get_settings
from app.stages.rlvr import tasks as tk

FORCE = "생각은 여기서 멈춥니다. 지금까지의 생각만으로, 마지막 줄에 '정답: …' 한 줄로 답하세요."
FORCE_THINK_CHARS = 3000  # 강제 답할 때 붙이는 생각 — 끝부분(결론에 가까운 쪽)을 남긴다


def root() -> Path:
    d = get_settings().data_dir / "reasoning"
    (d / "banks").mkdir(parents=True, exist_ok=True)
    return d


def solve(
    cfg: llm.LLMConfig, system: str, user: str, budget: int, answer_tokens: int = 200, temperature: float | None = 0.0
) -> dict[str, Any]:
    """→ {"text", "thinking", "think_tokens", "out_tokens", "seconds", "forced"}. budget=0 이면 생각 끔."""
    t0 = time.perf_counter()
    if budget <= 0:
        r = llm.chat(cfg, system, user, answer_tokens, temperature, thinking=False)
        return {"text": r["text"], "thinking": "", "think_tokens": 0, "out_tokens": r["usage"].get("output_tokens") or 0,
                "seconds": round(time.perf_counter() - t0, 2), "forced": False}  # fmt: skip
    r = llm.chat(cfg, system, user, budget + answer_tokens, temperature, thinking=True, thinking_budget=budget)
    think, text = r["reasoning"], r["text"]
    out = r["usage"].get("output_tokens") or 0
    # 생각 토큰은 따로 세어 주지 않는 서버가 많다 — 출력 토큰을 생각 · 답 글자 비율로 나눈 추정값
    think_tok = round(out * len(think) / max(1, len(think) + len(text))) if think else 0
    forced = False
    if tk.final_of(text) is None and (r["usage"].get("truncated") or r["usage"].get("reasoning_only") or not text.strip()):
        r2 = llm.chat(
            cfg, system, f"{user}\n\n[지금까지의 생각]\n{think[-FORCE_THINK_CHARS:]}\n\n{FORCE}", answer_tokens, temperature, thinking=False
        )
        text, forced = r2["text"], True
        out += r2["usage"].get("output_tokens") or 0
    return {
        "text": text,
        "thinking": think,
        "think_tokens": think_tok,
        "out_tokens": out,
        "seconds": round(time.perf_counter() - t0, 2),
        "forced": forced,
    }


# ── 풀이 저장소 ──────────────────────────────────────────────────────────────
def bank_key(tasks: str, model: str, budget: int, temperature: float) -> str:
    return f"{tasks}__{re.sub(r'[^A-Za-z0-9._-]', '_', model)[:60]}__b{budget}__t{temperature:g}"


def _path(key: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", key):
        raise ValueError(f"잘못된 저장소 이름: {key}")
    return root() / "banks" / f"{key}.jsonl"


def load_bank(key: str) -> dict[str, list[dict[str, Any]]]:
    """과제 id → 풀이 목록(만든 순서)."""
    p = _path(key)
    out: dict[str, list[dict[str, Any]]] = {}
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out.setdefault(r["task_id"], []).append(r)
    return out


def banks() -> list[dict[str, Any]]:
    out = []
    for p in sorted((root() / "banks").glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        tasks_, model, b, t = p.stem.rsplit("__", 3)
        out.append({"key": p.stem, "tasks": tasks_, "model": model, "budget": int(b[1:]), "temperature": float(t[1:]), "n_rows": len(rows),
                    "n_tasks": len({r["task_id"] for r in rows}), "acc": round(sum(r["correct"] for r in rows) / len(rows), 3) if rows else None})  # fmt: skip
    return out


def fill(
    key: str,
    items: list[dict[str, Any]],
    prompt_of,
    cfg: llm.LLMConfig,
    budget: int,
    n: int,
    temperature: float,
    answer_tokens: int = 200,
    progress=lambda f, m: None,
) -> dict[str, list[dict[str, Any]]]:
    """과제마다 풀이가 n 개가 되도록 모자란 만큼만 새로 푼다(저장소에 바로 이어 써서 중간에 멈춰도 남는다)."""
    bank = load_bank(key)
    need = [(t, i) for t in items for i in range(len(bank.get(t["id"], [])), n)]
    with _path(key).open("a", encoding="utf-8") as f:
        for k, (t, i) in enumerate(need):
            progress(k / max(1, len(need)), f"{t['id']} · {i + 1}/{n} (새로 {k + 1}/{len(need)})")
            system, user, obs = prompt_of(t)
            try:
                s = solve(cfg, system, user, budget, answer_tokens, temperature)
            except llm.LLMError as exc:
                s = {
                    "text": f"(오류 {exc})",
                    "thinking": "",
                    "think_tokens": 0,
                    "out_tokens": 0,
                    "seconds": 0,
                    "forced": False,
                    "error": True,
                }
            v = tk.verify(t, s["text"])
            row = {
                "task_id": t["id"],
                "i": i,
                "type": t["type"],
                **s,
                "final": v.get("final"),
                "correct": bool(v["correct"]),
                "candidates": v.get("candidates"),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            bank.setdefault(t["id"], []).append(row)
    return bank


def norm_final(task: dict[str, Any], final: str | None) -> str | None:
    """다수결용 정규화 — 같은 답의 다른 표기(제23조 · 제 23 조, 1,234 · 1234)를 한 표로."""
    if final is None:
        return None
    if task["kind"] == "number":
        m = re.findall(r"\d+", final.replace(",", ""))
        return m[0] if m else None
    if task["kind"] == "article":
        m = tk.ARTICLE.search(final)
        return (f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")) if m else None
    return tk._norm_text(final)[:40] or None
