"""RV3 보상 설계 · RV4 보상 해킹 감시.

보상 = 정답(1) + 형식(0.1, 마지막 '정답:' 줄) − 길이 벌점(답이 300자를 넘으면 조금씩) − 여러 답 벌점(정답 줄에 후보를 늘어놓으면).
항목별 기여를 함께 돌려줘 '왜 이 보상인가'를 설명할 수 있게 한다(8b 보상 함수와 같은 원칙).

보상 해킹: 보상은 오르는데 실제로 나아지지 않는 경우. 정답 확인이 있는 과제라도 생긴다 —
- 여러 답 늘어놓기: '정답: 23조 또는 24조' 처럼 후보를 늘어놓아 하나가 맞기를 노림(정답 확인이 첫 후보만 보게 막았지만 늘어나는지 감시)
- 길이 부풀리기: 생각을 길게 늘려 맞히는 비율은 같고 비용만 늚
- 학습 · 시험 차이: 학습 과제 정답률은 오르는데 시험(학습 외 유형 포함)은 그대로 — 외웠다
"""

from typing import Any

from app.stages.rlvr import tasks as tk

W = {"correct": 1.0, "format": 0.1, "length": -0.1, "multi": -0.3}
MAX_CHARS = 300


def score(task: dict[str, Any], text: str) -> dict[str, Any]:
    v = tk.verify(task, text)
    parts = {"correct": W["correct"] if v["correct"] else 0.0, "format": W["format"] if v.get("final") is not None else 0.0,
             "length": W["length"] * min(1.0, max(0, len(text) - MAX_CHARS) / MAX_CHARS), "multi": W["multi"] if (v.get("candidates") or 0) > 1 else 0.0}  # fmt: skip
    return {"reward": round(sum(parts.values()), 4), "parts": {k: round(x, 4) for k, x in parts.items()}, "correct": v["correct"], "final": v.get("final"),
            "chars": len(text), "candidates": v.get("candidates")}  # fmt: skip


def hacking(log: list[dict[str, Any]], train_acc: list[float] | None = None, test_acc: list[float] | None = None) -> dict[str, Any]:
    """학습 기록(걸음별 평균 보상 · 정답률 · 길이 · 여러 답 비율)과 학습 / 시험 정답률 → 경고."""
    flags = []
    if len(log) >= 4:
        first, last = log[: len(log) // 4 or 1], log[-(len(log) // 4 or 1) :]

        def m(xs: list[dict[str, Any]], k: str) -> float:
            return sum(x.get(k, 0) for x in xs) / len(xs)

        dr, dc = m(last, "reward") - m(first, "reward"), m(last, "correct") - m(first, "correct")
        if dr > 0.1 and dc < 0.03:
            flags.append(f"보상은 {dr:+.2f} 올랐는데 정답률은 {dc:+.2f} — 보상이 정답 밖에서 오름")
        if m(last, "chars") > m(first, "chars") * 1.5:
            flags.append(f"답 길이 {m(first, 'chars'):.0f} → {m(last, 'chars'):.0f}자 — 길이 부풀리기")
        if m(last, "multi") > m(first, "multi") + 0.1:
            flags.append(f"여러 답 늘어놓기 {m(first, 'multi'):.2f} → {m(last, 'multi'):.2f}")
    if train_acc and test_acc and len(train_acc) == 2 and len(test_acc) == 2:
        if train_acc[1] - train_acc[0] > 0.1 and test_acc[1] - test_acc[0] < 0.02:
            flags.append(
                f"학습 과제 정답률 {train_acc[0]:.2f} → {train_acc[1]:.2f}, 시험은 {test_acc[0]:.2f} → {test_acc[1]:.2f} — 외웠을 수 있음"
            )
    return {"flags": flags, "ok": not flags}
